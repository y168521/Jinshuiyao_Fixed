# -*- coding: utf-8 -*-
"""金水谣本地助手 · 项目记忆查询器

让 agent 能直接读取本项目的决策卡、总索引、风险登记册，回答：
  - "最近定了什么？"
  - "JS-20260727-20 做了什么？"
  - "现在最大的风险是什么？"
"""
import os
import re
from datetime import datetime
from typing import List, Dict, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(*parts):
    return os.path.join(_PROJECT_ROOT, *parts)


def _read_text(*parts, max_chars: int = 20000) -> str:
    p = _path(*parts)
    if not os.path.isfile(p):
        return ""
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read(max_chars)
    except Exception as e:
        return f"[读取失败: {e}]"


def _extract_cards(md: str, limit: int = 5) -> List[Dict[str, str]]:
    """从 ai_decisions.md 提取最近的决策卡。"""
    cards = []
    # 每张卡以 ### 开头
    parts = re.split(r"\n(?=### )", md)
    for part in reversed(parts):
        if not part.strip().startswith("###"):
            continue
        title_match = re.match(r"###\s*(.+?)\s*\n", part)
        title = title_match.group(1).strip() if title_match else "未知卡片"
        # 取前 500 字符作为摘要
        summary = part.strip().replace("\n", " ")[:500]
        cards.append({"title": title, "summary": summary, "raw": part.strip()})
        if len(cards) >= limit:
            break
    return cards


def query_recent_decisions(limit: int = 5) -> str:
    md = _read_text("金水谣数据", "log", "ai_decisions.md", max_chars=500000)
    if not md:
        return "【项目记忆】暂无论决策卡记录。"
    cards = _extract_cards(md, limit)
    if not cards:
        return "【项目记忆】未找到决策卡。"
    lines = [f"【最近 {len(cards)} 张决策卡】"]
    for i, c in enumerate(cards, 1):
        lines.append(f"\n{i}. {c['title']}")
        lines.append(f"   {c['summary']}...")
    return "\n".join(lines)


def query_decision_by_js(js_id: str) -> str:
    md = _read_text("金水谣数据", "log", "ai_decisions.md", max_chars=500000)
    if not md:
        return f"【项目记忆】找不到 {js_id} 相关记录。"
    # 按卡拆分，避免跨卡匹配
    parts = re.split(r"\n(?=### )", md)
    for part in parts:
        if part.strip().startswith("###") and js_id in part:
            return f"【{js_id} 决策卡详情】\n\n{part.strip()}"
    return f"【项目记忆】未在决策卡中找到 {js_id}。"


def query_total_index(keyword: str = "", limit: int = 5) -> str:
    md = _read_text("..", "工作留痕总索引.md")
    if not md:
        return "【项目记忆】总索引文件不存在。"
    if not keyword:
        # 返回最近几条（按 ### 标题）
        parts = re.split(r"\n(?=### )", md)
        recent = [p for p in parts if p.strip().startswith("###")][-limit:]
        lines = [f"【总索引最近 {len(recent)} 条】"]
        for p in recent:
            title = re.match(r"###\s*(.+?)\s*\n", p)
            lines.append(f"\n{title.group(1).strip() if title else '未知'}")
            lines.append("   " + p.replace("\n", " ")[:300] + "...")
        return "\n".join(lines)
    # 按关键词搜索
    matches = []
    parts = re.split(r"\n(?=### )", md)
    kw_lower = keyword.lower()
    for p in parts:
        if kw_lower in p.lower():
            title = re.match(r"###\s*(.+?)\s*\n", p)
            matches.append((title.group(1).strip() if title else "未知", p.replace("\n", " ")[:300]))
    if not matches:
        return f"【总索引】未找到与「{keyword}」相关的条目。"
    lines = [f"【总索引搜索「{keyword}」】共 {len(matches)} 条"]
    for title, snippet in matches[:limit]:
        lines.append(f"\n• {title}\n   {snippet}...")
    return "\n".join(lines)


def _parse_risk_rows(md: str) -> list:
    """从风险登记册 Markdown 表格解析风险行。"""
    rows = []
    for line in md.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # 过滤空单元格
        cells = [c for c in cells if c]
        if len(cells) >= 6 and re.match(r"R\d+", cells[0]):
            rows.append({
                "id": cells[0],
                "name": cells[1],
                "impact": cells[2],
                "trigger": cells[3],
                "mitigation": cells[4],
                "owner": cells[5],
                "status": cells[6] if len(cells) > 6 else "",
            })
    return rows


def query_risk_register(keyword: str = "") -> str:
    md = _read_text("金水谣数据", "风险登记册.md")
    if not md:
        return "【项目记忆】风险登记册不存在。"
    rows = _parse_risk_rows(md)
    if not rows:
        return "【风险登记册】未解析到风险条目。"
    if not keyword:
        lines = [f"【风险登记册】共 {len(rows)} 条"]
        for r in rows:
            lines.append(f"\n• {r['id']} {r['name']} [{r['status']}]")
            lines.append(f"   影响：{r['impact'][:80]}...")
            lines.append(f"   缓解：{r['mitigation'][:80]}...")
        return "\n".join(lines)
    kw_lower = keyword.lower()
    matches = [r for r in rows if any(kw_lower in str(v).lower() for v in r.values())]
    if not matches:
        return f"【风险登记册】未找到与「{keyword}」相关的风险。"
    lines = [f"【风险登记册搜索「{keyword}」】共 {len(matches)} 条"]
    for r in matches:
        lines.append(f"\n• {r['id']} {r['name']} [{r['status']}]")
        lines.append(f"   影响：{r['impact']}")
        lines.append(f"   缓解：{r['mitigation']}")
    return "\n".join(lines)


def query_project_memory(user_input: str) -> str:
    """根据用户问题统一调度项目记忆查询。"""
    text = user_input.lower()

    # JS 编号查询
    js_match = re.search(r"js[-\s]?(\d{8}[-\s]?\d+)", text, re.I)
    if js_match:
        js_id = f"JS-{js_match.group(1)}"
        return query_decision_by_js(js_id)

    # 风险相关
    if any(k in text for k in ["风险", "雷", "隐患", "登记册"]):
        kw = ""
        if "免费模型" in user_input or "积分" in user_input:
            kw = "免费模型"
        elif "并发" in user_input or "覆盖" in user_input:
            kw = "并发"
        return query_risk_register(kw)

    # 最近决策 / 做了什么
    if any(k in text for k in ["最近", "最近定了", "做了什么", "决策卡", "决定"]):
        return query_recent_decisions(5)

    # 总索引搜索
    if "总索引" in text or "留痕" in text:
        return query_total_index("", 5)

    # 默认：同时给最近决策 + 风险 Top
    return (
        query_recent_decisions(3) + "\n\n" +
        query_risk_register("")[:800] + "\n\n" +
        "（你可以更具体地问，比如「JS-20260727-20 做了什么」或「免费模型有什么风险」）"
    )
