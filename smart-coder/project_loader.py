# -*- coding: utf-8 -*-
"""金水谣 · 项目自动加载器（纯标准库，零外部依赖）
================================================
对应需求 1「自动识别与加载」：
  用户给一个项目目录（或模型文件夹），系统自动：
    1) 解析目录结构，生成可视化目录树；
    2) 识别入口文件 / 配置文件 / 核心模块 / 普通模块 / 文档 / 测试 / 数据 / 资源；
    3) 给出每个文件的重要性等级（高 / 中 / 低）与一句中文用途说明。
  不需手动指定路径，上传/粘贴目录即可。
输出为 JSON 友好的字典，供前端目录树直接渲染。
"""
import os
import re
import json

# 跳过的目录（隐藏/缓存/依赖/大体积），避免把无关注释进来
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache", "node_modules",
    ".venv", "venv", "env", ".idea", ".vscode", "dist", "build",
    ".uploads", "archive", ".workbuddy",
}

# 文本类扩展名（用于读取内容、统计行数、做引用分析）
_TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".c", ".cpp", ".h",
    ".cs", ".rb", ".php", ".rs", ".swift", ".kt", ".scala", ".sh", ".bat",
    ".ps1", ".sql", ".html", ".htm", ".css", ".scss", ".json", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".conf", ".md", ".txt", ".rst",
    ".xml", ".csv", ".log",
}

_PURPOSE = {
    "entry":  "项目入口：程序从这里开始运行，启动脚本/双击通常指向它。",
    "config": "配置文件：存放参数、密钥、开关；改这里一般不动代码逻辑。",
    "core":   "核心代码：实现主要功能的关键模块，改动需谨慎。",
    "module": "功能模块：可复用的代码单元。",
    "doc":    "说明文档：介绍用法、设计或记录，供人阅读。",
    "test":   "测试文件：用来验证功能是否正确，跑测试时执行。",
    "data":   "数据文件：模型/程序读取的数据。",
    "asset":  "资源文件：图片、样式等素材。",
    "other":  "其他文件。",
}

# 重要性等级文字映射
_IMP_LABEL = {"high": "高", "medium": "中", "low": "低"}


def _ext(name):
    return os.path.splitext(name)[1].lower()


def _classify(name, ext):
    """根据文件名与扩展名初判类别。"""
    low = name.lower()
    # 测试（优先判断，避免 run_tests / *_test 被误判为入口）
    if ext == ".py" and (low.startswith("test_") or re.search(r"_test[s]?\.py$", low)):
        return "test"
    if ext in (".robot", ".feature"):
        return "test"
    # 入口文件
    if ext == ".py" and (
        low.startswith("main") or low in ("app.py", "server.py", "run.py",
        "manage.py", "wsgi.py", "__main__.py", "start.py", "bot.py")
        or "server" in low or low.startswith("run_") or low.startswith("start_")
        or "guide" in low or "launcher" in low
    ):
        return "entry"
    if ext in (".bat", ".ps1", ".sh") and (
        low.startswith("启动") or low.startswith("start") or "launcher" in low
        or low in ("启动金水谣助手.bat", "启动deepseek助手.bat")
    ):
        return "entry"
    if (ext in (".html", ".htm")) and (low in ("index.html", "门户".replace("门户", "index") + ".html") or "门户" in name or low.startswith("index")):
        return "entry"
    # 配置
    if ext in (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env") \
       or low in ("config.py", "settings.py", "config.js", "settings.js") \
       or "config" in low or "setting" in low:
        return "config"
    # 测试
    if (ext == ".py" and (low.startswith("test_") or low.endswith("_test.py") or "_test_" in low)) \
       or ext in (".robot",):
        return "test"
    # 文档
    if ext in (".md", ".txt", ".rst", ".html", ".htm") and not low.startswith("index"):
        return "doc"
    # Python 代码 → 默认核心模块
    if ext == ".py":
        return "core"
    # 其他代码
    if ext in (".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".c", ".cpp",
               ".h", ".cs", ".rb", ".php", ".rs", ".swift", ".kt", ".scala", ".sh"):
        return "core"
    # 数据
    if ext in (".csv", ".xlsx", ".xls", ".parquet", ".db", ".sqlite", ".tsv", ".jsonl"):
        return "data"
    # 资源
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".bmp",
               ".css", ".scss", ".woff", ".woff2", ".ttf", ".eot"):
        return "asset"
    return "other"


