#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
金水谣收工自检（Fitness Function / 质量门禁）— 薄入口
实际检查逻辑已拆分至 tools/wrapup/ 包（P1-5 god object 拆分）。
用法不变：py -3.14 tools/wrapup_check.py [--skip-tests] [--date YYYY-MM-DD] ...
"""

import sys, os, re, subprocess, shutil
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows GBK 终端安全输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from tools.wrapup import *  # noqa: F403,F401
from tools.wrapup.base import _results, BASE_DIR, MODEL_DIR, FAIL_ICON  # 显式导入

def main():
    import argparse
    parser = argparse.ArgumentParser(description="金水谣收工自检（质量门禁）")
    parser.add_argument("--skip-tests", action="store_true", help="跳过pytest检查")
    parser.add_argument("--date", default=None, help="指定检查日期(YYYY-MM-DD)，默认今天")
    parser.add_argument("--update-baseline", action="store_true",
                        help="刷新文件地图基线（换机同步后或确认无误后用）")
    parser.add_argument("--update-hash", action="store_true",
                        help="刷新脚本哈希基线（合法升级 wrapup_check.py 后用）")
    parser.add_argument("--update-file-hash", action="store_true",
                        help="刷新文件哈希基线（合法修改文件后用，替代 git add）")
    parser.add_argument("--mode", default="NORMAL",
                        choices=["NORMAL", "DEGRADED", "OFFLINE", "OVERRIDE"],
                        help="门禁模式：NORMAL 严格阻断 / OVERRIDE 紧急豁免(仅警告) / "
                             "DEGRADED|OFFLINE 仅影响 AI 决策同步降级")
    args = parser.parse_args()

    # 哈希刷新模式：只刷新基线，不跑检查
    if args.update_hash:
        print("=" * 60)
        print("  金水谣收工自检 · 刷新脚本哈希基线")
        print("=" * 60)
        ok = update_script_hash()
        return 0 if ok else 1

    if args.update_file_hash:
        print("=" * 60)
        print("  金水谣收工自检 · 刷新文件哈希基线（替代 git add）")
        print("=" * 60)
        ok = update_file_hash_baseline()
        return 0 if ok else 1

    today_str = args.date or date.today().strftime("%Y-%m-%d")

    print("=" * 60)
    print("  金水谣收工自检 · Fitness Function 质量门禁 v1.7")
    print(f"  检查日期: {today_str}")
    print("=" * 60)
    print()

    # 第一道防线：脚本完整性校验（必须在所有检查之前）
    check_script_integrity()

    check_handoff(today_str)
    check_experience(today_str)
    check_trace_index(today_str)
    check_trace_field_completeness(today_str)
    check_experience_field_completeness(today_str)
    check_scheduler_sync()
    check_file_map(update_baseline=args.update_baseline)
    check_page_routes()
    check_source_code_verification(today_str)
    check_change_volume(today_str)
    check_config_consistency()
    check_css_var_override()
    check_mindmap_ids(today_str)
    check_tag_index_consistency()
    check_rejected_solutions_quality(today_str)
    check_history_field_sampling()
    check_reference_integrity(today_str)
    check_variable_naming_convention()
    check_experience_tag_count()
    check_trace_coverage(today_str)
    check_ai_decision_coverage(today_str, mode=args.mode)
    check_change_linkage(today_str, mode=args.mode)
    check_file_integrity()
    check_secrets_leak()
    check_html_security()
    check_knowledge_reuse()
    check_time_anomaly(today_str)
    check_gui_variable_scope()
    check_wukaisan(today_str)
    check_experience_quality()
    check_skip_frequency(today_str=today_str)
    check_tests(skip=args.skip_tests, today_str=today_str)

    # 汇总
    print()
    print("-" * 60)
    total = len(_results)
    passed = sum(1 for _, p, _ in _results if p)
    failed = total - passed

    if failed == 0:
        print(f"  结果: {passed}/{total} 项通过 —— 全绿，可以收工！")
        # 全绿后自动刷新文件哈希基线（自检通过=改动已留痕=可纳入新基线）
        # 这样下次自检只检测"本次基线之后"的新改动，不会重复检测已留痕的改动
        _save_file_hash_baseline(_scan_py_files_hashmap(BASE_DIR))
        print("-" * 60)
        return 0
    else:
        print(f"  结果: {passed}/{total} 项通过，{failed} 项红灯 —— 禁止收工！")
        print()
        print("  红灯项（必须修复后重跑）:")
        for name, p, detail in _results:
            if not p:
                print(f"    {FAIL_ICON} {name}: {detail}")
        print()
        print("  提示: 修完红灯项后重新运行本脚本，全绿才能说「完成」。")
        print("-" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
