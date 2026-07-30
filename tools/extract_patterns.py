# -*- coding: utf-8 -*-
"""金水谣 · 模式库经验抽取器

从经验箱决策卡（ai_decisions.md）抽取真实踩坑证据，补充到 pattern_library.json，
让手编种子具备「经验来源可追溯」能力（设计文档 T4 收尾项）。

逻辑：
  1. 扫描 ai_decisions.md 所有决策卡（### 标题 + 关联总索引 JS 编号 + 坑字段）
  2. 按 category→关键词映射，统计每类反模式在多少条决策卡里出现（证据强度）
  3. 给 pattern_library.json 中匹配 category 的 PAT 补充 evidence 字段：
     {source_count, source_js[], extracted_from}
  4. 不新增重复 PAT、不破坏现有结构，仅增强可追溯性

用法：
  python tools/extract_patterns.py            # 抽取并写回
  python tools/extract_patterns.py --report   # 仅打印报告不写回
"""
import json
import os
import re
import sys
import argparse

# ─── 路径 ───
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEC = os.path.join(_ROOT, "金水谣数据", "log", "ai_decisions.md")
_LIB = os.path.join(_ROOT, "knowledge", "pattern_library.json")

# ─── 反模式类别 → 关键词（从 ai_decisions 坑字段匹配）───
CAT_KEYWORDS = {
    "concurrency": ["锁", "死锁", "重入", "并发", "线程"],
    "security": ["SSRF", "泄露", "硬编码"],
    "maintainability": ["裸except", "except:", "吞异常"],
    "data_integrity": ["全局", "读-改-写", "状态恢复"],
    "performance": ["索引", "缓存", "N+1"],
}


def extract_cards(text):
    """提取决策卡：### 标题 / 关联总索引 JS 编号 / 坑字段文本"""
    cards = []
    # 防御：若文件首行即 ### 卡片（前无换行），补一个换行，避免首卡被 split 漏掉
    if not text.startswith('\n'):
        text = '\n' + text
    blocks = re.split(r'\n### ', text)
    for b in blocks[1:]:
        header = b.split('\n', 1)[0].strip()
        js_ids = re.findall(r'JS-\d{8}-\d+', b)
        # 兼容 "- 坑：" / "**坑**："(加粗) / "-坑:" 等格式；re.S 跨行捕获，前瞻到下一个 "- " 字段或块尾
        pit_m = re.search(r'[-*]\s*[*]{0,2}坑\s*[*]{0,2}\s*[:：]\s*(.*?)(?=\n\s*- |\Z)', b, re.S)
        pit_text = pit_m.group(1).strip() if pit_m else ''
        if js_ids or '坑' in b:
            cards.append({"header": header, "js": js_ids, "pit": pit_text})
    return cards


def collect_evidence(cards):
    """统计每类反模式的证据强度 + 来源 JS 编号"""
    evidence = {cat: {"count": 0, "js": set()} for cat in CAT_KEYWORDS}
    for c in cards:
        blob = c['pit']
        for cat, kws in CAT_KEYWORDS.items():
            if any(k in blob for k in kws):
                evidence[cat]["count"] += 1
                evidence[cat]["js"].update(c['js'])
    return evidence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="仅报告不写回")
    args = ap.parse_args()

    if not os.path.isfile(_DEC):
        print(f"[extract_patterns] 未找到决策卡: {_DEC}")
        sys.exit(1)

    text = open(_DEC, encoding='utf-8').read()
    cards = extract_cards(text)
    evidence = collect_evidence(cards)

    if args.report:
        print(f"[extract_patterns] 扫描 {len(cards)} 条决策卡")
        for cat, ev in evidence.items():
            print(f"  {cat}: {ev['count']} 条证据, {len(ev['js'])} 个 JS 来源")
        return

    try:
        with open(_LIB, encoding='utf-8') as f:
            lib = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[extract_patterns] 读取模式库失败（文件可能损坏或被占用）: {_LIB}")
        print(f"  错误: {e}")
        sys.exit(1)
    updated = 0
    for p in lib.get('patterns', []):
        cat = p.get('category')
        if cat in evidence and evidence[cat]['count'] > 0:
            p['evidence'] = {
                "source_count": evidence[cat]['count'],
                "source_js": sorted(evidence[cat]['js'])[:10],
                "extracted_from": "ai_decisions.md",
            }
            updated += 1

    lib['metadata'] = lib.get('metadata', {})
    lib['metadata']['evidence_extracted_at'] = __import__('time').strftime('%Y-%m-%dT%H:%M:%S')
    lib['metadata']['evidence_source_cards'] = len(cards)

    _tmp = _LIB + '.tmp'
    try:
        with open(_tmp, 'w', encoding='utf-8') as f:
            json.dump(lib, f, ensure_ascii=False, indent=2)
        os.replace(_tmp, _LIB)  # 原子替换，避免写到一半损坏文件
    except Exception:
        if os.path.exists(_tmp):
            os.remove(_tmp)
        raise
    print(f"[extract_patterns] 完成：{updated} 条 PAT 补充经验证据（来源 {len(cards)} 条决策卡）")
    for cat, ev in evidence.items():
        if ev['count'] > 0:
            print(f"  {cat}: {ev['count']} 条证据 ← {sorted(ev['js'])[:3]}{'...' if len(ev['js'])>3 else ''}")


if __name__ == '__main__':
    main()
