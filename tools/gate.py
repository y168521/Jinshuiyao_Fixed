#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣 · 统一门禁入口（gate.py）
=================================
合并 wrapup_check / smoke_test(组件+e2e) / ast_checker / closeout_gate /
quality_gate / review / test / audit(跨文档一致性) 为单一入口。用法：
  py -3.14 tools/gate.py --check          # 收工自检（原 wrapup_check）
  py -3.14 tools/gate.py --smoke          # 冒烟测试·组件（原 tools/smoke_test）
  py -3.14 tools/gate.py --e2e            # 冒烟测试·端到端（原 scripts/smoke_test）
  py -3.14 tools/gate.py --ast            # AST 扫描（原 ast_checker）
  py -3.14 tools/gate.py --closeout       # DoD 门禁（原 closeout_gate）
  py -3.14 tools/gate.py --quality        # 质量基线（原 quality_gate）
  py -3.14 tools/gate.py --review         # AI 审查（原 run_review）
  py -3.14 tools/gate.py --test           # 全量测试（原 run_tests）
  py -3.14 tools/gate.py --all            # 全跑一遍
各子命令透传额外参数（如 --quick, --skip-tests 等）。
旧入口脚本保留作为兼容别名，但新调用请统一走 gate.py。
"""
from __future__ import annotations
import sys, os, subprocess

# GBK 安全输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)  # Jinshuiyao_Fixed/
SCRIPTS = os.path.join(ROOT, "scripts")

SCRIPT_MAP = {
    "check":     (os.path.join(BASE, "wrapup_check.py"),     "收工自检"),
    "smoke":     (os.path.join(BASE, "smoke_test.py"),       "冒烟测试(15项)"),
    "e2e":       (os.path.join(BASE, "smoke_test.py"),       "冒烟测试·端到端(15项)"),
    "ast":       (os.path.join(BASE, "ast_checker.py"),      "AST 扫描"),
    "closeout":  (os.path.join(BASE, "closeout_gate.py"), "DoD 门禁"),
    "quality":   (os.path.join(SCRIPTS, "quality_gate.py"),  "质量基线"),
    "review":    (os.path.join(BASE, "run_review.py"),       "AI 审查"),
    "test":      (os.path.join(BASE, "run_tests.py"),        "全量测试(pytest)"),
    "audit":     (os.path.join(BASE, "cross_doc_audit.py"),  "跨文档一致性审计"),
}

def run_script(script_path, label, extra_args):
    cmd = [sys.executable, script_path] + extra_args
    print(f"[gate] {'='*50}")
    print(f"[gate] 执行: {label}")
    print(f"[gate] 命令: {' '.join(cmd)}")
    print(f"[gate] {'='*50}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[gate] FAIL {label} 失败 (exit={result.returncode})")
    else:
        print(f"[gate] OK {label} 通过")
    return result.returncode

def run_tests(extra_args):
    """--test: 直接跑 pytest（真源轨道），不再走 run_tests.py 空跑"""
    cmd = [sys.executable, "-m", "pytest", os.path.join(ROOT, "tests"), "-q"] + extra_args
    print(f"[gate] {'='*50}")
    print(f"[gate] 执行: 全量测试(pytest) — 真断言轨道")
    print(f"[gate] 命令: {' '.join(cmd)}")
    print(f"[gate] {'='*50}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[gate] FAIL 全量测试失败 (exit={result.returncode})")
    else:
        print(f"[gate] OK 全量测试通过")
    return result.returncode

def main():
    import argparse
    parser = argparse.ArgumentParser(description="金水谣统一门禁入口")
    parser.add_argument("--check", action="store_true", help="收工自检（原 wrapup_check）")
    parser.add_argument("--smoke", action="store_true", help="冒烟测试·组件(15项,原 tools/smoke_test)")
    parser.add_argument("--e2e", action="store_true", help="冒烟测试·端到端(12项,原 scripts/smoke_test)")
    parser.add_argument("--ast", action="store_true", help="AST 扫描（原 ast_checker）")
    parser.add_argument("--closeout", action="store_true", help="DoD 门禁（原 closeout_gate）")
    parser.add_argument("--quality", action="store_true", help="质量基线（原 quality_gate）")
    parser.add_argument("--review", action="store_true", help="AI 审查（原 run_review）")
    parser.add_argument("--test", action="store_true", help="全量测试（原 run_tests）")
    parser.add_argument("--audit", action="store_true", help="跨文档一致性审计（cross_doc_audit）")
    parser.add_argument("--all", action="store_true", help="全跑一遍")
    args, extra = parser.parse_known_args()

    selected = []
    if args.all:
        selected = list(SCRIPT_MAP.keys())
    else:
        for key in SCRIPT_MAP:
            if getattr(args, key, False):
                selected.append(key)

    if not selected:
        parser.print_help()
        print("\n[gate] 未指定子命令。例如: py -3.14 tools/gate.py --check")
        return 1

    exit_codes = []
    for key in selected:
        if key == "test":
            code = run_tests(extra)
        else:
            script_path, label = SCRIPT_MAP[key]
            code = run_script(script_path, label, extra)
        exit_codes.append(code)

    max_code = max(exit_codes) if exit_codes else 0
    if max_code == 0:
        print(f"\n[gate] OK 全部 {len(selected)} 项通过")
    else:
        n_fail = sum(1 for c in exit_codes if c != 0)
        print(f"\n[gate] WARN 有 {n_fail} 项失败，最高退出码={max_code}")
    return max_code

if __name__ == "__main__":
    sys.exit(main())
