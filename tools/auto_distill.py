#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动蒸馏器 auto_distill.py — 经验收集箱 → SKILL.md 全自动升级管线
================================================================
检测经验收集箱的新条目，按关键词自动归类到对应 Skill，并把条目的
"规则/教训"提炼成要点追加进 SKILL.md 的「自动蒸馏区」。

幂等：基于条目标题 sha256 标记，重复运行不重复追加。
运行：py -3.14 tools/auto_distill.py   （计划任务"Jinshuiyao自动同步"顺带调用）

输出：
  - 更新 .opencode/skills/<skill>/SKILL.md 的「自动蒸馏区」
  - 追加 金水谣数据/log/distill.log
  - 新条目若无法归类 → 写 金水谣数据/log/待蒸馏队列.md（供 AI 会话处理）
"""

import hashlib
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPBOX = os.path.join(BASE_DIR, "金水谣数据", "log", "经验收集箱.md")
STATE = os.path.join(BASE_DIR, "金水谣数据", "log", ".distill_seen")
DISTILL_LOG = os.path.join(BASE_DIR, "金水谣数据", "log", "distill.log")
QUEUE = os.path.join(BASE_DIR, "金水谣数据", "log", "待蒸馏队列.md")
SKILLS_DIR = os.path.join(BASE_DIR, ".opencode", "skills")

# 关键词 → Skill 映射（标题/正文命中即归类，优先级从高到低）
SKILL_KEYWORDS = [
    ("jinshuiyao-encoding", ["编码", "BOM", "GBK", "乱码", "bat", "ps1", "中文路径", "chcp", "剪贴板"]),
    ("jinshuiyao-sync", ["同步", "vault", "计划任务", "黑名单", "多机", "GitHub", "push", "pull", "坚果云", "冲突"]),
    ("jinshuiyao-docs", ["登记", "留痕", "交接", "编号", "铁律", "文档", "经验沉淀", "收工"]),
]

SECTION_MARKER = "## 📥 自动蒸馏区（auto_distill 维护，勿手改）"


def sha256_hex(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def load_seen():
    if not os.path.exists(STATE):
        return set()
    with open(STATE, encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_seen(seen):
    with open(STATE, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(seen)) + "\n")


def parse_entries(text):
    """解析经验收集箱为 [{'title','body','block'}]"""
    entries = []
    for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        title, body = m.group(1).strip(), m.group(2).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", title):
            entries.append({"title": title, "body": body, "block": m.group(0)})
    return entries


def extract_rules(body):
    """抽取 规则/教训/方案 段落为要点列表"""
    points = []
    for field in ["规则", "教训", "方案", "处理"]:
        m = re.search(r"^- \*\*" + field + r"\*\*：(.+)$", body, re.M)
        if m:
            points.append(m.group(1).strip())
    return points


def classify(title, body):
    text = title + "\n" + body
    for skill, kws in SKILL_KEYWORDS:
        for kw in kws:
            if kw.lower() in text.lower():
                return skill
    return None


def append_to_skill(skill, title, points, rel_js):
    skill_dir = os.path.join(SKILLS_DIR, skill)
    if not os.path.isdir(skill_dir):
        return False
    skill_file = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_file):
        return False
    with open(skill_file, encoding="utf-8") as f:
        text = f.read()
    entry_lines = ["- **" + title + "**"]
    for p in points:
        entry_lines.append("  - " + p)
    entry_lines.append("  - 关联: " + rel_js)
    entry_block = "\n".join(entry_lines)
    if SECTION_MARKER in text:
        # 追加到区末尾（去重：标题已在则跳过）
        if title in text:
            return False
        pos = text.index(SECTION_MARKER)
        sec_end = len(text)
        text = text[:sec_end].rstrip() + "\n" + entry_block + "\n"
    else:
        text = text.rstrip() + "\n\n" + SECTION_MARKER + "\n\n" + entry_block + "\n"
    with open(skill_file, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def main():
    if not os.path.exists(EXPBOX):
        print("[distill] 经验收集箱不存在，跳过")
        return
    with open(EXPBOX, encoding="utf-8") as f:
        text = f.read()
    seen = load_seen()
    entries = parse_entries(text)
    new_count, skill_updated = 0, []
    queue_entries = []
    for e in entries:
        key = sha256_hex(e["title"])
        if key in seen:
            continue
        seen.add(key)
        new_count += 1
        points = extract_rules(e["body"])
        skill = classify(e["title"], e["body"])
        rel = "JS-未知"
        m = re.search(r"关联总索引\*\*：(.+)", e["body"])
        if m:
            rel = m.group(1).strip()
        if skill and points:
            if append_to_skill(skill, e["title"], points, rel):
                skill_updated.append(skill)
        else:
            queue_entries.append("### " + e["title"] + "\n\n- 归类: " + str(skill) + "\n- 关联: " + rel + "\n\n```\n" + e["body"][:600] + "\n```\n")
    save_seen(seen)
    with open(DISTILL_LOG, "a", encoding="utf-8") as f:
        ts = re.sub(r"\D", "", str(__import__("datetime").datetime.now().isoformat()))[:14]
        f.write(f"{ts} 新条目={new_count} 已更新Skill={skill_updated or '无'} 待队列={len(queue_entries)}\n")
    if queue_entries:
        with open(QUEUE, "a", encoding="utf-8") as f:
            f.write("## 自动蒸馏待处理 " + __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M") + "\n\n")
            for q in queue_entries:
                f.write(q + "\n")
    print(f"[distill] 新条目={new_count} 更新Skill={skill_updated or '无'} 待队列={len(queue_entries)}")


if __name__ == "__main__":
    main()
