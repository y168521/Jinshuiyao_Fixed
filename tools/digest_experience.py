#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣 · 经验提取器 (digest_experience.py)
=========================================
从当前轮工作记录中提取经验，追加到经验收集箱.md。
旨在解决"聊天记录中的经验仅留在日志里，未归入知识库"的问题。

用法（交互模式）：
  py -3.14 tools/digest_experience.py
  py -3.14 tools/digest_experience.py --js JS-20260729-05

用法（批量/非交互）：
  先创建临时 JSON 文件，再：
  py -3.14 tools/digest_experience.py --input digest_data.json

JSON 格式：
  {
    "js_id": "JS-20260729-05",
    "entries": [
      {
        "tag": "架构",
        "title": "简短标题",
        "what": "做了什么",
        "pitfall": "踩过的坑",
        "next_time": "下次注意",
        "method": "有效方法",
        "maturity": "draft"
      }
    ]
  }
"""
import os, sys, json, argparse
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
LOG_DIR = os.path.join(ROOT, "金水谣数据", "log")
EXP_PATH = os.path.join(LOG_DIR, "经验收集箱.md")
MODEL = os.path.dirname(ROOT)

TAGS = {
    "1": ("架构", "架构类"),
    "2": ("后端", "后端类"),
    "3": ("前端", "前端类"),
    "4": ("测试", "测试类"),
    "5": ("运维", "运维类"),
    "6": ("安全", "安全类"),
    "7": ("最佳实践", "最佳实践类"),
    "8": ("踩坑", "踩坑类"),
    "9": ("协作", "协作类"),
    "10": ("数据完整性", "数据完整性类"),
}

TEMPLATE = """
### {date}（{ai}）{title} · {js_id} [{tags}]
**标签：** {tag_hashes}
**做了什么：** {what}
**踩过的坑：** {pitfall}
**下次注意：** {next_time}
**有效方法：** {method}
**知识成熟度：** {maturity}
**关联总索引：** {js_id}
"""

def _get_last_js_id():
    """从 总索引 获取最近一条 JS 编号"""
    idx_path = os.path.join(MODEL, "工作留痕总索引.md")
    if not os.path.isfile(idx_path):
        return None
    with open(idx_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    import re
    all_js = []
    for m in re.finditer(r'(JS-\d{8}-\d{2})', text):
        all_js.append(m.group(1))
    return all_js[-1] if all_js else None

def _prompt_interactive():
    print(f"\n{'='*60}")
    print("  金水谣 · 经验提取器 (交互模式)")
    print(f"{'='*60}\n")
    print("请逐项输入本条经验的内容（直接回车跳过可选字段）:\n")

    js_id = input(f"  JS 编号 (默认: {_get_last_js_id() or '?'}): ").strip()
    if not js_id:
        js_id = _get_last_js_id() or "JS-????"
    title = input("  标题: ").strip()
    if not title:
        title = "经验提取"
    ai = input("  AI 模型 (默认: opencode): ").strip() or "opencode"

    print("\n  标签选择:")
    for num, (tag, desc) in TAGS.items():
        print(f"    [{num}] {tag} - {desc}")
    tag_input = input("  标签编号 (逗号分隔, 默认 7): ").strip() or "7"
    selected_tags = []
    for t in tag_input.split(","):
        t = t.strip()
        if t in TAGS:
            selected_tags.append(TAGS[t][0])
    if not selected_tags:
        selected_tags = ["最佳实践"]
    tags_comma = "/".join(selected_tags)

    print()
    what = input("  做了什么: ").strip()
    pitfall = input("  踩过的坑: ").strip()
    next_time = input("  下次注意: ").strip()
    method = input("  有效方法: ").strip()

    print("\n  成熟度:")
    print("    [d] draft - 未验证")
    print("    [v] verified - 已验证")
    maturity_input = input("  选择 (默认 d): ").strip().lower()
    maturity = {"v": "verified", "d": "draft"}.get(maturity_input, "draft")

    entry = {
        "js_id": js_id,
        "title": title,
        "ai": ai,
        "date": str(date.today()),
        "tags": tags_comma,
        "tag_hashes": " ".join(f"#{t}" for t in selected_tags),
        "what": what or "（待补充）",
        "pitfall": pitfall or "（待补充）",
        "next_time": next_time or "（待补充）",
        "method": method or "（待补充）",
        "maturity": maturity,
    }
    return entry

def _append_to_experience(entry):
    text = TEMPLATE.format(**entry)
    with open(EXP_PATH, "a", encoding="utf-8") as f:
        f.write(text)
    print(f"\n[digest] 已追加到: {EXP_PATH}")
    print(text)

def _batch_from_json(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    js_id = data.get("js_id", "JS-????")
    count = 0
    for entry_data in data.get("entries", []):
        entry = {
            "js_id": js_id,
            "title": entry_data.get("title", "经验提取"),
            "ai": entry_data.get("ai", "-"),
            "date": entry_data.get("date", str(date.today())),
            "tags": "/".join(entry_data.get("tags", ["最佳实践"])),
            "tag_hashes": " ".join(f"#{t}" for t in entry_data.get("tags", ["最佳实践"])),
            "what": entry_data.get("what", "（待补充）"),
            "pitfall": entry_data.get("pitfall", "（待补充）"),
            "next_time": entry_data.get("next_time", "（待补充）"),
            "method": entry_data.get("method", "（待补充）"),
            "maturity": entry_data.get("maturity", "draft"),
        }
        _append_to_experience(entry)
        count += 1
    print(f"[digest] 批量完成：{count} 条")

def main():
    parser = argparse.ArgumentParser(description="金水谣经验提取器")
    parser.add_argument("--js", help="JS 编号（指定时自动使用最近编号）")
    parser.add_argument("--input", help="JSON 文件路径（批量非交互模式）")
    args = parser.parse_args()

    if not os.path.isfile(EXP_PATH):
        print(f"[digest] 错误: 经验收集箱不存在 ({EXP_PATH})")
        return 1

    if args.input:
        _batch_from_json(args.input)
    else:
        entry = _prompt_interactive()
        _append_to_experience(entry)
    return 0

if __name__ == "__main__":
    sys.exit(main())