def _count_loc(path, ext):
    """统计文本行数（只读前 200KB，避免卡在大文件）。"""
    if ext not in _TEXT_EXTS:
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read(200_000)
        return data.count("\n") + (1 if data and not data.endswith("\n") else 0)
    except Exception:
        return 0


def _read_head(path, ext, limit=4000):
    if ext not in _TEXT_EXTS:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except Exception:
        return ""


def _analyze_imports(py_files):
    """粗略统计：每个模块名被多少个其他 py 文件引用（用于识别核心模块）。"""
    # 建立 文件名(去扩展) -> 被引用计数
    ref_count = {}
    for fp, src in py_files.items():
        base = os.path.splitext(os.path.basename(fp))[0]
        # 找 import xxx / from xxx import
        imports = set(re.findall(r"(?:^|\n)\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
                                 src))
        names = set()
        for m in imports:
            name = (m[0] or m[1] or "").split(".")[0]
            if name:
                names.add(name)
        for n in names:
            ref_count[n] = ref_count.get(n, 0) + 1
    return ref_count


def scan_directory(root, max_files=1500, max_depth=12):
    """扫描目录，返回目录树 + 文件清单 + 重要性分级。

    返回字典：
    {
      "root": 绝对路径, "root_name": 根目录名, "error": None,
      "total": 文件数, "tree": 嵌套字典(供前端渲染),
      "files": [ {rel, name, ext, category, importance, importance_label,
                  purpose, size, loc, referenced_by} , ... ]
    }
    """
    out = {"root": root, "root_name": os.path.basename(root.rstrip(os.sep)) or root,
           "error": None, "total": 0, "tree": None, "files": []}
    if not os.path.isdir(root):
        out["error"] = f"目录不存在：{root}"
        return out

    collected = []  # (abspath, rel, name, ext, size, loc, head)
    py_sources = {}
    depth_ok = True

    for dirpath, dirnames, filenames in os.walk(root):
        # 过滤跳过目录
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, root)
        cur_depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if cur_depth > max_depth:
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.startswith(".") and fn not in ("env",):
                # 跳过隐藏文件（除 .env）
                if not fn.endswith(".env") and fn != ".env":
                    continue
            ab = os.path.join(dirpath, fn)
            try:
                sz = os.path.getsize(ab)
            except Exception:
                sz = 0
            ext = _ext(fn)
            rel = os.path.relpath(ab, root).replace(os.sep, "/")
            head = ""
            if ext in _TEXT_EXTS and sz < 5_000_000:
                head = _read_head(ab, ext)
            loc = _count_loc(ab, ext) if ext == ".py" else 0
            collected.append((ab, rel, fn, ext, sz, loc, head))
            if ext == ".py":
                py_sources[ab] = head
            if len(collected) >= max_files:
                depth_ok = False
                break
        if not depth_ok:
            break

    ref_count = _analyze_imports(py_sources)

    files = []
    for (ab, rel, fn, ext, sz, loc, head) in collected:
        category = _classify(fn, ext)
        base = os.path.splitext(fn)[0]
        referenced_by = ref_count.get(base, 0)

        # 重要性分级
        if category in ("entry", "config") or loc >= 300 or referenced_by >= 3:
            importance = "high"
        elif category in ("core", "doc") or referenced_by >= 1 or loc >= 80:
            importance = "medium"
        else:
            importance = "low"

        # 用途说明（带一点针对性）
        purpose = _PURPOSE.get(category, "其他文件。")
        if category == "core" and referenced_by >= 3:
            purpose = f"核心模块：被 {referenced_by} 个文件引用，是项目枢纽，改动务必小心。"
        elif category == "config" and "key" in fn.lower():
            purpose = "密钥/配置：可能含 API Key，请勿外泄。"
        elif category == "entry":
            purpose = "入口文件：项目从这里启动，通常第一个看它。"

        files.append({
            "rel": rel, "name": fn, "ext": ext, "category": category,
            "importance": importance, "importance_label": _IMP_LABEL[importance],
            "purpose": purpose, "size": sz, "loc": loc,
            "referenced_by": referenced_by,
        })

    # 按重要性+名称排序（高 -> 低），便于前端优先展示
    order = {"high": 0, "medium": 1, "low": 2}
    files.sort(key=lambda x: (order[x["importance"]], x["category"], x["rel"]))

    out["files"] = files
    out["total"] = len(files)
    out["tree"] = _build_tree(out["root_name"], files)
    return out


