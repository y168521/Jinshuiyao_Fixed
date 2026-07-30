#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣 · 流程合规督察
=================
检查谁在偷懒、谁跳过了流程。

用法:
  py -3.14 tools/compliance.py          # 今日报告
  py -3.14 tools/compliance.py --date 2026-07-29  # 指定日期
  py -3.14 tools/compliance.py --out    # 输出到交接中心
"""

import os
import sys
import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
MODEL_DIR = os.path.dirname(ROOT_DIR)

sys.path.insert(0, ROOT_DIR)
from tools.audit_trail import compliance_report, write_replay, log_event


def _append_report_to_jiaojie(report, date_str):
    """把合规报告追加到交接中心"""
    path = os.path.join(MODEL_DIR, "AI协作交接中心.md")
    if not os.path.isfile(path):
        print("[compliance] 交接中心不存在，跳过追加")
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    marker = "## 合规督察"
    section = f"\n\n{marker}\n\n{report}\n"
    if marker in content:
        # 替换已有
        idx = content.index(marker)
        end = content.find("\n## ", idx + 1)
        if end == -1:
            end = len(content)
        content = content[:idx] + section + content[end:]
    else:
        content += section
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[compliance] 报告已追加到 AI协作交接中心.md")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="金水谣流程合规督察")
    parser.add_argument("--date", help="指定日期 (YYYY-MM-DD), 默认今天")
    parser.add_argument("--out", action="store_true", help="输出到 AI协作交接中心.md")
    args = extra = parser.parse_known_args()[0]

    date_str = args.date or datetime.date.today().isoformat()
    report = compliance_report(date_str)
    print(report)

    if args.out:
        _append_report_to_jiaojie(report, date_str)

    log_event("compliance", detail=f"生成合规报告 {date_str}")


if __name__ == "__main__":
    main()
