# -*- coding: utf-8 -*-
"""风险登记册 md 生成器（T02，纯标准库）

双轨同源：risk_register.json 为单一真源，本脚本将其渲染为
`金水谣数据/风险登记册.md`。禁止手工双写——改 json 后重跑本脚本即可。

用法：
    python scripts/gen_risk_md.py [--path 自定义json] [--out 自定义md]

退出码：0=成功；2=json 缺失/非法。
"""
import os
import sys
import json
import argparse

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
_DEFAULT_JSON = os.path.join(_PROJECT_ROOT, "金水谣数据", "risk_register.json")
_DEFAULT_MD = os.path.join(_PROJECT_ROOT, "金水谣数据", "风险登记册.md")

# 概览表表头
_OVERVIEW_HEADERS = [
    ("id", "ID"),
    ("probability", "概率"),
    ("impact_level", "影响度"),
    ("mitigation_status", "降级状态"),
    ("owner", "责任方"),
    ("last_review", "最后review"),
]

# 详情区字段展示顺序（键 -> 中文标签）
_DETAIL_FIELDS = [
    ("description", "描述"),
    ("impact", "影响"),
    ("probability", "概率"),
    ("impact_level", "影响度"),
    ("mitigation", "降级方案"),
    ("mitigation_status", "降级状态"),
    ("owner", "责任方"),
    ("early_signal", "预警信号"),
    ("last_review", "最后review"),
]


def _default_json_path():
    return _DEFAULT_JSON


def _render(json_path, md_path):
    """读取 json，渲染 md，写盘。返回 (ok, msg)。"""
    if not os.path.isfile(json_path):
        return False, "风险登记册 json 缺失: " + json_path
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, "风险登记册 json 解析失败: %s" % e

    if not isinstance(data, dict) or not isinstance(data.get("risks"), list):
        return False, "风险登记册 json 结构非法（缺 risks 数组）"

    risks = data.get("risks", [])
    policy = data.get("review_policy", {}) or {}
    stale_days = policy.get("stale_days", 90)

    lines = []
    lines.append("# 金水谣风险登记册（Risk Register）")
    lines.append("")
    lines.append("> ⚠️ **本文件由 `金水谣数据/risk_register.json` 自动生成，请勿手工修改；"
                 "改动请编辑 json 后重跑 `scripts/gen_risk_md.py`。**")
    lines.append("")
    lines.append("- 单一真源：`金水谣数据/risk_register.json`")
    lines.append("- 复查节奏：%s（stale_days=%s；last_review 超期标红）" % (
        policy.get("cadence", "monthly"), stale_days))
    lines.append("- 体检挂载：`%s`" % policy.get("lint_hook", "knowledge/用户知识库/lint_knowledge.py"))
    lines.append("- 条目数：%d" % len(risks))
    lines.append("")

    # 概览表
    lines.append("## 概览")
    lines.append("")
    header_keys = [h[1] for h in _OVERVIEW_HEADERS]
    lines.append("| " + " | ".join(header_keys) + " |")
    lines.append("|" + "|".join(["---"] * len(header_keys)) + "|")
    for r in risks:
        row = []
        for key, _label in _OVERVIEW_HEADERS:
            row.append(str(r.get(key, "")))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # 每条详情
    lines.append("## 条目详情")
    lines.append("")
    for r in risks:
        rid = r.get("id", "?")
        title = r.get("description", "")
        lines.append("### %s %s" % (rid, title))
        lines.append("")
        for key, label in _DETAIL_FIELDS:
            val = r.get(key, "")
            lines.append("- **%s**：%s" % (label, val))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("> 本文档由 `scripts/gen_risk_md.py` 生成（自动生成勿手工改）。"
                 "任何修改请回到 `risk_register.json` 单一真源。")
    lines.append("")

    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        return False, "写入 md 失败: %s" % e

    return True, "已生成: %s（%d 条）" % (md_path, len(risks))


def main():
    ap = argparse.ArgumentParser(description="风险登记册 md 生成器（json→md 同源渲染）")
    ap.add_argument("--path", default=_DEFAULT_JSON, help="risk_register.json 路径")
    ap.add_argument("--out", default=_DEFAULT_MD, help="输出的 md 路径")
    args = ap.parse_args()

    ok, msg = _render(args.path, args.out)
    print(msg)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
