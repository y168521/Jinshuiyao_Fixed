# -*- coding: utf-8 -*-
"""【道衍推导·JS-20260727-35】
  阴阳：阳=AI 主动扫色识别(显性能力)；阴=守底(只改确属禁用的饱和色，不误伤中性灰)。
  天地人：天=替代词典可配(下方 FORBIDDEN_MAP)；地=正则提取+语义映射，结构不动；
          人=复盘(scan/fix 返回结构化变更，可审计)。
  知止：默认只自动改写"明确禁用饱和色"，其余 off-theme 色仅报告不擅改(除非用户要求全量重做)。

金水谣 · AI 配色子系统（让智能体像人一样识别并帮配色）
  - scan_colors(text) : 提取所有颜色，对照参考主题标违规
  - fix_colors(text)  : 把禁用饱和色按替代词典改写（复刻"刚对话"的纠错）
  - suggest_theme(prompt): 自然语言→主题变量（七色/浅色中性/深色中性/带色调）
  - explain_scan(...)  : 生成大白话摘要，让人秒懂
"""
import re
import json
import os

from core.theme_manager import (
    _load_cfg, get_theme_vars, theme_to_css_vars, list_themes,
)

# 禁用饱和色 → (替换色, 语义说明) ；覆盖项目实际遇到的 GitHub 暗色系/业务误用色
FORBIDDEN_MAP = {
    "#ef4444": ("#C8755A", "正红→赤铜色(负向/报错)"),
    "#22c55e": ("#2D8B7E", "正绿→墨绿金(正向/成功)"),
    "#eab308": ("#C9A96E", "正黄→香槟金(警告)"),
    "#8b5cf6": ("#162840", "紫色→深海墨蓝(建议渐变香槟金)"),
    "#f97316": ("#C8755A", "橙色→赤铜色(浅)"),
    "#ff6b6b": ("#C8755A", "红→赤铜色"),
    "#51cf66": ("#2D8B7E", "绿→墨绿金"),
    "#ffd43b": ("#C9A96E", "黄→香槟金"),
    "#ffa94d": ("#C8755A", "橙→赤铜色"),
    "#74c0fc": ("#5BC0DE", "亮蓝→冰水蓝"),
    "#1f9d57": ("#2D8B7E", "绿→墨绿金"),
    "#60a5fa": ("#5BC0DE", "蓝→冰水蓝"),
    "#2f6df0": ("#5BC0DE", "蓝→冰水蓝"),
    "#ffb347": ("#C9A96E", "橙黄→香槟金"),
    "#ff8f00": ("#C8755A", "橙→赤铜色"),
    "#22aa5a": ("#2D8B7E", "绿→墨绿金"),
    "#34aa5a": ("#2D8B7E", "绿→墨绿金"),
    "#06b6d4": ("#5BC0DE", "青→冰水蓝"),
    "#10b981": ("#2D8B7E", "绿→墨绿金"),
    "#ec4899": ("#C8755A", "粉→赤铜色"),
    "#0f1419": ("#0B1A2F", "GitHub暗底→深海墨蓝"),
    "#1a2230": ("#162840", "GitHub卡片→深蓝灰"),
    "#141b26": ("#162840", "GitHub次级→深蓝灰"),
    "#2a3441": ("#162840", "GitHub描边→深蓝灰"),
    "#9aa7b4": ("#E8ECF1", "GitHub灰字→暖银白"),
    "#9be7c4": ("#2D8B7E", "GitHub绿字→墨绿金"),
    "#0b0f14": ("#0B1A2F", "GitHub代码底→深海墨蓝"),
    "#13251c": ("#162840", "GitHub绿块底→深蓝灰"),
    "#16301f": ("#162840", "GitHub绿块底→深蓝灰"),
}

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_RGB_RE = re.compile(r"rgba?\(\s*[\d.,%\s]+\s*\)", re.IGNORECASE)


def _norm_hex(h):
    h = h.lstrip("#").lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 8:  # 含 alpha，比较时忽略透明度
        h = h[:6]
    return "#" + h


def scan_colors(text, reference_theme="owner-default"):
    """扫描文本中的颜色，对照参考主题分类。

    返回 dict: {colors:[{raw, normalized, kind}], violations:[...], off_theme:[...], summary}
      kind: 'forbidden' | 'in_theme' | 'neutral' | 'rgb' | 'other'
    """
    theme_vars = get_theme_vars(reference_theme) or {}
    theme_values = set(v.lower() if isinstance(v, str) else "" for v in theme_vars.values())
    theme_values.discard("")

    colors = []
    violations = []
    off_theme = []

    for m in _HEX_RE.finditer(text):
        raw = m.group(0)
        norm = _norm_hex(raw)
        if norm in FORBIDDEN_MAP:
            kind = "forbidden"
            repl, why = FORBIDDEN_MAP[norm]
            violations.append({"raw": raw, "normalized": norm, "replace": repl, "reason": why})
        elif norm in theme_values:
            kind = "in_theme"
        elif _is_neutral(norm):
            kind = "neutral"
        else:
            kind = "off_theme"
            off_theme.append({"raw": raw, "normalized": norm})
        colors.append({"raw": raw, "normalized": norm, "kind": kind})

    for m in _RGB_RE.finditer(text):
        raw = m.group(0)
        colors.append({"raw": raw, "normalized": raw, "kind": "rgb"})
        off_theme.append({"raw": raw, "normalized": raw, "note": "需人工核对是否饱和色"})

    summary = "发现 {} 个颜色：禁用色 {} 处，离题色 {} 处，符合主题 {} 处".format(
        len(colors), len(violations), len(off_theme),
        sum(1 for c in colors if c["kind"] == "in_theme"),
    )
    return {
        "colors": colors,
        "violations": violations,
        "off_theme": off_theme,
        "summary": summary,
        "reference_theme": reference_theme,
    }


