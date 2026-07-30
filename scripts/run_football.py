#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金水谣足彩预测系统 - 独立启动器（含完整诊断）

用法：
    python run_football.py
"""

import sys
import os
import subprocess
import traceback

# ============================================================
# 诊断第一阶段：环境检查
# ============================================================
print("=" * 60)
print("[DIAG] [诊断] 金水谣足彩启动诊断")
print("=" * 60)

project_root = os.path.dirname(os.path.abspath(__file__))
print(f"  Python 版本: {sys.version}")
print(f"  Python 路径: {sys.executable}")
print(f"  项目根目录: {project_root}")
print(f"  当前工作目录: {os.getcwd()}")
print(f"  脚本自身: {__file__}")

# 检查 jinshuiyao 目录
jinshuiyao_dir = os.path.join(project_root, "jinshuiyao")
jinshuiyao_exists = os.path.isdir(jinshuiyao_dir)
print(f"  jinshuiyao/ 目录: {'[OK] 存在' if jinshuiyao_exists else '[FAIL] 不存在'} ({jinshuiyao_dir})")

if not jinshuiyao_exists:
    print("\n[FAIL] 错误: 未找到 jinshuiyao/ 目录，请确保该目录存在于项目根目录下")
    input("按回车退出...")
    sys.exit(1)

# 检查关键文件
critical_files = [
    "football_gui.py",
    "calibrator.py",
    "decision_engine.py",
    "config.py",
    "fetcher.py",
    "odds_utils.py",
    "models/__init__.py",
    "models/poisson_model.py",
]
for fname in critical_files:
    fpath = os.path.join(jinshuiyao_dir, fname)
    ok = os.path.exists(fpath)
    print(f"  {fname}: {'[OK]' if ok else '[FAIL] 缺失'}")

# ============================================================
# 诊断第二阶段：导入测试
# ============================================================
print()
print("[DIAG] [诊断] 模块导入测试")

# 确保项目根目录在 sys.path
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import_test_errors = []

# 测试包模式导入
modules_to_test = [
    "jinshuiyao.config",
    "jinshuiyao.schemas",
    "jinshuiyao.logger",
    "jinshuiyao.odds_utils",
    "jinshuiyao.calibrator",
    "jinshuiyao.feature_engine",
    "jinshuiyao.data_provider",
    "jinshuiyao.decision_engine",
    "jinshuiyao.risk_controller",
    "jinshuiyao.fetcher",
    "jinshuiyao.models.poisson_model",
    # v3.0 新增模块
    "jinshuiyao.radar",
    "jinshuiyao.scene_factors",
    "jinshuiyao.score_path",
    "jinshuiyao.stability",
    "jinshuiyao.team_db",
    "jinshuiyao.audit",
    "jinshuiyao.multi_play",
    "jinshuiyao.combo_optimizer",
    "jinshuiyao.match_validator",
]
for mod_name in modules_to_test:
    try:
        __import__(mod_name)
        print(f"  {mod_name}: [OK]")
    except Exception as e:
        print(f"  {mod_name}: [FAIL] {e}")
        import_test_errors.append((mod_name, str(e)))

# 测试关键类导入
key_classes = [
    ("jinshuiyao.football_gui", "FootballApp"),
    ("jinshuiyao.odds_utils", "OddsUtils"),
    ("jinshuiyao.decision_engine", "JinshuiyaoDecisionEngine"),
    # v3.0 新增
    ("jinshuiyao.radar", "TeamRadar"),
    ("jinshuiyao.radar", "TeamRatingEngine"),
    ("jinshuiyao.scene_factors", "SceneFactors"),
    ("jinshuiyao.score_path", "generate_score_paths"),
    ("jinshuiyao.score_path", "compute_expected_goals"),
    ("jinshuiyao.stability", "TeamStabilityTracker"),
    ("jinshuiyao.team_db", "TeamDatabase"),
    ("jinshuiyao.audit", "AuditSystem"),
    ("jinshuiyao.multi_play", "MultiPlayEngine"),
    ("jinshuiyao.combo_optimizer", "ComboOptimizer"),
    ("jinshuiyao.match_validator", "filter_matches_lenient"),
]
for mod_name, cls_name in key_classes:
    try:
        mod = __import__(mod_name, fromlist=[cls_name])
        getattr(mod, cls_name)
        print(f"  {mod_name}.{cls_name}: [OK]")
    except Exception as e:
        print(f"  {mod_name}.{cls_name}: [FAIL] {e}")
        import_test_errors.append((f"{mod_name}.{cls_name}", str(e)))

# 检查 tkinter
try:
    import tkinter
    print(f"  tkinter: [OK]")
except ImportError as e:
    print(f"  tkinter: [FAIL] {e}")
    import_test_errors.append(("tkinter", str(e)))

# 检查依赖
for lib in ["pandas", "scipy"]:
    try:
        __import__(lib)
        print(f"  {lib}: [OK]")
    except ImportError as e:
        print(f"  {lib}: [WARN] 未安装 (部分功能会使用默认值)")

print()
if import_test_errors:
    print("=" * 60)
    print("[FAIL] [诊断] 导入失败，无法启动足彩系统:")
    for name, err in import_test_errors:
        print(f"  - {name}: {err}")
    print("=" * 60)
    # 输出完整 traceback 用于排查
    print()
    print("[DIAG] [诊断] 详细错误追踪:")
    for mod_name, _ in import_test_errors:
        try:
            __import__(mod_name.split(".")[0] if "." in mod_name else mod_name, fromlist=[mod_name.rsplit(".", 1)[-1]])
        except Exception:
            traceback.print_exc()
    input("\n按回车退出...")
    sys.exit(1)

print("[OK] 所有导入测试通过")

# ============================================================
# 诊断第三阶段：启动 GUI
# ============================================================
print()
print("[DIAG] [诊断] 启动 GUI 子进程...")
print(f"  命令: {sys.executable} -m jinshuiyao.football_gui")
print(f"  工作目录: {project_root}")

try:
    result = subprocess.run(
        [sys.executable, "jinshuiyao/football_gui.py"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30  # 30秒超时，防止窗口挂起
    )
    print(f"  子进程退出码: {result.returncode}")
    if result.stdout:
        print("  --- stdout ---")
        for line in result.stdout.strip().split("\n")[-20:]:
            print(f"    {line}")
    if result.stderr:
        print("  --- stderr ---")
        for line in result.stderr.strip().split("\n")[-20:]:
            print(f"    {line}")
    if result.returncode != 0:
        print(f"\n[FAIL] 子进程异常退出 (exit code: {result.returncode})")
        if "TclError" in result.stderr or "display" in result.stderr.lower():
            print("  原因分析: 系统缺少图形环境 (DISPLAY)，这在服务器环境是正常的")
            print("  在有桌面环境的 Windows 上运行不会出现此错误")
except subprocess.TimeoutExpired as e:
    print("  [WARN] 子进程超时 (可能 GUI 窗口正常运行中，但此诊断脚本无法检测)")
    # 显示捕获的输出，帮助诊断
    if e.stdout:
        print("  --- 子进程 stdout (最后30行) ---")
        stdout_lines = e.stdout.strip().split("\n") if e.stdout else []
        for line in stdout_lines[-30:]:
            print(f"    {line}")
    if e.stderr:
        print("  --- 子进程 stderr (最后30行) ---")
        stderr_lines = e.stderr.strip().split("\n") if e.stderr else []
        for line in stderr_lines[-30:]:
            print(f"    {line}")
except FileNotFoundError:
    print(f"  [FAIL] 找不到 Python 解释器: {sys.executable}")
except Exception as e:
    print(f"  [FAIL] 启动异常: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("诊断完成。如果窗口未弹出，请将以上诊断输出截图反馈。")
print("=" * 60)

# 仅在直接运行时才暂停
if sys.stdin and sys.stdin.isatty():
    input("\n按回车退出...")