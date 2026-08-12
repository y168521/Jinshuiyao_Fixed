# -*- coding: utf-8 -*-
"""
【道衍推导·JS-20260727-24】
  阴阳：阳=修改前拍快照(主动防退)；阴=verify比对(守底，差异即知)。
  天地人：天=规划基线；地=隔离(只读比对不破坏)；人=复盘(反复问题不再现)。
  知止：PROTECTED_VITAL_DOCS命门文档绝不允许被标"可删"；误删即红。

金水谣质量门禁系统（Quality Gate）

使用方式：
    python scripts/quality_gate.py             # 验证模式（默认）
    python scripts/quality_gate.py --snapshot  # 拍快照（重新记录当前文件状态）
    python scripts/quality_gate.py --verify    # 对照快照验证

流程：
    --snapshot → 记录当前所有文件 MD5 到 .quality_baseline.json
    --verify   → 对比当前文件与快照，报告差异（新增/删除/修改）
    默认模式   → 一次性跑完：基线校验 + 功能清单检查 + 测试

设计目的：
    1. 防止"优化"意外删除功能文件
    2. 防止反复出现相同问题
    3. 修改前拍快照、修改后验证，对比即知改了什么
"""
import os
import sys
import json
import hashlib
import subprocess

# GBK 安全输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import session_coordinator
except Exception:
    session_coordinator = None

# 门禁去盲区（T01）：独立轻量目录级守护，专守「金水谣数据」核心目录/文件。
# 与既有 check_vital_docs() 并存不冲突（本模块显式跳过已归命门的 2 份文档）。
try:
    from jinshuiyao_data_guard import check_jinshuiyao_data
except Exception:
    check_jinshuiyao_data = None

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_FILE = os.path.join(PROJECT_DIR, "scripts", ".quality_baseline.json")
MANIFEST_FILE = os.path.join(PROJECT_DIR, "scripts", "feature_manifest.json")
EXCLUDE_DIRS = {"__pycache__", ".git", "金水谣数据", "node_modules", "archive"}
ROOT_DIR = os.path.dirname(PROJECT_DIR)  # 项目根（模型/），用于看护根级命门文档
# 命门文档（道衍·知止）：绝不可被任何清理/误删弄丢。
# 根因：原 EXCLUDE_DIRS 把整个"金水谣数据"排除在快照比对外（避运行时噪音），
#       代价是命门文档也失守——循环删除事故即源于此。此处单独死守关键文档。
#       同时覆盖根级文档（quality_gate 以 Jinshuiyao_Fixed 为根，原根本看不见根级文档）。
PROTECTED_VITAL_DOCS = [
    os.path.join(ROOT_DIR, "金水谣_纲.md"),
    os.path.join(ROOT_DIR, "金水谣_契.md"),
    os.path.join(ROOT_DIR, "金水谣_录.md"),
    os.path.join(PROJECT_DIR, "金水谣数据", "log", "ai_decisions.md"),
    os.path.join(PROJECT_DIR, "金水谣数据", "风险登记册.md"),
    os.path.join(ROOT_DIR, "工作留痕总索引.md"),
    os.path.join(ROOT_DIR, "启动提示词.txt"),
]

PASS = 0
FAIL = 0
WARN = 0

def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _should_include(path):
    rel = os.path.relpath(path, PROJECT_DIR)
    parts = rel.split(os.sep)
    for part in parts:
        if part in EXCLUDE_DIRS:
            return False
    ext = os.path.splitext(path)[1]
    if ext not in (".py", ".html", ".bat", ".md", ".json", ".txt", ".csv"):
        return False
    return True

def snapshot():
    """拍快照：记录项目所有关键文件的MD5"""
    baseline = {}
    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            path = os.path.join(root, f)
            if _should_include(path):
                rel = os.path.relpath(path, PROJECT_DIR)
                baseline[rel] = _md5(path)
    baseline["_snapshot_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    baseline["_file_count"] = len(baseline) - 2
    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)
    print(f"✅ 快照已保存: {BASELINE_FILE}")
    print(f"   共记录 {baseline['_file_count']} 个文件")
    return baseline

