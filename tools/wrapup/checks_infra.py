# -*- coding: utf-8 -*-
"""wrapup_check 子模块: checks_infra"""
from tools.wrapup.base import *  # noqa: F403,F401
from tools.wrapup.base import _results, _report, _warn, _read_text  # 显式导入

def check_scheduler_sync():
    import json
    # 从 scheduler.py 提取 _defaults 的 key
    py_text = _read_text(SCHEDULER_PY)
    if not py_text:
        _report("调度器配置与代码同步", False, "scheduler.py 无法读取")
        return
    m = re.search(r"_defaults\s*=\s*\{(.*?)\}", py_text, re.DOTALL)
    if not m:
        _report("调度器配置与代码同步", False, "scheduler.py 中未找到 _defaults 字典")
        return
    code_keys = set(re.findall(r'"(\w+)":', m.group(1)))

    # 从 scheduler.json 读取 key（排除 _ 开头的说明字段）
    json_text = _read_text(SCHEDULER_JSON)
    if not json_text:
        _warn("调度器配置与代码同步", "scheduler.json 不存在（将用代码默认值，可接受）")
        return
    try:
        cfg = json.loads(json_text)
    except Exception as e:
        _report("调度器配置与代码同步", False, f"scheduler.json 格式错误: {e}")
        return
    json_keys = {k for k in cfg if not k.startswith("_")}

    missing_in_json = code_keys - json_keys
    extra_in_json = json_keys - code_keys
    if missing_in_json:
        _report("调度器配置与代码同步", False,
                f"scheduler.json 缺少: {sorted(missing_in_json)}")
    elif extra_in_json:
        _warn("调度器配置与代码同步",
              f"scheduler.json 多出（无效）: {sorted(extra_in_json)}")
    else:
        _report("调度器配置与代码同步", True, f"{len(code_keys)} 个任务 key 完全一致")


# ---------------------------------------------------------------------------
# 检查 7：核心文件地图覆盖（基线快照法）
# ---------------------------------------------------------------------------
# 原理：维护 tools/.wrapup_baseline.txt（已知文件清单）。
# 不在基线中 且 不在 AGENTS.md 中的新文件 → 红灯（漏登记）。
# 换机/坚果云全量同步后，跑一次 --update-baseline 刷新基线即可。
_MAP_SCAN_DIRS = ["core", "knowledge", "server", "engines"]
_MAP_WHITELIST = {"__init__.py", "__pycache__"}
_BASELINE_FILE = os.path.join(BASE_DIR, "tools", ".wrapup_baseline.txt")
_SKIP_COUNT_FILE = os.path.join(BASE_DIR, "tools", ".wrapup_skip_count.txt")
_MAX_CONSECUTIVE_SKIP = 2

# 改动量阈值（P1-5: 移至 base.py 共享，checks_code 也需要）

def _scan_map_files():
    """扫描核心目录下的 .py 文件，返回相对路径集合"""
    found = set()
    for d in _MAP_SCAN_DIRS:
        dir_path = os.path.join(BASE_DIR, d)
        if not os.path.isdir(dir_path):
            continue
        for fname in os.listdir(dir_path):
            if fname.endswith(".py") and fname not in _MAP_WHITELIST:
                found.add(f"{d}/{fname}")
    return found


def _load_baseline():
    text = _read_text(_BASELINE_FILE)
    return {line.strip() for line in text.splitlines() if line.strip()}


def check_file_map(update_baseline=False):
    agents_text = _read_text(AGENTS_MD)
    if not agents_text:
        _report("核心文件地图覆盖", False, "AGENTS.md 无法读取")
        return
    current = _scan_map_files()

    if update_baseline:
        with open(_BASELINE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(current)) + "\n")
        _report("核心文件地图覆盖", True, f"基线已刷新（{len(current)} 个文件）")
        return

    baseline = _load_baseline()
    if not baseline:
        # 首次运行：自动生成基线并提示
        with open(_BASELINE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(current)) + "\n")
        _warn("核心文件地图覆盖",
              f"首次运行，已自动生成基线（{len(current)} 个文件），下次起生效")
        return

    new_files = current - baseline
    uncovered = [f for f in sorted(new_files)
                 if os.path.basename(f) not in agents_text]
    if uncovered:
        _report("核心文件地图覆盖", False,
                f"新增但未登记到AGENTS.md: {uncovered[:5]}" + ("..." if len(uncovered) > 5 else ""))
    else:
        detail = "无新增文件" if not new_files else f"新增 {len(new_files)} 个文件均已登记"
        _report("核心文件地图覆盖", True, detail)


# ---------------------------------------------------------------------------
# 检查 8：页面路由注册完整
# ---------------------------------------------------------------------------
# jinshuiyao-guide/ 下的 html 文件，应在 _PAGE_ROUTES 或 _EXTERNAL_PAGE_ROUTES 中注册
_PAGE_WHITELIST = {
    "jinshuiyao-guide.html",   # 导航页本身（通过 /jinshuiyao-guide 注册）
}


