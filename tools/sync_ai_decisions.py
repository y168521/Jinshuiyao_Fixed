#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI 决策手动同步工具（离线 / 应急兜底）
======================================
金水谣 server 没在跑（无 watcher 监听）时，或想立即强制同步时，手动调用本脚本：
  把 ai_decisions.md 的新决策卡抽取为 ① MiroFish 知识卡片 ② GraphRAG 三元组。
幂等：基于内容 sha256 标记，重复运行不重复入库。

用法：
    py -3.14 tools/sync_ai_decisions.py                 # 默认 NORMAL 模式全量同步
    py -3.14 tools/sync_ai_decisions.py --mode DEGRADED # 跳过三元组（仅写卡片）
    py -3.14 tools/sync_ai_decisions.py --mode OFFLINE  # 无网络仅写卡片
    py -3.14 tools/sync_ai_decisions.py --search "为什么加 _TRIPLE_STORE_LOCK"  # 检索已沉淀决策

纯标准库 + 项目内模块；即使 server 挂了也能跑（卡片不依赖 LLM，三元组依赖 DeepSeek key）。
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _setup_path():
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)


def main():
    parser = argparse.ArgumentParser(description="AI 决策手动同步 / 检索")
    parser.add_argument("--mode", default="NORMAL",
                        choices=["NORMAL", "DEGRADED", "OFFLINE", "OVERRIDE"],
                        help="同步模式（应对突发情况）")
    parser.add_argument("--search", default="",
                        help="检索已沉淀的 AI 决策知识（关键词）")
    args = parser.parse_args()

    _setup_path()
    try:
        # 模块位置随 God Object 拆分(JS-20260724-39)迁移：
        #   set_pipeline_mode → core.pipeline_mode
        #   extract_* → core.ai_decisions_extractor
        #   search_ai_knowledge → knowledge.knowledge_search
        # 优先按新位置导入；旧版 auto_knowledge 若仍 re-export 则回退兼容。
        try:
            from core.pipeline_mode import set_pipeline_mode
            from core.ai_decisions_extractor import (
                extract_from_ai_decisions,
                extract_triples_from_ai_decisions,
            )
            from knowledge.knowledge_search import search_ai_knowledge
        except Exception:
            from core.auto_knowledge import (  # 向后兼容：旧单体仍导出时
                set_pipeline_mode, extract_from_ai_decisions,
                extract_triples_from_ai_decisions, search_ai_knowledge,
            )
    except Exception as e:
        print(f"[!!] 导入知识库管线失败: {e}")
        return 1

    # 检索模式：直接查，不写
    if args.search:
        res = search_ai_knowledge(args.search, limit=10)
        print(f"\n[AI决策检索] 命中 {res['count']} 条（关键词：{args.search}）")
        if res["cards"]:
            print("  —— 决策卡 ——")
            for c in res["cards"]:
                print(f"  · {c['title']}")
                print(f"    {c['snippet']}")
        if res["triples"]:
            print("  —— 三元组 ——")
            for t in res["triples"]:
                print(f"  · ({t['subject']}) —[{t['predicate']}]→ ({t['object']})")
        if res["count"] == 0:
            print("  （无命中；可能尚未同步，或关键词不匹配）")
        return 0

    # 同步模式
    set_pipeline_mode(args.mode)
    print(f"[..] 管线模式={args.mode}，开始同步 ai_decisions.md ...")
    try:
        r = extract_from_ai_decisions()
        print(f"  [OK] 决策卡片: 新条目={r.get('new_entries')} 提取={r.get('extracted')} "
              f"保存={r.get('saved')} ({r.get('info','')})")
    except Exception as e:
        print(f"  [!!] 卡片同步异常: {e}")

    try:
        tr = extract_triples_from_ai_decisions()
        print(f"  [OK] GraphRAG 三元组: 处理={tr.get('processed')} 解析={tr.get('triples')} "
              f"新增={tr.get('saved')} ({tr.get('info','')})")
    except Exception as e:
        print(f"  [!!] 三元组同步异常: {e}")

    print("[OK] 同步完成。下一个 AI 可通过知识库检索 / search_ai_knowledge() 找到这些决策。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
