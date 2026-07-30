# -*- coding: utf-8 -*-
"""wrapup_check 子模块: checks_linkage"""
from tools.wrapup.base import *  # noqa: F403,F401
from tools.wrapup.base import _results, _report, _warn, _read_text  # 显式导入
from tools.wrapup.checks_integrity import get_changed_files_by_hash  # P1-5: 跨模块依赖

def _run_git(args):
    """健壮调用 git：优先系统 git，回退硬编码路径。返回 (rc, stdout) 或 None。"""
    candidates = []
    sys_git = shutil.which("git")
    if sys_git:
        candidates.append(sys_git)
    candidates.append(r"D:\下载\Git\bin\git.exe")
    for g in candidates:
        if not g or not os.path.exists(g):
            continue
        try:
            r = subprocess.run([g] + args, cwd=MODEL_DIR, capture_output=True,
                               text=True, errors="replace", timeout=15)
            return r.returncode, r.stdout
        except Exception:
            continue
    return None


def _git_diff_added_routes(rel_path, is_new):
    """提取文件新增的 /api/ 路由。is_new=True 时全部路由算新增。返回 set。"""
    route_re = re.compile(r'["\'](/api/[A-Za-z0-9_/-]+)["\']')
    abs_path = os.path.join(BASE_DIR, rel_path)
    if is_new:
        return set(route_re.findall(_read_text(abs_path)))
    res = _run_git(["diff", "HEAD", "--", rel_path])
    if res is None:
        return set()  # git 不可用，跳过（不误报）
    rc, out = res
    if rc != 0:
        return set()
    added = set()
    for line in out.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added |= set(route_re.findall(line))
    return added


def _collect_frontend_route_refs():
    """收集前端(*.js/*.html)引用的所有 /api/ 路由。"""
    route_re = re.compile(r'["\'](/api/[A-Za-z0-9_/-]+)["\']')
    refs = set()
    search_dirs = [
        os.path.join(BASE_DIR, "server", "templates"),
        os.path.join(BASE_DIR, "html"),
        os.path.join(BASE_DIR, "jinshuiyao-guide"),
        os.path.join(BASE_DIR, "static"),
    ]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.endswith((".js", ".html", ".htm")):
                    refs |= set(route_re.findall(_read_text(os.path.join(root, fn))))
    refs |= set(route_re.findall(_read_text(os.path.join(BASE_DIR, "server", "handlers", "static.py"))))
    return refs


def _detect_noncanonical_experience_tags():
    """检测经验收集箱分类标签体系之外的非规范标签（经验条目里出现的）。返回 set。"""
    text = _read_text(EXPERIENCE_FILE)
    if not text:
        return set()
    canonical = {"架构", "后端", "前端", "测试", "协作", "运维", "安全", "踩坑", "最佳实践"}
    non_canon = set()
    for m in re.finditer(r'^### 2026-\d{2}-\d{2} .+?(\s*\[.+\])?\s*$', text, re.MULTILINE):
        tags_str = m.group(1) or ""
        for t in re.findall(r'\[([^\]]+)\]', tags_str):
            if t not in canonical:
                non_canon.add(t)
    return non_canon


def check_change_linkage(today_str, mode="NORMAL"):
    """改动联动自动检查（防"修A忘改B"·JS-20260723-41新增）。

    检测三类契约联动（严格只报"明确悬空"，避免误报红灯破门禁）：
      L1 API契约：server 处理器新增 /api/ 路由 → 前端(*.js/*.html)须引用，否则前端未同步(警告)。
      L2 经验标签：经验收集箱出现非规范标签 → 须同步自检/模式库白名单(警告)。
      L3 领域调度：domains/*/domain.py 改动且 core/scheduler.py 未同步 → 软警告。
    设计：v1 全以 WARN 级浮现（供用户兜底人工确认），不阻断门禁；git 不可用时 L1 跳过。
    理由：误报红灯破门禁本身是头号失败模式，故先 WARN 验证低误报后再考虑升 RED。
    """
    changed_files, new_files, is_first = get_changed_files_by_hash()
    if is_first:
        _report("改动联动检查", True, "首次运行已建基线，下次生效")
        return
    all_changed = [f for f in (changed_files + new_files) if f.endswith(".py")]
    if not all_changed:
        _report("改动联动检查", True, "今日无 .py 改动，无需联动检查")
        return

    new_set = set(new_files)
    warns = []  # (detail,)

    # ---- L1: API 路由 ↔ 前端 ----
    handlers = [f for f in all_changed
                if f.startswith("server/handlers/") or f == "server/router.py"]
    if handlers:
        added = set()
        for f in handlers:
            added |= _git_diff_added_routes(f, f in new_set)
        if added:
            frontend_refs = _collect_frontend_route_refs()
            missing = sorted(r for r in added if r not in frontend_refs)
            if missing:
                warns.append(
                    f"新增API路由前端未引用（改了API格式但前端*.js/*.html没同步）：{missing[:5]}")
        else:
            # 无新增路由（git不可用或处理器未加路由）→ 不误报
            pass

    # ---- L2: 经验标签 ↔ 白名单 ----
    exp_rel = "金水谣数据/log/经验收集箱.md".replace("\\", "/")
    if exp_rel in [c.replace("\\", "/") for c in (changed_files + new_files)]:
        non_canon = _detect_noncanonical_experience_tags()
        if non_canon:
            warns.append(
                f"经验收集箱出现非规范标签（须同步自检/模式库白名单）：{sorted(non_canon)[:5]}")

    # ---- L3: domain.py ↔ scheduler.py ----
    domains = [f for f in all_changed if f.startswith("domains/") and f.endswith("domain.py")]
    if domains:
        sched_changed = any("core/scheduler.py" in f for f in all_changed)
        if not sched_changed:
            names = [os.path.basename(d) for d in domains]
            warns.append(
                f"领域文件改动({names})但 core/scheduler.py 未同步——若新增了调度应调用的方法请同步")

    if not warns:
        _report("改动联动检查", True,
                f"联动一致（{len(all_changed)}个.py："
                f"L1={'Y' if handlers else 'N'} "
                f"L2={'Y' if exp_rel in [c.replace(chr(92),'/') for c in (changed_files+new_files)] else 'N'} "
                f"L3={'Y' if domains else 'N'}）")
        return
    for detail in warns:
        _warn("改动联动检查", detail)
    _report("改动联动检查", True, f"联动检查发现 {len(warns)} 条软警告（见上方），无硬性悬空，已浮现供人工兜底")


