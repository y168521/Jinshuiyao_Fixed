# -*- coding: utf-8 -*-
"""
金水谣知识图谱雏形
====================
从双库卡片中提取实体（标签/关键词），建立共现关系网络。
支持：实体提取、关系构建、邻居查询、聚类发现。

存储：knowledge/knowledge_graph.json
节点 = 实体（标签、领域、关键概念）
边 = 共现关系（同一张卡片中出现）+ 交叉链接

用法：
    from knowledge.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()
    kg.build()                    # 从双库提取实体+关系
    neighbors = kg.get_neighbors("PARA")  # 查某实体的关联
    clusters = kg.get_clusters()  # 发现知识聚类
"""
import os
import re
import json
import logging
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
USER_KB_DIR = os.path.join(KNOWLEDGE_DIR, "用户知识库")
MIROFISH_DB_PATH = os.path.join(KNOWLEDGE_DIR, "mirofish_db.json")
GRAPH_PATH = os.path.join(KNOWLEDGE_DIR, "knowledge_graph.json")

# 停用词：太泛的标签不作为实体
STOP_ENTITIES = {
    "视频提取", "教程", "general", "test", "其他",
    "数据", "信息", "知识", "智慧",
}


class KnowledgeGraph:
    """知识图谱：实体-关系网络"""

    def __init__(self):
        self._graph = None

    # ------------------------------------------------------------------
    # 构建图谱
    # ------------------------------------------------------------------
    def build(self, save=True):
        """
        从双库提取实体和关系，构建图谱。

        返回:
            {"nodes": int, "edges": int, "clusters": int}
        """
        nodes = {}  # entity -> {type, count, sources}
        edges = defaultdict(lambda: {"weight": 0, "cards": []})

        # 1. 从MiroFish提取
        miro_cards = self._load_mirofish()
        for card in miro_cards:
            entities = self._extract_entities(card, "mirofish")
            self._add_entities(nodes, entities, "mirofish", card["title"])
            self._add_cooccurrence(edges, entities, card["title"])

        # 2. 从用户知识库提取
        user_cards = self._load_user_kb()
        for card in user_cards:
            entities = self._extract_entities(card, "user_kb")
            self._add_entities(nodes, entities, "user_kb", card["title"])
            self._add_cooccurrence(edges, entities, card["title"])

        # 3. 从 GraphRAG 三元组库补充有向关系（D：densify 图谱，支持多跳推理）
        self._add_triple_edges(edges, nodes)

        # 4. 从交叉链接补充关系
        self._add_crosslinks(edges)

        # 4. 构建最终图谱
        edge_list = []
        for (a, b), info in edges.items():
            if info["weight"] >= 1:
                edge = {
                    "source": a,
                    "target": b,
                    "weight": info["weight"],
                    "cards": info["cards"][:3],  # 最多记录3张来源卡片
                }
                # 携带 GraphRAG 三元组的谓词关系（D：densify 图谱，支持多跳/可视化）
                if info.get("relations"):
                    edge["relations"] = info["relations"]
                edge_list.append(edge)

        node_list = []
        for name, info in nodes.items():
            node_list.append({
                "id": name,
                "type": info["type"],
                "count": info["count"],
                "sources": list(info["sources"]),
            })

        # 按度数排序（连接越多越重要）
        degree = defaultdict(int)
        for e in edge_list:
            degree[e["source"]] += 1
            degree[e["target"]] += 1
        node_list.sort(key=lambda n: degree.get(n["id"], 0), reverse=True)

        graph_data = {
            "version": "1.0",
            "description": "金水谣知识图谱（实体共现网络）",
            "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nodes": node_list,
            "edges": edge_list,
            "stats": {
                "total_nodes": len(node_list),
                "total_edges": len(edge_list),
                "mirofish_cards": len(miro_cards),
                "user_kb_cards": len(user_cards),
            }
        }

        if save:
            self._save(graph_data)
        self._graph = graph_data

        return {
            "nodes": len(node_list),
            "edges": len(edge_list),
            "clusters": len(self._find_clusters(node_list, edge_list)),
        }

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_neighbors(self, entity, limit=10):
        """获取某实体的关联实体（按权重排序）"""
        graph = self._load()
        neighbors = []
        for edge in graph.get("edges", []):
            if edge["source"] == entity:
                neighbors.append({
                    "entity": edge["target"],
                    "weight": edge["weight"],
                    "cards": edge.get("cards", []),
                })
            elif edge["target"] == entity:
                neighbors.append({
                    "entity": edge["source"],
                    "weight": edge["weight"],
                    "cards": edge.get("cards", []),
                })
        neighbors.sort(key=lambda x: x["weight"], reverse=True)
        return neighbors[:limit]

    def get_node_info(self, entity):
        """获取实体节点详情"""
        graph = self._load()
        for node in graph.get("nodes", []):
            if node["id"] == entity:
                return node
        return None

    def get_clusters(self):
        """发现知识聚类（连通分量）"""
        graph = self._load()
        return self._find_clusters(graph.get("nodes", []), graph.get("edges", []))

    def get_top_entities(self, limit=20):
        """获取最重要的实体（按度数）"""
        graph = self._load()
        degree = defaultdict(int)
        for edge in graph.get("edges", []):
            degree[edge["source"]] += edge["weight"]
            degree[edge["target"]] += edge["weight"]
        ranked = sorted(degree.items(), key=lambda x: x[1], reverse=True)
        return [{"entity": e, "degree": d} for e, d in ranked[:limit]]

    def get_stats(self):
        """图谱统计"""
        graph = self._load()
        return graph.get("stats", {})

    def get_graph_data(self, max_nodes=50):
        """获取图谱数据（供前端可视化，限制节点数）"""
        graph = self._load()
        nodes = graph.get("nodes", [])[:max_nodes]
        node_ids = set(n["id"] for n in nodes)
        edges = [e for e in graph.get("edges", [])
                 if e["source"] in node_ids and e["target"] in node_ids]
        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _extract_entities(self, card, lib):
        """从卡片中提取实体"""
        entities = set()
        # 标签作为实体
        for tag in card.get("tags", []):
            tag_clean = tag.strip().lower()
            if tag_clean and tag_clean not in STOP_ENTITIES and len(tag_clean) > 1:
                entities.add(tag.strip())
        # 领域作为实体
        domain = card.get("domain", "")
        if domain and domain != "general":
            entities.add(domain)
        # 从标题提取关键概念（2-6字中文词组）
        title = card.get("title", "")
        # 去除前缀标记如 [fund]、[music]
        title_clean = re.sub(r'^\[[\w]+\]\s*', '', title)
        # 提取中文词组（简单策略：按标点切分后的片段）
        segments = re.split(r'[：:，,。.、/\\（）()\[\]【】]', title_clean)
        for seg in segments:
            seg = seg.strip()
            if 2 <= len(seg) <= 8 and re.search(r'[\u4e00-\u9fff]', seg):
                entities.add(seg)
        return entities

    def _add_entities(self, nodes, entities, lib, card_title):
        """注册实体节点"""
        for e in entities:
            if e not in nodes:
                nodes[e] = {"type": self._classify_entity(e), "count": 0, "sources": set()}
            nodes[e]["count"] += 1
            nodes[e]["sources"].add(lib)

    def _add_cooccurrence(self, edges, entities, card_title):
        """同一卡片中的实体建立共现边"""
        entity_list = sorted(entities)
        for i in range(len(entity_list)):
            for j in range(i + 1, len(entity_list)):
                key = (entity_list[i], entity_list[j])
                edges[key]["weight"] += 1
                if len(edges[key]["cards"]) < 3:
                    edges[key]["cards"].append(card_title[:30])

    def _add_triple_edges(self, edges, nodes):
        """从 GraphRAG 三元组库补充有向关系（D：densify 图谱）。

        每个三元组 (subject, predicate, object) 在共现网络中添加一条加权边，
        relation 字段记录谓词，便于后续多跳查询与可视化。
        """
        triple_path = os.path.join(KNOWLEDGE_DIR, "graph_triples.json")
        if not os.path.isfile(triple_path):
            return
        try:
            with open(triple_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (IOError, json.JSONDecodeError):
            return
        for t in data.get("triples", []):
            s = (t.get("subject") or "").strip()
            o = (t.get("object") or "").strip()
            p = (t.get("predicate") or "").strip()
            if not s or not o:
                continue
            for ent in (s, o):
                if ent not in nodes:
                    nodes[ent] = {"type": self._classify_entity(ent),
                                  "count": 0, "sources": set()}
                nodes[ent]["count"] += 1
                nodes[ent]["sources"].add("triple")
            key = (s, o) if s <= o else (o, s)
            edges[key]["weight"] += 1
            edges[key].setdefault("relations", [])
            if p and p not in edges[key]["relations"]:
                edges[key]["relations"].append(p)

    def _add_crosslinks(self, edges):
        """从交叉链接补充关系"""
        crosslinks_path = os.path.join(KNOWLEDGE_DIR, "crosslinks.json")
        if not os.path.isfile(crosslinks_path):
            return
        try:
            with open(crosslinks_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for link in data.get("links", []):
                # 用标题的前几个字作为实体关联
                src = link.get("source_title", "")[:10]
                tgt = link.get("target_title", "")[:10]
                if src and tgt:
                    key = (src, tgt) if src < tgt else (tgt, src)
                    edges[key]["weight"] += 2  # 交叉链接权重更高
        except (IOError, json.JSONDecodeError):
            pass

    @staticmethod
    def _classify_entity(entity):
        """简单分类实体类型"""
        e = entity.lower()
        if any(k in e for k in ["策略", "方法", "算法", "模型", "规则"]):
            return "method"
        if any(k in e for k in ["工具", "库", "框架", "api", "skill"]):
            return "tool"
        if any(k in e for k in ["彩票", "3d", "双色球", "基金", "股", "足彩"]):
            return "domain"
        if any(k in e for k in ["知识", "记忆", "学习", "管理"]):
            return "concept"
        return "tag"

    def _find_clusters(self, nodes, edges):
        """简单连通分量聚类"""
        if not nodes:
            return []
        # Union-Find
        parent = {}
        def find(x):
            if x not in parent:
                parent[x] = x
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for edge in edges:
            union(edge["source"], edge["target"])

        clusters = defaultdict(list)
        for node in nodes:
            root = find(node["id"])
            clusters[root].append(node["id"])

        # 只返回大小>=2的聚类
        result = []
        for members in clusters.values():
            if len(members) >= 2:
                result.append({"size": len(members), "members": members[:10]})
        result.sort(key=lambda c: c["size"], reverse=True)
        return result

    def _load_mirofish(self):
        """加载MiroFish卡片"""
        try:
            with open(MIROFISH_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("cards", [])
        except (IOError, json.JSONDecodeError):
            return []

    def _load_user_kb(self):
        """加载用户知识库卡片"""
        cards = []
        index_path = os.path.join(USER_KB_DIR, "INDEX.json")
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)
            for entry in index:
                cards.append({
                    "title": entry.get("title", ""),
                    "tags": entry.get("tags", []),
                    "domain": "general",
                })
        except (IOError, json.JSONDecodeError):
            pass
        return cards

    def _load(self):
        """加载图谱数据"""
        if self._graph is not None:
            return self._graph
        if not os.path.isfile(GRAPH_PATH):
            return {"nodes": [], "edges": [], "stats": {}}
        try:
            with open(GRAPH_PATH, "r", encoding="utf-8") as f:
                self._graph = json.load(f)
            return self._graph
        except (IOError, json.JSONDecodeError):
            return {"nodes": [], "edges": [], "stats": {}}

    def _save(self, data):
        """保存图谱（原子写入）"""
        try:
            from utils.safe_json import safe_write_json
            safe_write_json(GRAPH_PATH, data)
        except ImportError:
            tmp = GRAPH_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, GRAPH_PATH)


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------
_graph_instance = None

def get_graph():
    """获取全局知识图谱单例"""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = KnowledgeGraph()
    return _graph_instance
