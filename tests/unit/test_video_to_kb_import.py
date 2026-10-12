"""JS-20261012-18：video_to_kb 导入链守卫（core/infra 跨包裸导入）。

背景（真实缺陷，已修）：
- `core/infra/video_to_kb.py` 原 `from content_refiner import ContentRefiner` 是**跨包裸导入**，
  content_refiner 实际在 `core/ai/`；以 `core.infra.video_to_kb` 方式导入时必抛
  ModuleNotFoundError ⇒ `server/handlers/knowledge.py` 的 `/api/video/ingest` 运行期 500。
- 同文件 `_PROJECT_ROOT = os.path.dirname(_THIS)` 算出的是 `core/` 而非仓库根，
  导致 KB_DIR 指向 `core/knowledge/用户知识库`（错误目录）。

本文件三层防护：
1. 端到端：模块能被真正导入，且 KB_DIR 落在仓库根；
2. 闸：core/infra 下不得出现「目标模块实际在 core/ai 或 core/dispatch」的无保护裸导入；
3. 反证：给闸喂已知坏样本必须检出，喂正确写法必须不报（否则闸本身是假的）。

注：本文件刻意使用模块级函数而非 class——`code_health_gate.max_function_lines`
把 class 体当一个"函数"统计，用 class 会被判为新增超阈值（已知门禁口径缺陷）。
"""

import ast
import importlib
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_INFRA_DIR = os.path.join(_ROOT, "core", "infra")
_OTHER_PKGS = ("ai", "dispatch")


def _sibling_pkg_modules():
    """返回 {顶层模块名: 所在子包名}，仅统计 core/ai、core/dispatch 下的 .py。"""
    out = {}
    for pkg in _OTHER_PKGS:
        d = os.path.join(_ROOT, "core", pkg)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.endswith(".py") and not fn.startswith("_"):
                out.setdefault(fn[:-3], pkg)
    return out


def _handler_exc_names(h):
    """取 except 子句捕获的异常名集合；裸 `except:` 视为空集（不算豁免）。"""
    names = set()
    t = getattr(h, "type", None)
    if t is None:
        return names
    items = t.elts if isinstance(t, ast.Tuple) else [t]
    for it in items:
        if isinstance(it, ast.Name):
            names.add(it.id)
        elif isinstance(it, ast.Attribute):
            names.add(it.attr)
    return names


def _exempt_ranges(tree):
    """try/except ImportError(ModuleNotFoundError) 内的行号范围——有意的兼容回退，豁免。

    依据：AST 闸扫太宽＝假警。video_to_kb 里「包导入优先 + 裸导入回退」是刻意设计，
    闸若连它一起报，就是拿假警换真信号，反而让真缺陷被忽略（第一版实测误报过）。
    """
    ranges = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            if _handler_exc_names(h) & {"ImportError", "ModuleNotFoundError"}:
                for stmt in h.body:
                    ranges.append((stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno)))
    return ranges


def _find_cross_pkg_bare_imports(src_dir):
    """在 src_dir 的 .py 中找出**无保护**的跨包裸导入。

    返回 ['文件:行号 from X import ... (实际在 core/Y/)']。
    判定：只认 `from X import ...`（level==0，非相对导入）；`from core.ai.X import ...`
    顶层名是 `core`，不在目标集合内，不误报；位于 try/except ImportError 内的
    回退导入属刻意兼容，豁免。
    """
    targets = _sibling_pkg_modules()
    bad = []
    if not os.path.isdir(src_dir):
        return bad
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(src_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except Exception:
            continue
        exempt = _exempt_ranges(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top = node.module.split(".")[0]
                if top not in targets:
                    continue
                if any(lo <= node.lineno <= hi for lo, hi in exempt):
                    continue
                bad.append("%s:%s from %s import ... (实际在 core/%s/)"
                           % (fn, node.lineno, node.module, targets[top]))
    return bad


def _collect_hits(sample):
    """对源码字符串跑同一判定，返回命中的顶层模块名列表（供反证用例复用）。"""
    tree = ast.parse(sample)
    targets = _sibling_pkg_modules()
    exempt = _exempt_ranges(tree)
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            top = n.module.split(".")[0]
            if top in targets and not any(lo <= n.lineno <= hi for lo, hi in exempt):
                hits.append(top)
    return hits, exempt


# ── 1. 端到端：模块真能导入，且知识库目录落在仓库根 ──

def test_module_imports_ok():
    mod = importlib.import_module("core.infra.video_to_kb")
    assert hasattr(mod, "ingest_to_kb"), "ingest_to_kb 缺失，/api/video/ingest 会 500"
    assert hasattr(mod, "ContentRefiner"), "ContentRefiner 未解析到"


def test_kb_dir_under_project_root():
    mod = importlib.import_module("core.infra.video_to_kb")
    kb = os.path.abspath(mod.KB_DIR)
    assert kb.startswith(os.path.abspath(_ROOT)), "KB_DIR 不在仓库根下: %s" % kb
    # 历史 bug：_PROJECT_ROOT 少算一级 → core/knowledge/用户知识库
    assert os.path.sep + "core" + os.path.sep + "knowledge" not in kb, \
        "KB_DIR 落到了 core/knowledge（_PROJECT_ROOT 少算一级的回归）: %s" % kb
    assert kb.endswith(os.path.join("knowledge", "用户知识库")), \
        "KB_DIR 应指向 仓库根/knowledge/用户知识库，实际: %s" % kb


# ── 2. 闸：core/infra 下不得有跨包裸导入 ──

def test_core_infra_has_no_cross_pkg_bare_import():
    bad = _find_cross_pkg_bare_imports(_INFRA_DIR)
    assert not bad, (
        "core/infra 存在跨包裸导入（以包方式导入时会 ModuleNotFoundError）共 %d 处:\n%s"
        % (len(bad), "\n".join(bad))
    )


# ── 3. 反证：闸必须能响，也必须不误报 ──

def test_guard_detects_known_bad_sample():
    """坏样本必须检出——否则闸是假闸。

    依据：守卫两失败模式里「静默」才是真敌人；只跑真实代码全绿，
    证明不了闸会响。
    """
    sample = (
        "import os\n"
        "from video_extractor import VideoExtractor\n"
        "from content_refiner import ContentRefiner\n"
    )
    targets = _sibling_pkg_modules()
    assert "content_refiner" in targets, "样本前提失效：core/ai 下应存在 content_refiner.py"
    hits, _ = _collect_hits(sample)
    assert "content_refiner" in hits, "闸未检出已知坏样本 → 闸本身无效（假绿）"


def test_guard_excuses_fallback_inside_import_error():
    """try/except ImportError 内的回退导入不得报警（防假警）。

    实测教训：第一版闸把 video_to_kb.py:63 的刻意回退也报了出来。
    """
    sample = (
        "try:\n"
        "    from core.ai.content_refiner import ContentRefiner\n"
        "except ImportError:\n"
        "    from content_refiner import ContentRefiner\n"
    )
    hits, exempt = _collect_hits(sample)
    assert exempt, "豁免逻辑未生效（except ImportError 未被识别）"
    assert hits == [], "受保护的回退导入被误报: %s" % hits


def test_guard_does_not_flag_package_import():
    """正确的包导入不得被误报（防假警）。"""
    sample = "from core.ai.content_refiner import ContentRefiner\n"
    hits, _ = _collect_hits(sample)
    assert hits == [], "包导入被误报: %s" % hits
