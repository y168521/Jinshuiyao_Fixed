# -*- coding: utf-8 -*-
"""【道衍推导·JS-20260727-35】
  阴阳：阳=客户主权(自选颜色优先)；阴=owner 个人默认(七色)兜底守底。
  天地人：天=主题分层可配(config/themes.json)；地=变量名统一、切换只覆盖值(不碰结构)；
          人=复盘(用户主题落盘 user_themes.json，可追溯)。
  知止：所有页面颜色只经 CSS 变量引用，绝不在组件里写死；主题切换只换变量值。

金水谣 · 主题分层管理（生产上线配色框架）
  - 三层主题：L0 系统默认(中性) / L1 客户自选 / L2 owner 个人默认(七色)
  - 回退序：客户自选 → 系统默认 → owner 个人默认
  - 实现：所有页面经 CSS 变量引用颜色；切换主题 = 覆盖同名变量值(结构不动)
"""
import json
import os
import re
from utils.safe_json import safe_write_json, safe_load_json
import threading

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "themes.json")
_USER_THEMES_PATH = os.path.join(_PROJECT_ROOT, "金水谣数据", "user_themes.json")

_lock = threading.RLock()
_cfg_cache = None
_cfg_mtime = 0

# 变量名 → 人类可读含义（用于生成说明/审计）
_VAR_MEANING = {
    "--deep": "主背景",
    "--card-bg": "卡片/次级背景",
    "--ink": "主文字",
    "--gold": "强调/标题/按钮",
    "--ice": "数据高亮/链接/交互",
    "--jade": "正向/盈利/成功/在线",
    "--copper": "负向/亏损/报错/风险",
    "--status-online": "状态·正常",
    "--status-offline": "状态·离线",
    "--status-warning": "状态·警告",
    "--status-error": "状态·错误",
    "--status-pending": "状态·待处理",
    "--chart-1": "图表系列1",
    "--chart-2": "图表系列2",
    "--chart-3": "图表系列3",
    "--chart-4": "图表系列4",
    "--chart-5": "图表系列5",
}


def _load_cfg():
    global _cfg_cache, _cfg_mtime
    try:
        mtime = os.path.getmtime(_CONFIG_PATH)
    except Exception:
        mtime = 0
    if _cfg_cache is not None and mtime == _cfg_mtime:
        return _cfg_cache
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
    except Exception:
        c = {"variable_order": list(_VAR_MEANING.keys()),
             "default_theme": "owner-default",
             "fallback_order": ["customer", "system-dark", "owner-default"],
             "themes": {}}
    _cfg_cache = c
    _cfg_mtime = mtime
    return c


def list_themes():
    """返回内置主题清单 [{name,label,kind}]"""
    cfg = _load_cfg()
    out = []
    for name, t in cfg.get("themes", {}).items():
        out.append({"name": name, "label": t.get("label", name), "kind": t.get("kind", "unknown")})
    return out


def get_theme_vars(name):
    """取内置主题变量 dict；不存在返回 None"""
    cfg = _load_cfg()
    t = cfg.get("themes", {}).get(name)
    if not t:
        return None
    return dict(t.get("vars", {}))


def theme_to_css_vars(vars_dict, var_order=None):
    """把变量 dict 渲染成 :root{...} CSS 文本（含 theme-vars 块便于直接注入）"""
    cfg = _load_cfg()
    order = var_order or cfg.get("variable_order") or list(_VAR_MEANING.keys())
    lines = []
    for k in order:
        if k in vars_dict:
            lines.append("  {}: {};".format(k, vars_dict[k]))
    body = "\n".join(lines)
    return ":root {\n" + body + "\n}"


def _load_user_themes():
    # 刀⑥(JS-20260807-02): safe_load_json 原子读+损坏恢复，避免裸 open+json.load 半读/崩
    data = safe_load_json(_USER_THEMES_PATH, default={})
    return data if isinstance(data, dict) else {}


def _save_user_themes(data):
    # 刀⑥: safe_write_json 原子写+备份，含 makedirs，避免半写撕裂
    safe_write_json(_USER_THEMES_PATH, data, backup=True)


