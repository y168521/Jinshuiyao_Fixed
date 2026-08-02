#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动蒸馏器 auto_distill.py — 经验收集箱 → SKILL.md 全自动升级管线（AI 增强版）
================================================================================
检测经验收集箱的新条目，自动提炼进对应 Skill：

  1. 启发式快速归类（零成本，命中关键词直接搬规则）
  2. AI 语义蒸馏（未归类/归类存疑的条目，调用 DeepSeek 理解+归类+提炼规则）
  3. AI 不可用/失败 → 退回待蒸馏队列（供 AI 会话处理）

幂等：基于条目标题 sha256 标记，重复运行不重复追加。
运行：py -3.14 tools/auto_distill.py            # 纯启发式（离线安全）
      py -3.14 tools/auto_distill.py --ai       # 启发式 + AI 语义蒸馏
      py -3.14 tools/auto_distill.py --flush-queue   # 把待蒸馏队列当素材再跑一轮 AI

输出：
  - 更新 .opencode/skills/<skill>/SKILL.md 的「自动蒸馏区」
  - 追加 金水谣数据/log/distill.log
  - 无法处理 → 追加到 金水谣数据/log/待蒸馏队列.md
"""

import argparse
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

SKILL_NAMES = {
    "jinshuiyao-encoding": "Windows 脚本编码与中文路径铁律",
    "jinshuiyao-sync": "自动同步与多机协作规范",
    "jinshuiyao-docs": "文档登记与交接规范（铁律0）",
    "jinshuiyao-dev": "开发协作与代码维护规范",
}

# 关键词 → Skill 映射（标题/正文命中即归类，优先级从高到低）
SKILL_KEYWORDS = [
    ("jinshuiyao-encoding", ["编码", "BOM", "GBK", "乱码", "bat", "ps1", "中文路径", "chcp", "剪贴板"]),
    ("jinshuiyao-sync", ["同步", "vault", "计划任务", "黑名单", "多机", "GitHub", "push", "pull", "坚果云", "冲突"]),
    ("jinshuiyao-docs", ["登记", "留痕", "交接", "编号", "铁律", "文档", "经验沉淀", "收工"]),
    ("jinshuiyao-dev", ["代码审查", "合并", "重构", "Edit", "测试", "Lint", "防乱", "启动器", "快照", "备份", "覆盖率"]),
]

SECTION_MARKER = "## 📥 自动蒸馏区（auto_distill 维护，勿手改）"
MAX_DISTILL_ENTRIES = 12  # 蒸馏区容量上限：超出后最旧条目压缩为归档行（原文永远在经验收集箱）


def sha256_hex(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _compact_distill_section(text):
    """蒸馏区瘦身：真实条目超过 MAX_DISTILL_ENTRIES 时，把最旧的压缩为归档行。

    条目只保留"标题+要点+原文指针"，细节原文在经验收集箱（L1），
    Skill 只承载索引，避免无限膨胀成累赘。

    归档行（📜 开头）不参与计数、不被拆解——只记录被淘汰条目标题，
    内容永远以经验收集箱为准，防止链式压缩丢标题。
    """
    if SECTION_MARKER not in text:
        return text
    marker_pos = text.index(SECTION_MARKER)
    head = text[:marker_pos]
    rest = text[marker_pos + len(SECTION_MARKER):]

    # 行级解析：条目 = "- **标题**" 行 + 后续缩进行；归档行（📜）单独识别
    blocks, cur_title, cur = [], None, []
    archive_titles = []
    for ln in rest.split("\n"):
        m = re.match(r"- \*\*(.+?)\*\*", ln)
        if m:
            if cur_title is not None:
                blocks.append((cur_title, "\n".join(cur)))
            cur, cur_title = [ln], m.group(1).strip()
            if cur_title.startswith("📜"):
                inner = re.search(r"——\s*(.+?)\s*——", ln)
                if inner:
                    for t in inner.group(1).split("；"):
                        t = t.strip()
                        if t and not t.startswith("📜"):
                            archive_titles.append(t)
                cur_title = None  # 归档行不参与计数
        elif cur_title is not None:
            cur.append(ln)
    if cur_title is not None:
        blocks.append((cur_title, "\n".join(cur)))

    real = [b for b in blocks if not b[0].startswith("📜")]
    if len(real) <= MAX_DISTILL_ENTRIES:
        return text

    keep = real[:MAX_DISTILL_ENTRIES]
    merged = []
    for t in [b[0] for b in real[MAX_DISTILL_ENTRIES:]] + archive_titles:
        if t not in merged:
            merged.append(t)
    body = "\n".join(b[1] for b in keep)
    archive_line = (
        "- **📜 历史蒸馏归档（" + str(len(merged)) + " 条）** —— " + "；".join(merged)
        + " —— 完整内容见 金水谣数据/log/经验收集箱.md（L1 原始层，永不删除）"
    )
    return head + SECTION_MARKER + "\n" + body + "\n" + archive_line + "\n"


def load_seen():
    if not os.path.exists(STATE):
        return set()
    with open(STATE, encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_seen(seen):
    with open(STATE, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(seen)) + "\n")


def parse_entries(text):
    """解析经验收集箱为 [{'title','body'}]"""
    entries = []
    for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        title, body = m.group(1).strip(), m.group(2).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", title):
            entries.append({"title": title, "body": body})
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
    if title in text:
        return False  # 已存在，跳过（幂等）
    # 索引式条目：1 行要点 + 原文指针（细节在经验收集箱 L1，Skill 不复制全文防膨胀）
    first_point = points[0] if points else "见原文要点"
    entry_lines = ["- **" + title + "** — " + first_point[:120]]
    for p in points[1:4]:
        entry_lines.append("  - " + p[:200])
    # 原文指针：经验收集箱文件 + 条目标题（锚点定位）
    title_anchor = title.split("：", 1)[0] if "：" in title else title
    entry_lines.append("  - 原文: 金水谣数据/log/经验收集箱.md#" + title_anchor + "（L1 原始层）")
    entry_lines.append("  - 关联: " + rel_js)
    entry_block = "\n".join(entry_lines)
    if SECTION_MARKER in text:
        pos = text.index(SECTION_MARKER)
        # 在 marker 后插入，保持区顺序
        insert_at = pos + len(SECTION_MARKER)
        text = text[:insert_at] + "\n" + entry_block + text[insert_at:]
    else:
        text = text.rstrip() + "\n\n" + SECTION_MARKER + "\n\n" + entry_block + "\n"
    text = _compact_distill_section(text)
    with open(skill_file, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def _ai_classify_and_extract(title, body):
    """调用 DeepSeek：语义归类 + 提炼规则。失败返回 None。"""
    try:
        sys.path.insert(0, BASE_DIR)
        from core.ai_service import AIService
        ai = AIService()
        if not ai.is_available:
            return None
        skill_list = "、".join(SKILL_NAMES.keys())
        sys_prompt = (
            "你是金水谣项目的经验蒸馏员。用户给一条经验记录，你要：\n"
            "1. 判断它属于哪个 Skill 领域，只输出 Skill 名（可选值: " + skill_list + "），如都不匹配输出 None；\n"
            "2. 提炼 2-4 条可执行的规则/教训，每条一句话，编号列出；\n"
            "输出格式：第一行=Skill名（或None），第二行起=每条规则一行，不要其他内容。"
        )
        user_prompt = "经验标题: " + title + "\n\n经验内容:\n" + body[:1500]
        resp = ai.chat(system_prompt=sys_prompt, user_prompt=user_prompt)
        if not resp:
            return None
        text = resp.strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return None
        # 宽松解析：第一行是 Skill 名；否则全文中找 Skill 名
        skill = lines[0]
        if skill not in SKILL_NAMES:
            found = next((ln for ln in lines if ln in SKILL_NAMES), None)
            if found:
                skill = found
            else:
                return None
        rules = [ln.lstrip("- ").strip() for ln in lines if ln.strip() and ln not in SKILL_NAMES and not ln == skill][:4]
        if not rules:
            return None
        return skill, rules
    except Exception:
        return None


def _queue_key(qtitle):
    """队列条目幂等键：标题 sha256（与经验条目一致）。"""
    return sha256_hex("QUEUE:" + qtitle)


def _load_queue_entries():
    """读取待蒸馏队列为 [{title, body}]，空文件返回 []。"""
    if not os.path.exists(QUEUE):
        return []
    with open(QUEUE, encoding="utf-8") as f:
        qtext = f.read()
    entries = []
    for m in re.finditer(r"^### (.+?)\n(.*?)(?=^### |\Z)", qtext, re.M | re.S):
        title, body = m.group(1).strip(), m.group(2).strip()
        if not title:
            continue
        entries.append({"title": title, "body": body[:600]})
    return entries


def _prune_queue(done_keys):
    """从队列文件移除已成功处理的条目（保留其余），返回是否变动。"""
    if not done_keys or not os.path.exists(QUEUE):
        return False
    with open(QUEUE, encoding="utf-8") as f:
        qtext = f.read()
    if not qtext.strip():
        return False
    lines = qtext.split("\n")
    out, skip, changed = [], False, False
    for ln in lines:
        m = re.match(r"^### (.+?)$", ln)
        if m:
            skip = _queue_key(m.group(1).strip()) in done_keys
            if skip:
                changed = True
        if not skip:
            out.append(ln)
    if changed:
        with open(QUEUE, "w", encoding="utf-8") as f:
            f.write("\n".join(out).rstrip() + "\n")
    return changed


def distill_entry(e, use_ai):
    """处理单条经验，返回 (skill, points) 或 None。"""
    points = extract_rules(e["body"])
    skill = classify(e["title"], e["body"])
    if skill and points:
        return skill, points
    if use_ai and (not skill or not points):
        result = _ai_classify_and_extract(e["title"], e["body"])
        if result:
            return result
    return None


def main():
    parser = argparse.ArgumentParser(description="金水谣自动蒸馏器")
    parser.add_argument("--ai", action="store_true", help="启用 AI 语义蒸馏（调用 DeepSeek）")
    parser.add_argument("--flush-queue", action="store_true", help="把待蒸馏队列条目重新处理一遍")
    args = parser.parse_args()

    if args.flush_queue:
        entries = _load_queue_entries()
        if not entries:
            print("[distill] 队列为空，跳过")
            return
        print(f"[distill] 队列重处理: {len(entries)} 条")
    else:
        if not os.path.exists(EXPBOX):
            print("[distill] 经验收集箱不存在，跳过")
            return
        with open(EXPBOX, encoding="utf-8") as f:
            text = f.read()
        entries = parse_entries(text)

    seen = load_seen()
    new_count, skill_updated, ai_used = 0, [], 0
    queue_entries, done_keys = [], []
    for e in entries:
        if args.flush_queue:
            key = _queue_key(e["title"])
            if key in seen:
                continue  # 队列条目已成功处理过，幂等防重复
        else:
            key = sha256_hex(e["title"])
            if key in seen:
                continue
            seen.add(key)
        new_count += 1
        result = distill_entry(e, args.ai)
        if result:
            skill, points = result
            if args.ai:
                ai_used += 1
            rel = "JS-未知"
            m = re.search(r"关联总索引\*\*：(.+)", e["body"])
            if m:
                rel = m.group(1).strip()
            appended = append_to_skill(skill, e["title"], points, rel)
            if appended:
                skill_updated.append(skill)
            else:
                new_count -= 1  # 已存在，不算新
            seen.add(key)  # 成功提炼（无论是否新写）即标记，防重复
            if args.flush_queue:
                done_keys.append(key)  # 提炼成功即从队列移除（内容已入 Skill 或已存在）
        else:
            if args.flush_queue:
                continue  # 失败保留队列，不标记 seen，下轮可重试
            queue_entries.append("### " + e["title"] + "\n\n- 归类: 待处理\n- 关联: 见下\n\n```\n" + e["body"][:600] + "\n```\n")
    save_seen(seen)
    if args.flush_queue:
        _prune_queue(done_keys)

    with open(DISTILL_LOG, "a", encoding="utf-8") as f:
        ts = re.sub(r"\D", "", str(__import__("datetime").datetime.now().isoformat()))[:14]
        f.write(f"{ts} 处理={new_count} AI蒸馏={ai_used} 更新Skill={skill_updated or '无'} 待队列={len(queue_entries)}\n")

    if queue_entries:
        with open(QUEUE, "a", encoding="utf-8") as f:
            f.write("\n## 自动蒸馏待处理 " + __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M") + "\n\n")
            for q in queue_entries:
                f.write(q + "\n")

    print(f"[distill] 处理={new_count} AI蒸馏={ai_used} 更新Skill={skill_updated or '无'} 待队列={len(queue_entries)}")


if __name__ == "__main__":
    main()
