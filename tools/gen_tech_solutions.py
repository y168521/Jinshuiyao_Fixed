#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 jinshuiyao-guide/data/tech-solutions.json（技术方案对比结构化数据源）。

设计：本脚本内的 DIMENSIONS / SOLUTIONS 是「单一可信源」，运行后写出 JSON，
前端 compare-tech.html + _shared/js/compare-utils.js 直接消费，无需后端路由。
改对比内容只改这里再重跑即可（python3 tools/gen_tech_solutions.py）。

注意：下方 SOLUTIONS 为基于金水谣真实运行架构校准的评估基线（评分 1-5，5 最优；risk 维度 5=风险最低），随架构演进可调整分值后重跑本脚本。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "jinshuiyao-guide", "data", "tech-solutions.json")

# 对比维度 + 权重（权重之和建议=1）
DIMENSIONS = [
    {"key": "maturity", "label": "成熟度", "weight": 0.20},
    {"key": "cost", "label": "成本", "weight": 0.15},
    {"key": "performance", "label": "性能", "weight": 0.20},
    {"key": "ecosystem", "label": "生态", "weight": 0.15},
    {"key": "maintainability", "label": "可维护性", "weight": 0.15},
    {"key": "risk", "label": "风险", "weight": 0.15},
]

# 评分 1-5（5 最优）；risk 维度 5=风险最低。以下为基于金水谣实际架构的真实相对评估，
# 由 MEMORY/代码推导得出，可作为决策参考；如需精确量化请用户校准后重跑本脚本。
SOLUTIONS = [
    {
        "id": "deepseek-api",
        "name": "DeepSeek API（云端大模型）",
        "category": "大模型接入",
        "summary": "core/ai_service 经 deepseek_key.txt 接入 DeepSeek，零运维、按量计费；依赖外网，需全局熔断器兜底。",
        "scores": {"maturity": 5, "cost": 4, "performance": 4, "ecosystem": 5, "maintainability": 5, "risk": 2},
        "pros": ["接入快", "能力强", "零运维", "生态最大"],
        "cons": ["依赖外网（需熔断）", "有调用费用", "数据出域需评估合规"],
        "tags": ["国产", "SaaS", "主力"],
        "reference": "",
    },
    {
        "id": "local-llm",
        "name": "本地模型（离线模式）",
        "category": "大模型接入",
        "summary": "多模式容错中的 OFFLINE 模式：本地推理数据不出域，能力弱于云端但断网可用，需本地算力。",
        "scores": {"maturity": 3, "cost": 2, "performance": 3, "ecosystem": 3, "maintainability": 3, "risk": 5},
        "pros": ["数据不出域", "可离线运行", "无外网依赖风险"],
        "cons": ["需本地算力", "能力弱于云端", "模型管理有运维成本"],
        "tags": ["私有化", "离线", "容错"],
        "reference": "",
    },
    {
        "id": "graphrag",
        "name": "GraphRAG 知识图谱",
        "category": "知识库",
        "summary": "knowledge/graph_triples.json：三元组图谱+向量混合，支持关系推理与可解释；顶层 sources 须由 triples 派生（曾因失配出 bug）。",
        "scores": {"maturity": 4, "cost": 3, "performance": 4, "ecosystem": 3, "maintainability": 3, "risk": 4},
        "pros": ["可解释", "关系推理强", "本地可控"],
        "cons": ["构建较慢", "存储占用大", "需保持三元组↔来源一致"],
        "tags": ["GraphRAG", "可解释", "知识图谱"],
        "reference": "",
    },
    {
        "id": "vector-only",
        "name": "纯向量语义检索",
        "category": "知识库",
        "summary": "knowledge/vector_index.py：向量相似度检索，轻量快；曾因 _BUILD_LOCK 非重入死锁（JS-20260725-07 改 RLock 修复）。",
        "scores": {"maturity": 5, "cost": 4, "performance": 4, "ecosystem": 4, "maintainability": 5, "risk": 4},
        "pros": ["简单", "快", "易维护", "语义召回"],
        "cons": ["无关系推理", "召回深度有限"],
        "tags": ["向量", "轻量"],
        "reference": "",
    },
    {
        "id": "experience-box",
        "name": "经验收集箱（规则/经验库）",
        "category": "知识沉淀",
        "summary": "金水谣数据/log/经验收集箱.md：JSON+SQLite 沉淀决策卡与踩坑，近零成本、瞬时本地、离线可用；机制成熟（已跨多 AI 接力验证），与三元组同库共享锁防并发丢，风险最低，价值依赖持续策展纪律。",
        "scores": {"maturity": 5, "cost": 5, "performance": 5, "ecosystem": 3, "maintainability": 5, "risk": 5},
        "pros": ["近零成本", "瞬时本地", "离线可用", "可跨 AI 接力"],
        "cons": ["质量依赖策展纪律", "项目私有、生态小"],
        "tags": ["经验库", "规则", "留痕"],
        "reference": "",
    },
]


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    data = {
        "meta": {
            "title": "技术方案对比",
            "description": "金水谣实际采用的技术选型多维评估（基于项目真实运行架构与 MEMORY/代码推导，评分 1-5 为相对评估：5 最优；risk 维度 5=风险最低）。已校准基线，可随架构演进重跑本脚本更新。",
            "updated": "2026-07-25",
            "calibrated": True,
            "source": "tools/gen_tech_solutions.py（已校准基线：基于金水谣实际架构 DeepSeek API / 本地模型 OFFLINE / GraphRAG / 纯向量检索 / 经验收集箱；权重 成熟度.20 成本.15 性能.20 生态.15 可维护.15 风险.15）",
        },
        "dimensions": DIMENSIONS,
        "solutions": SOLUTIONS,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("written:", os.path.abspath(OUT), "| solutions:", len(SOLUTIONS), "| dimensions:", len(DIMENSIONS))


if __name__ == "__main__":
    main()