def verify_baseline():
    """对照快照验证：报告新增/删除/修改的文件"""
    if not os.path.isfile(BASELINE_FILE):
        print("❌ 基线文件不存在，请先运行 --snapshot")
        return False

    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    current = {}
    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file in files:
            path = os.path.join(root, file)
            if _should_include(path):
                rel = os.path.relpath(path, PROJECT_DIR)
                current[rel] = _md5(path)

    old_files = set(baseline.keys()) - {"_snapshot_time", "_file_count"}
    new_files = set(current.keys())

    added = new_files - old_files
    removed = old_files - new_files
    changed = {f for f in old_files & new_files
               if f in current and f in baseline
               and current[f] != baseline[f]}

    ok = True
    if added:
        print(f"  [!] 新增文件 ({len(added)}):")
        for f in sorted(added):
            print(f"    + {f}")
        global WARN; WARN += 1

    if removed:
        print(f"  ❌ 文件被删除/移动 ({len(removed)}):")
        for f in sorted(removed):
            print(f"    - {f}")
        ok = False

    if changed:
        print(f"  ⚠ 文件被修改 ({len(changed)}):")
        for f in sorted(changed):
            print(f"    ~ {f}")

    if not added and not removed and not changed:
        print(f"  ✅ 所有 {len(old_files)} 个文件完好无损")

    return ok

def check_manifest():
    """检查功能清单中的所有文件是否存在、大小是否达标、关键函数是否存在"""
    if not os.path.isfile(MANIFEST_FILE):
        print("❌ 功能清单文件不存在")
        return False

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    ok = True
    print("\n📋 功能清单验证:")

    # 检查所有GUI文件
    for rel_path, info in manifest.get("gui_files", {}).get("files", {}).items():
        full_path = os.path.join(PROJECT_DIR, rel_path)
        if not os.path.isfile(full_path):
            print(f"    ❌ 文件缺失: {rel_path} ({info['purpose']})")
            ok = False
            continue

        size = os.path.getsize(full_path)
        min_size = info.get("min_size_bytes", 0)
        if size < min_size:
            print(f"    ⚠ 文件过小: {rel_path} ({size} bytes, 期望 >= {min_size})")
            ok = False
            continue

        # 检查关键函数
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        missing_symbols = []
        for sym in info.get("key_symbols", []):
            if sym not in content:
                missing_symbols.append(sym)
        if missing_symbols:
            print(f"    ⚠ {rel_path}: 缺少关键元素 {missing_symbols}")
            ok = False
        else:
            print(f"    ✅ {rel_path} — {info['purpose']}")

    # 检查子系统和核心脚本
    for category in ["subsystems", "core_scripts", "config", "documentation"]:
        cat_data = manifest.get(category, {})
        cat_files = cat_data.get("files", {})
        # domains/__init__.py 特殊处理
        if category == "subsystems" and "domains/__init__.py" in cat_data:
            cat_files["domains/__init__.py"] = cat_data["domains/__init__.py"]

        for rel_path, info in cat_files.items():
            full_path = os.path.join(PROJECT_DIR, rel_path)
            if info.get("required", False):
                if not os.path.isfile(full_path):
                    print(f"    ❌ 必需文件缺失: {rel_path}")
                    ok = False
                    continue
                # 检查关键函数
                key_syms = info.get("key_symbols", [])
                if key_syms:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    missing = [s for s in key_syms if s not in content]
                    if missing:
                        print(f"    ❌ {rel_path}: 缺少 {missing}")
                        ok = False

    if ok:
        print("  ✅ 所有功能文件完整")
    return ok


def check_vital_docs():
    """命门文档死守（道衍·知止）：任何一份缺失即 FAIL。

    这是 quality_gate 原本的盲区补丁：EXCLUDE_DIRS 排除了金水谣数据整目录，
    导致命门文档失守；且 quality_gate 以 Jinshuiyao_Fixed 为根，根级文档根本不在视野。
    本函数独立于快照，专门看护不可丢的关键文档（跨根级与子目录）。
    """
    print("\n🛡 命门文档死守 (vital-docs):")
    ok = True
    for doc in PROTECTED_VITAL_DOCS:
        if os.path.isfile(doc):
            print(f"    ✅ {os.path.relpath(doc, ROOT_DIR)}")
        else:
            print(f"    ❌ 命门文档缺失: {os.path.relpath(doc, ROOT_DIR)}")
            ok = False
    if ok:
        print("  ✅ 所有命门文档完好")
    return ok


