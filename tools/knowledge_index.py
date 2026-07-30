#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣 · 知识索引生成器 (knowledge_index.py v2)
===========================================
自动从以下数据源构建「文件→关联知识」反向索引：
  - 工作留痕总索引.md   — JS记录（表格式 + ###-pipe + ###-dot）
  - ai_decisions.md     — AI决策卡（57卡, ~104文件路径）
  - 经验收集箱.md        — 经验条目（~1805行）
  - pattern_library.json  — 15个失败模式
  - risk_register.json    — 10条风险登记

输出：knowledge/file_knowledge_index.json
用法：py -3.14 tools/knowledge_index.py [--force]
"""
import os, sys, re, json
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
MODEL = os.path.dirname(ROOT)
KNOWLEDGE_DIR = os.path.join(ROOT, "knowledge")
INDEX_PATH = os.path.join(KNOWLEDGE_DIR, "file_knowledge_index.json")
INDEX_PATH_LEGACY = os.path.join(ROOT, "金水谣数据", "log", "file_knowledge_index.json")

INDEX = {}

def _norm(p):
    p = p.replace("\\", "/").strip().lower()
    for prefix in [MODEL.replace("\\", "/") + "/", ROOT.replace("\\", "/") + "/"]:
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    p = re.sub(r'^模型/jinshuiyao_fixed/', '', p)
    p = re.sub(r'^jinshuiyao_fixed/', '', p)
    p = re.sub(r'^[a-z]:[/\\]', '', p)
    return p.strip("/")

_KNOWN_EXT = r'\.(py|json|md|bat|ps1|txt|yaml|yml|toml|ini|cfg|html|csv|xlsx)$'
_KNOWN_PREFIX = r'^(模型/|Jinshuiyao_Fixed/|scripts/|tools/|server/|config/|tests/|core/|domains/|knowledge/|金水谣数据/|engines/|fetchers/|deliverables/|data/|jinshuiyao/)'

def _is_valid_path(path):
    return bool(re.search(_KNOWN_EXT, path, re.IGNORECASE)) or bool(re.search(_KNOWN_PREFIX, path, re.IGNORECASE))

def _extract_backtick_paths(text):
    """提取反引号内的文件路径"""
    paths = []
    for m in re.finditer(r'`([^`]+)`', text):
        path = m.group(1).strip().rstrip('\\/.,;:')
        if _is_valid_path(path):
            paths.append(path)
    return paths

def _extract_slash_paths(text):
    """提取 path1 / path2 / path3 格式（关联文件字段常见）"""
    paths = []
    for m in re.finditer(r'(?:^|[^-/\w])([\w./-]+\.(?:py|json|md|txt|yaml|yml|toml|ini|cfg|html|csv))(?:\s|$|/)', text):
        path = m.group(1).strip()
        if path and '/' in path and not re.search(r'\s', path):
            paths.append(path)
    return paths

def _add(ref_path, kind, item_id, summary, source):
    n = _norm(ref_path)
    if not n or n == "." or len(n) < 2:
        return
    if n not in INDEX:
        INDEX[n] = []
    for existing in INDEX[n]:
        if existing.get("id") == item_id and existing.get("type") == kind:
            return
    INDEX[n].append({"type": kind, "id": item_id, "summary": summary, "source": source})

def _dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = (it["type"], it["id"])
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out

# ========== 工作留痕总索引.js — 三种格式 ==========

def _index_table_js(text):
    """表格式: | JS-XXXXXXXX-XX | date | topic | AI | 关键改动 | 验证 | 关联 | 成熟度 |"""
    for m in re.finditer(r'(?m)^\| (JS-\d{8}-\d{2}) \|.*? \|.*? \|([^|]+) \|([^|]+) \|', text):
        js_id = m.group(1)
        topic = m.group(2).strip()
        changes = m.group(3)
        for path in _extract_backtick_paths(changes):
            _add(path, "js", js_id, topic, "工作留痕总索引(表)")

def _index_pipe_js(text):
    """###-pipe格式: ### JS-XXXXXXXX-XX | date | time | project | topic | AI | status + body"""
    for m in re.finditer(r'### (JS-\d{8}-\d{2})\s*\|[^|]*\|[^|]*\|[^|]*\|([^|]+)', text):
        js_id = m.group(1)
        topic = m.group(2).strip()
        # find body
        body_match = re.search(rf'### {re.escape(js_id)}\s*\|.*?\n(.*?)(?=### JS-|\Z)', text, re.DOTALL)
        if not body_match:
            continue
        body = body_match.group(1)
        for section in [r'\*\*改动文件\*\*[：:]', r'改动文件[：:]', r'\*\*验证\*\*[：:]', r'正文']:
            if section == '正文':
                for path in _extract_backtick_paths(body):
                    _add(path, "js", js_id, topic, "工作留痕总索引")
            else:
                fs = re.search(section + r'(.*?)(?=\*\*[^体]|被否决方案|\Z)', body, re.DOTALL)
                if fs:
                    for path in _extract_backtick_paths(fs.group(1)):
                        _add(path, "js", js_id, topic, "工作留痕总索引")