def _build_tree(root_name, files):
    """由扁平文件列表构造嵌套目录树。"""
    root = {"name": root_name, "is_dir": True, "children": {},
            "category": None, "importance": None, "purpose": ""}
    for f in files:
        parts = f["rel"].split("/")
        node = root
        for i, p in enumerate(parts):
            is_last = (i == len(parts) - 1)
            if is_last:
                fcopy = dict(f)
                fcopy["is_dir"] = False
                node["children"][p] = fcopy
            else:
                if p not in node["children"]:
                    node["children"][p] = {"name": p, "is_dir": True,
                                           "children": {}, "category": None,
                                           "importance": None, "purpose": ""}
                node = node["children"][p]
    return _tree_to_list(root)


def _tree_to_list(node):
    if node.get("is_dir"):
        ch = list(node["children"].values())
        # 目录在前、文件在后；同级按名称
        ch.sort(key=lambda x: (not x.get("is_dir", False), x["name"].lower()))
        node["children"] = [_tree_to_list(c) for c in ch]
    return node


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------
def _self_test():
    import tempfile
    import shutil
    print("== project_loader 自测 ==")
    tmp = tempfile.mkdtemp(prefix="pl_test_")
    try:
        # 构造一个小项目
        os.makedirs(os.path.join(tmp, "pkg"))
        open(os.path.join(tmp, "main.py"), "w", encoding="utf-8").write(
            "import pkg.core\nprint('hi')\n")
        open(os.path.join(tmp, "pkg", "core.py"), "w", encoding="utf-8").write(
            "def f():\n    return 1\n" * 50)  # 较长
        open(os.path.join(tmp, "config.json"), "w", encoding="utf-8").write(
            '{"k": 1}')
        open(os.path.join(tmp, "readme.md"), "w", encoding="utf-8").write(
            "# 说明")
        open(os.path.join(tmp, "run_tests.py"), "w", encoding="utf-8").write(
            "def test():\n    pass\n")

        r = scan_directory(tmp)
        assert r["error"] is None, r
        assert r["total"] == 5, r["total"]
        cats = {f["name"]: f["category"] for f in r["files"]}
        assert cats["main.py"] == "entry", cats
        assert cats["config.json"] == "config", cats
        assert cats["core.py"] == "core", cats
        assert cats["readme.md"] == "doc", cats
        assert cats["run_tests.py"] == "test", cats
        # 重要性：main 入口应高
        imp = {f["name"]: f["importance"] for f in r["files"]}
        assert imp["main.py"] == "high", imp
        # 目录树存在且含 pkg 子节点
        assert r["tree"]["is_dir"] is True
        names = [c["name"] for c in r["tree"]["children"]]
        assert "pkg" in names and "main.py" in names, names
        print("✓ 目录扫描：5 文件分类正确、入口标记高重要性、目录树生成")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("project_loader 自测通过 ✅")


if __name__ == "__main__":
    _self_test()