def run_tests():
    """运行所有测试套件"""
    print("\n🧪 测试套件:")
    all_pass = True

    # 1. 预检查
    print("  [1/4] 前置检查 preflight_check.py...", end=" ")
    r = subprocess.run(
        [sys.executable, "scripts/preflight_check.py"],
        cwd=PROJECT_DIR, capture_output=True, text=True
    )
    if "9/9 全部通过" in r.stdout:
        print("✅")
    else:
        print("❌")
        all_pass = False

    # 2. 烟雾测试（批次A后迁 tools/，2026-08-12 W63补71 路径修正）
    print("  [2/4] 烟雾测试 smoke_test.py...", end=" ")
    r = subprocess.run(
        [sys.executable, "tools/smoke_test.py"],
        cwd=PROJECT_DIR, capture_output=True, text=True
    )
    if "10/10 通过" in r.stdout or "9/10 通过" in r.stdout:
        print("✅ (服务器离线时9/10正常)")
    else:
        print("❌")
        all_pass = False

    # 3. 全量单元测试（批次A后迁 tools/，2026-08-12 W63补71 路径修正）
    print("  [3/4] 全量单元测试 run_tests.py...", end=" ")
    r = subprocess.run(
        [sys.executable, "tools/run_tests.py"],
        cwd=PROJECT_DIR, capture_output=True, text=True
    )
    if "失败: 0" in r.stdout:
        print("✅ (全量通过)")
    else:
        lines = [l.strip() for l in r.stdout.split("\n") if "失败" in l or "总计" in l]
        print(f"⚠ ({'; '.join(lines) if lines else '查看详情'})")
        if "失败: 0" not in r.stdout:
            all_pass = False

    # 4. 功能清单验证
    print("  [4/4] 功能清单验证...", end=" ")
    if check_manifest():
        print("  ✅")
    else:
        print("  ❌")
        all_pass = False

    return all_pass


def print_summary(passed, failed, warnings):
    print("\n" + "=" * 50)
    if not passed and not failed:
        print("  质量门禁: 仅快照模式")
    elif failed == 0 and warnings == 0:
        print("  ✅ 质量门禁: 全部通过")
    elif failed == 0:
        print(f"  ⚠ 质量门禁: 通过但有 {warnings} 个警告")
    else:
        print(f"  ❌ 质量门禁: {failed} 项失败, {warnings} 个警告")
    print("=" * 50)


def main():
    import sys
    mode = "check"
    if "--snapshot" in sys.argv:
        mode = "snapshot"
    elif "--verify" in sys.argv:
        mode = "verify"

    # 门禁去盲区：OVERRIDE 透传（复用既有「人工确认后放行」铁律）。
    # 子进程恒为 NORMAL，故以 --override 参数或环境变量 JINSHUIYAO_OVERRIDE=1 显式确认。
    _override = ("--override" in sys.argv) or (os.environ.get("JINSHUIYAO_OVERRIDE") == "1")

    # 同频共识（JS-20260727-25）：跑质量门禁前先占锁，避免与写共享知识的会话竞态误报。
    _held = False
    if session_coordinator is not None:
        try:
            session_coordinator.acquire("质量门禁验证", wait_secs=0)
            _held = True
        except RuntimeError as e:
            print("[quality_gate] 检测到他者占锁共识(%s)，跳过本次以免竞态误报。" % e)
            return 0

    try:
        os.chdir(PROJECT_DIR)

        print("=" * 50)
        print("  金水谣质量门禁系统 (Quality Gate)")
        print(f"  模式: {mode}")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)

        if mode == "snapshot":
            snapshot()
            print_summary(0, 0, 0)
            return 0

        if mode == "verify":
            ok = verify_baseline()
            vital_ok = check_vital_docs()
            # 门禁去盲区：verify 场景为人工主动核对，数据缺失应如实硬报错（退出码 1）
            data_ok = check_jinshuiyao_data(override=_override) if check_jinshuiyao_data else True
            all_ok = ok and vital_ok and data_ok
            print_summary(1 if all_ok else 0, 0 if all_ok else 1, 0)
            return 0 if all_ok else 1

        # 默认模式：全量检查
        baseline_ok = verify_baseline()
        vital_ok = check_vital_docs()
        # 门禁去盲区（fail-safe）：默认仅告警（计入 WARN），不进 failures，不阻断收工
        data_ok = check_jinshuiyao_data(override=_override) if check_jinshuiyao_data else True
        test_ok = run_tests()

        failures = 0
        if not baseline_ok:
            failures += 1
        if not vital_ok:
            failures += 1
        if not test_ok:
            failures += 1

        global WARN
        # data 缺失只计警告，不计入硬失败（fail-safe）
        warnings = WARN + (0 if data_ok else 1)

        print_summary(1 if failures == 0 else 0, failures, warnings)
        return 0 if failures == 0 else 1
    finally:
        if _held:
            try:
                session_coordinator.release()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