def check_page_routes():
    static_text = _read_text(STATIC_PY)
    if not static_text:
        _report("页面路由注册完整", False, "static.py 无法读取")
        return
    # 页面路由双真源：static.py 路由表 OR router.py 页面路由（review-dashboard 等由 router 先行响应）
    router_text = _read_text(ROUTER_PY)
    if not os.path.isdir(GUIDE_DIR):
        _warn("页面路由注册完整", "jinshuiyao-guide/ 目录不存在")
        return
    html_files = [f for f in os.listdir(GUIDE_DIR)
                  if f.endswith(".html") and f not in _PAGE_WHITELIST]
    unregistered = []
    for fname in html_files:
        # 文件名出现在 static.py 或 router.py 中即视为已注册
        # （router.py 只写 URL 路径，故去掉 .html 扩展名再匹配一次）
        base = fname[:-5] if fname.endswith(".html") else fname
        if fname not in static_text and fname not in (router_text or "") \
                and base not in (router_text or ""):
            # 也检查 _shared 子目录中的（不需要注册）
            unregistered.append(fname)
    if unregistered:
        _report("页面路由注册完整", False,
                f"未注册路由: {unregistered[:5]}" + ("..." if len(unregistered) > 5 else ""))
    else:
        _report("页面路由注册完整", True, f"{len(html_files)} 个页面全部有路由")


# ---------------------------------------------------------------------------
# 检查 9：测试全绿（含跳过频率限制）
# ---------------------------------------------------------------------------
def _read_skip_count():
    """读取连续跳过次数（按天重置，每天最多跳过_MAX_CONSECUTIVE_SKIP次）"""
    try:
        with open(_SKIP_COUNT_FILE, "r", encoding="utf-8") as f:
            data = f.read().strip()
            if not data:
                return 0, ""
            parts = data.split(",")
            if len(parts) == 2:
                count = int(parts[0])
                last_date = parts[1]
                return count, last_date
            return int(parts[0]), ""
    except Exception:
        return 0, ""


def _write_skip_count(count, today_str):
    """写入连续跳过次数 + 日期"""
    try:
        with open(_SKIP_COUNT_FILE, "w", encoding="utf-8") as f:
            f.write(f"{count},{today_str}")
    except Exception:
        pass


def check_tests(skip=False, today_str=""):
    skip_count, last_date = _read_skip_count()

    # 如果日期变了，重置计数（按天重置）
    if last_date and last_date != today_str:
        skip_count = 0

    # 如果当天跳过已达上限，强制跑测试（忽略 --skip-tests）
    forced = False
    if skip and skip_count >= _MAX_CONSECUTIVE_SKIP:
        forced = True
        skip = False
        _warn("测试跳过超限",
              f"今日已跳过 {skip_count} 次（上限 {_MAX_CONSECUTIVE_SKIP}），强制跑全量测试")

    if skip:
        new_count = skip_count + 1
        _write_skip_count(new_count, today_str)
        remaining = _MAX_CONSECUTIVE_SKIP - new_count
        if remaining > 0:
            _warn("测试全绿",
                  f"已跳过（今日第{new_count}次，还可跳过{remaining}次后强制跑）")
        else:
            _warn("测试全绿",
                  f"已跳过（今日第{new_count}次，下次将强制跑全量测试）")
        return

    # 找 python：优先 venv
    venv_python = os.path.join(MODEL_DIR, "venv_314", "Scripts", "python.exe")
    python_exe = venv_python if os.path.isfile(venv_python) else sys.executable
    tests_dir = os.path.join(BASE_DIR, "tests")
    if not os.path.isdir(tests_dir):
        _report("测试全绿", False, "tests/ 目录不存在")
        return
    print("  [..] 正在跑 pytest（约2分钟）...", flush=True)
    try:
        proc = subprocess.run(
            [python_exe, "-m", "pytest", "tests/", "-q", "--tb=no", "--no-header"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        # 提取摘要行，如 "746 passed in 118.53s"
        summary_m = re.search(r"(\d+ passed[^\n]*)", output)
        summary = summary_m.group(1).strip() if summary_m else output.strip()[-100:]
        if proc.returncode == 0:
            # 测试全绿，重置当天跳过计数
            _write_skip_count(0, today_str)
            _report("测试全绿", True, summary + ("（强制）" if forced else ""))
        else:
            fail_m = re.search(r"(\d+ failed[^\n]*)", output)
            detail = fail_m.group(1).strip() if fail_m else f"退出码 {proc.returncode}"
            _report("测试全绿", False, detail + ("（强制）" if forced else ""))
    except subprocess.TimeoutExpired:
        _report("测试全绿", False, "pytest 超时（>10分钟）" + ("（强制）" if forced else ""))
    except Exception as e:
        _report("测试全绿", False, f"执行失败: {e}" + ("（强制）" if forced else ""))


# ---------------------------------------------------------------------------
# 检查 10：测试跳过频率合规
# ---------------------------------------------------------------------------
def check_skip_frequency(today_str=""):
    skip_count, last_date = _read_skip_count()
    # 日期变了就重置
    if last_date and last_date != today_str:
        skip_count = 0
    if skip_count == 0:
        _report("测试跳过频率合规", True, "今日暂无跳过记录")
    elif skip_count <= _MAX_CONSECUTIVE_SKIP:
        remaining = _MAX_CONSECUTIVE_SKIP - skip_count
        _report("测试跳过频率合规", True,
                f"今日已跳过 {skip_count} 次（上限 {_MAX_CONSECUTIVE_SKIP}），还可跳过 {remaining} 次")
    else:
        _report("测试跳过频率合规", False,
                f"今日已跳过 {skip_count} 次（上限 {_MAX_CONSECUTIVE_SKIP}），超限！本次强制跑测试")


# ---------------------------------------------------------------------------
# 检查 11：源码改动真实性验证（防"完成欺诈"核心）
# ---------------------------------------------------------------------------