def _index_dot_js(text):
    """###-dot格式: ### JS-XXXXXXXX-XX · topic · AI · brief"""
    for m in re.finditer(r'### (JS-\d{8}-\d{2})\s*·[^·]*·([^·]+)', text):
        js_id = m.group(1)
        topic = m.group(2).strip()
        # 这些记录在补录段，没有 改动文件 字段，从上下文提取
        body_match = re.search(rf'### {re.escape(js_id)}\s*·.*?\n(.*?)(?=### JS-|\Z)', text, re.DOTALL)
        if body_match:
            for path in _extract_backtick_paths(body_match.group(1)):
                _add(path, "js", js_id, topic, "工作留痕总索引(dot)")

# ========== ai_decisions.md ==========

def _index_ai_decisions():
    log_dir = os.path.join(ROOT, "金水谣数据", "log")
    fp = os.path.join(log_dir, "ai_decisions.md")
    if not os.path.isfile(fp):
        fp = os.path.join(ROOT, "金水谣数据", "log", "ai_decisions.md")
    if not os.path.isfile(fp):
        return
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    cards = re.split(r'(?m)^### ', text)[1:]
    for card_text in cards:
        first_line = card_text.split('\n')[0].strip()
        card_id = f"AD-{first_line[:30]}"
        card_title = first_line[:60]
        # 提取 关联文件 字段（各种格式）
        assoc_match = re.search(r'关联文件[：:]\s*(.*?)(?=\n(?:- |\n|$))', card_text, re.DOTALL)
        if assoc_match:
            assoc_text = assoc_match.group(1)
            # 尝试 backtick 提取
            for path in _extract_backtick_paths(assoc_text):
                _add(path, "ad", card_id, card_title, "ai_decisions.md")
            # 尝试 path1 / path2 / path3 格式
            for path in re.finditer(r'([\w./-]+\.(?:py|json|md|txt|yaml|yml|toml|ini|cfg|html|csv))', assoc_text):
                p = path.group(1).strip()
                if '/' in p:
                    _add(p, "ad", card_id, card_title, "ai_decisions.md")
        # 从正文提取 backtick 路径
        for path in _extract_backtick_paths(card_text):
            _add(path, "ad", card_id, card_title, "ai_decisions.md")

# ========== 经验收集箱.md ==========

def _index_experience_box():
    log_dir = os.path.join(ROOT, "金水谣数据", "log")
    fp = os.path.join(log_dir, "经验收集箱.md")
    if not os.path.isfile(fp):
        return
    with open(fp, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    entries = re.split(r'(?m)^####?\s+', text)[1:] if '####' in text else re.split(r'(?m)^###\s+', text)[1:]
    for i, entry_text in enumerate(entries[:200]):
        first_line = entry_text.split('\n')[0].strip()[:60]
        exp_id = f"EXP-{i+1:03d}"
        for path in _extract_backtick_paths(entry_text):
            _add(path, "exp", exp_id, first_line, "经验收集箱")
        for path in _extract_slash_paths(entry_text):
            _add(path, "exp", exp_id, first_line, "经验收集箱")

# ========== pattern_library.json & risk_register.json ==========

def _index_patterns():
    fp = os.path.join(KNOWLEDGE_DIR, "pattern_library.json")
    if not os.path.isfile(fp):
        return
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
    for pat in data.get("patterns", []):
        pid = pat.get("id", "?")
        title = pat.get("title", "")
        desc = pat.get("description", "")[:80]
        summary = f"[{pid}] {title}: {desc}"
        for field in ["references", "code_pattern", "fix_pattern",
                       "detection_strategy", "related_files", "test_files"]:
            val = pat.get(field, "")
            if isinstance(val, list):
                val = " ".join(val)
            for path in _extract_backtick_paths(val):
                _add(path, "pattern", pid, summary, "pattern_library")

def _index_risks():
    fp = os.path.join(ROOT, "金水谣数据", "risk_register.json")
    if not os.path.isfile(fp):
        return
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return
    for risk in data.get("risks", []):
        rid = risk.get("id", "?")
        desc = risk.get("description", "")[:80]
        summary = f"[{rid}] {desc}"
        txt = json.dumps(risk, ensure_ascii=False)
        for path in _extract_backtick_paths(txt):
            _add(path, "risk", rid, summary, "risk_register")
        for field in ["owner", "mitigation"]:
            for path in _extract_slash_paths(risk.get(field, "")):
                _add(path, "risk", rid, summary, "risk_register")

# ========== 聚合输出 ==========

def build():
    with open(os.path.join(MODEL, "工作留痕总索引.md"), "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    _index_table_js(text)
    _index_pipe_js(text)
    _index_dot_js(text)
    _index_ai_decisions()
    _index_experience_box()
    _index_patterns()
    _index_risks()

    # 去重 + 排序
    sorted_index = {}
    for path in sorted(INDEX.keys()):
        sorted_index[path] = _dedupe(INDEX[path])

    output = {
        "_generated": str(date.today()),
        "_schema": "v2",
        "_count": len(sorted_index),
        "_note": "文件→关联知识反向索引。由 tools/knowledge_index.py v2 自动生成，请勿手动编辑。",
        "entries": sorted_index
    }
    for dest in [INDEX_PATH, INDEX_PATH_LEGACY]:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    build()
    print(f"[知识索引] v2 生成完成：{len(INDEX)} 个文件条目")
    print(f"  位置: {INDEX_PATH}")