def _is_neutral(hex6):
    """判断是否是中性灰（r/g/b 彼此接近）"""
    hex6 = hex6.lstrip("#")
    try:
        r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
    except Exception:
        return False
    return max(r, g, b) - min(r, g, b) <= 24


def fix_colors(text, reference_theme="owner-default"):
    """把文本中的禁用饱和色按替代词典改写。返回 (new_text, changes)。

    注意：默认只改 FORBIDDEN_MAP 命中的明确禁用色；off_theme/中性色不动（守底，不误伤）。
    """
    changes = []

    def repl_hex(m):
        raw = m.group(0)
        norm = _norm_hex(raw)
        if norm in FORBIDDEN_MAP:
            repl, why = FORBIDDEN_MAP[norm]
            changes.append({"from": raw, "to": repl, "reason": why})
            return repl
        return raw

    new_text = _HEX_RE.sub(repl_hex, text)
    return new_text, changes


def suggest_theme(prompt):
    """自然语言→主题变量 dict。关键词驱动，确定性、可测。

    支持：七色/金水谣→owner-default；浅色/亮色/白→system-light；
          深色/暗色→system-dark；蓝/红/暖/金 等可加色调前缀（以 system 为底微调强调色）。
    返回 dict: {name, label, vars}
    """
    p = (prompt or "").lower()
    base = "owner-default"
    if any(k in p for k in ["七色", "金水谣", "个人默认", "香槟金", "我的配色"]):
        base = "owner-default"
    elif any(k in p for k in ["浅色", "亮色", "白底", "浅色中性", "light"]):
        base = "system-light"
    elif any(k in p for k in ["深色", "暗色", "深色中性", "dark"]):
        base = "system-dark"
    else:
        # 未点名具体主题时，默认系统深色中性（最像主流模型）
        base = "system-dark"

    vars_dict = dict(get_theme_vars(base) or {})
    label = "建议主题(基于 {})".format(base)

    # 简单色调微调（在 system 底上改强调色）
    if "蓝" in p and base.startswith("system"):
        vars_dict["--gold"] = "#5BC0DE"
        vars_dict["--ice"] = "#5BC0DE"
        label = "蓝调·系统中性"
    elif ("红" in p or "暖" in p) and base.startswith("system"):
        vars_dict["--gold"] = "#C8755A"
        label = "暖红调·系统中性"
    elif "绿" in p and base.startswith("system"):
        vars_dict["--gold"] = "#2D8B7E"
        label = "绿调·系统中性"

    return {"name": base, "label": label, "vars": vars_dict}


def explain_scan(scan_result):
    """把 scan 结果转成大白话摘要（像人跟你说的一样）。"""
    lines = [scan_result["summary"], ""]
    if scan_result["violations"]:
        lines.append("🚫 禁用色（须改）：")
        for v in scan_result["violations"]:
            lines.append("  · {} → {}（{}）".format(v["raw"], v["replace"], v["reason"]))
    if scan_result["off_theme"]:
        lines.append("⚠️ 离题色（非七色、非中性，建议确认）：")
        for o in scan_result["off_theme"][:12]:
            note = o.get("note", "")
            lines.append("  · {} {}".format(o["raw"], ("（" + note + "）") if note else ""))
    if not scan_result["violations"] and not scan_result["off_theme"]:
        lines.append("✅ 配色合规，未引入禁用色。")
    return "\n".join(lines)


if __name__ == "__main__":
    sample = '''
    .badge{background:#1f9d57;color:#fff}
    .warn{background:#ffb347}
    .link{color:#60a5fa}
    .card{background:#162840}
    .txt{color:#E8ECF1}
    .rgbtest{color:rgba(255,0,0,0.5)}
    '''
    s = scan_colors(sample)
    print("== SCAN ==")
    print(explain_scan(s))
    fixed, changes = fix_colors(sample)
    print("\n== FIX ({} 处) ==".format(len(changes)))
    for c in changes:
        print("  {} → {}".format(c["from"], c["to"]))
    print("\n== SUGGEST '帮我配一套浅色中性' ==")
    sug = suggest_theme("帮我配一套浅色中性")
    print(sug["label"], "→", sug["vars"]["--deep"], sug["vars"]["--ink"])