def get_user_theme(user_id):
    """取某用户的自选主题变量 dict；无则返回 None（走回退）"""
    if not user_id:
        return None
    data = _load_user_themes()
    return data.get(str(user_id))


def save_user_theme(user_id, vars_dict):
    """持久化某用户的自选主题变量；返回是否成功"""
    if not user_id or not isinstance(vars_dict, dict):
        return False
    with _lock:
        data = _load_user_themes()
        data[str(user_id)] = vars_dict
        _save_user_themes(data)
    return True


def clear_user_theme(user_id):
    """清除某用户自选主题（回到系统默认/个人默认回退）；返回是否成功"""
    if not user_id:
        return False
    with _lock:
        data = _load_user_themes()
        if str(user_id) in data:
            del data[str(user_id)]
            _save_user_themes(data)
    return True


def resolve_theme(user_id=None, system_theme=None):
    """解析最终生效的主题变量（回退：客户自选 → 系统默认 → owner 个人默认）。

    返回 dict：{vars, source} —— source 标记来自哪一层。
    """
    cfg = _load_cfg()
    if user_id == "owner":
        # owner 个人默认=七色，优先于系统中性默认
        fallback = ["customer", "owner-default", "system-light"]
    else:
        # 普通/匿名用户：客户自选 → 系统浅色中性(像主流模型默认) → 个人七色兜底
        fallback = cfg.get("fallback_order", ["customer", "system-light", "owner-default"])

    customer_vars = get_user_theme(user_id) if user_id else None
    if customer_vars:
        return {"vars": customer_vars, "source": "customer"}

    # 在 fallback 中找第一个可用的系统/owner 主题
    for layer in fallback:
        if layer == "customer":
            continue
        if layer == "owner-default" or layer == "system-dark" or layer == "system-light":
            if system_theme:
                v = get_theme_vars(system_theme)
                if v:
                    return {"vars": v, "source": system_theme}
            v = get_theme_vars(layer)
            if v:
                return {"vars": v, "source": layer}
    # 极端兜底
    v = get_theme_vars(cfg.get("default_theme", "owner-default"))
    return {"vars": v or {}, "source": cfg.get("default_theme", "owner-default")}


def apply_to_html(html, vars_dict, var_order=None):
    """把主题变量注入/替换进 HTML 的 <style id="theme-vars"> 块。

    已存在则替换；不存在则插入（优先 </head> 后，其次 <html> 后，再否则头部）。
    返回新 HTML 字符串。
    """
    css = theme_to_css_vars(vars_dict, var_order)
    block = '<style id="theme-vars">\n' + css + "\n</style>"
    pat = re.compile(r'<style id="theme-vars">.*?</style>', re.DOTALL | re.IGNORECASE)
    if pat.search(html):
        return pat.sub(lambda m: block, html)
    if "</head>" in html:
        return html.replace("</head>", block + "\n</head>", 1)
    m = re.search(r"<html[^>]*>", html, re.IGNORECASE)
    if m:
        return html[:m.end()] + "\n" + block + html[m.end():]
    return block + "\n" + html


def extract_existing_theme_vars(html):
    """从 HTML 的 <style id="theme-vars"> 块中提取已声明的变量 dict（用于编辑回显）"""
    pat = re.compile(r'<style id="theme-vars">\s*:root\s*\{(.*?)\}</style>', re.DOTALL | re.IGNORECASE)
    m = pat.search(html)
    if not m:
        return {}
    body = m.group(1)
    out = {}
    for line in body.splitlines():
        line = line.strip()
        if line.endswith(";"):
            line = line[:-1]
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


if __name__ == "__main__":
    # 隔离自测
    print("内置主题:", [t["name"] for t in list_themes()])
    r = resolve_theme(user_id=None, system_theme="system-light")
    print("无用户回退→", r["source"])
    r2 = resolve_theme(user_id="u1")
    print("有用户→", r2["source"], "(应 customer 或回退)")
    sample = "<html><head><title>t</title></head><body>x</body></html>"
    out = apply_to_html(sample, r["vars"])
    print("注入成功:", 'id="theme-vars"' in out)
    print(theme_to_css_vars(r["vars"])[:80], "...")
