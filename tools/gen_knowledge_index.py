# -*- coding: utf-8 -*-
"""知识网关索引生成器 — 外部AI的第一入口文档（index.md 式）

扫描项目知识资产，生成 知识网关索引.md：
每类知识一行（名称+一句话+路径+规模），外部 AI 读它即知道
"这个项目的知识在哪、有哪些、怎么查"，再按需深入或调网关。
"""
import json
import os
import re
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE_DIR, '知识网关索引.md')


def wc(path):
    try:
        with open(path, encoding='utf-8') as f:
            return len(f.readlines())
    except Exception:
        return 0


def exists(path):
    return os.path.isfile(path)


def main():
    log_dir = os.path.join(BASE_DIR, '金水谣数据', 'log')
    exp_lines = wc(os.path.join(log_dir, '经验收集箱.md'))
    ai_dec_lines = wc(os.path.join(log_dir, 'ai_decisions.md'))

    # 卡片规模
    cards = 0
    try:
        sys.path.insert(0, BASE_DIR)
        from knowledge.mirofish_db import MiroFishDB
        db = MiroFishDB()
        cards = len(db._data.get('cards', []))
    except Exception:
        pass

    # 三元组
    triples = 0
    try:
        with open(os.path.join(BASE_DIR, 'knowledge', 'graph_triples.json'), encoding='utf-8') as f:
            triples = len(json.load(f).get('triples', []))
    except Exception:
        pass

    # 图谱实体
    entities = 0
    try:
        from knowledge.knowledge_graph import get_graph
        g = get_graph()
        entities = len(g.get_graph_data(max_nodes=10 ** 9).get('nodes', []))
    except Exception:
        pass

    # Skill
    skills = []
    skills_dir = os.path.join(BASE_DIR, '.opencode', 'skills')
    if os.path.isdir(skills_dir):
        for d in sorted(os.listdir(skills_dir)):
            if os.path.isfile(os.path.join(skills_dir, d, 'SKILL.md')):
                skills.append(d)

    # 知识库卡片数（用户知识库）
    user_kb = []
    kb_dir = os.path.join(BASE_DIR, 'knowledge', '用户知识库')
    if os.path.isdir(kb_dir):
        user_kb = [f for f in os.listdir(kb_dir) if f.endswith('.md')]

    lines = []
    lines.append('# 知识网关索引（Knowledge Gateway Index）')
    lines.append('')
    lines.append('> 本文件是外部 AI（opencode/Claude Code/Qoder/豆包等）接入金水谣项目的**第一入口**。')
    lines.append('> 生成时间：' + __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    lines.append('> 规则：**先读本索引定位，再按需深入；复杂问题用网关检索 `/api/knowledge/gateway?q=...` 四源召回。**')
    lines.append('')
    lines.append('## 一、项目规范（必读，开工前）')
    lines.append('')
    lines.append('| 文档 | 路径 | 用途 |')
    lines.append('|------|------|------|')
    lines.append('| 交接中心 | `模型/AI协作交接中心.md` | 已完成/待办/环境，开工先读 |')
    lines.append('| 总索引 | `模型/工作留痕总索引.md` | 所有变更 JS-编号 倒查 |')
    lines.append('| 天·纲 | `模型/金水谣_纲.md` | 五铁律、代码审查Pipeline |')
    lines.append('| 地·契 | `模型/金水谣_契.md` | 编码规范、模块边界 |')
    lines.append('| 人·录 | `模型/金水谣_录.md` | 接手SOP、质量保障 |')
    lines.append('| AGENTS.md | 仓库根 | 铁律0(完成即留存)、环境、收工流程 |')
    lines.append('')
    lines.append('## 二、知识资产规模（自动统计）')
    lines.append('')
    lines.append('| 资产 | 位置 | 规模 | 用途 |')
    lines.append('|------|------|------|------|')
    lines.append('| 经验收集箱（L1原始层） | `金水谣数据/log/经验收集箱.md` | %d 行 | 踩坑/教训/方案原始记录，跨AI共享，永不删除 |' % exp_lines)
    lines.append('| AI决策记录 | `金水谣数据/log/ai_decisions.md` | %d 行 | 关键决策与理由 |' % ai_dec_lines)
    lines.append('| 知识卡片（MiroFish） | `knowledge/mirofish_db.json` | %d 张 | 经验/成败/方法卡片，全文检索 |' % cards)
    lines.append('| 图谱三元组（GraphRAG） | `knowledge/graph_triples.json` | %d 条 | 实体-关系证据，多跳推理 |' % triples)
    lines.append('| 实体图谱 | `knowledge/knowledge_graph.json` | %d 节点 | 实体网络，可视化 |' % entities)
    lines.append('| Skill（L3可执行规则） | `.opencode/skills/` | %d 个 | %s |' % (len(skills), '、'.join(skills)))
    lines.append('| 用户知识库 | `knowledge/用户知识库/` | %d 个md | 外部资料整理（Karpathy双层：raw+卡片） |' % len(user_kb))
    lines.append('')
    lines.append('## 三、知识检索入口')
    lines.append('')
    lines.append('1. **知识网关**（推荐，四源一次召回）：`GET /api/knowledge/gateway?q=问题&limit=8`')
    lines.append('   - 返回：知识卡片 + 图谱三元组 + 向量召回 + 经验条目 + 项目文档片段')
    lines.append('2. **知识搜索**：`POST /api/knowledge/search`（全文+三元组+向量融合）')
    lines.append('3. **图谱检索**：`GET /api/knowledge/graph/search?q=实体`')
    lines.append('4. **向量检索**：`GET /api/knowledge/vector/search?q=...`')
    lines.append('5. **经验箱直读**：`金水谣数据/log/经验收集箱.md`（搜索 `## 日期` 标题）')
    lines.append('')
    lines.append('## 四、知识流向（织网全景）')
    lines.append('')
    lines.append('```')
    lines.append('经验收集箱(L1原始) ──自动蒸馏──> Skill(L3规则,带原文指针)')
    lines.append('       │──提取──> 知识卡片(MiroFish) ──> 全文检索')
    lines.append('       └──三元组──> 图谱(567条) ──> 多跳推理/搜索证据')
    lines.append('用户知识库(raw证据+卡片) ──> 实体图谱 ──> 可视化')
    lines.append('所有层 ──> 知识网关 ──> 外部AI/网页助手/服务器')
    lines.append('```')
    lines.append('')
    lines.append('## 五、给外部 AI 的接入建议')
    lines.append('')
    lines.append('1. 开工前：读本索引 → 读 交接中心 → 读 AGENTS.md（铁律0必须遵守）')
    lines.append('2. 遇到问题：先用知识网关搜（经验箱里 90% 的坑都有记录，搜对词直接定位）')
    lines.append('3. 完成工作：按铁律0 登记交接中心 + 总索引 + 当天写经验收集箱')
    lines.append('4. 复杂问题：`query_graph` / `get_experience` 可多跳追问（MCP 工具）')
    lines.append('')

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('已生成:', OUT)
    print('卡片=%d 三元组=%d 实体=%d Skill=%d 用户知识库=%d 经验箱=%d行' % (
        cards, triples, entities, len(skills), len(user_kb), exp_lines))


if __name__ == '__main__':
    main()
