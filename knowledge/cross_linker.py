# -*- coding: utf-8 -*-
"""
金水谣双库交叉链接器（胼胝体）
================================
连接左脑（MiroFish模型知识库）和右脑（用户知识库），
自动发现两库间的知识关联，支持手动补充。

存储：knowledge/crosslinks.json
算法：标签Jaccard + 标题关键词重叠 + 领域匹配

用法：
    from knowledge.cross_linker import CrossLinker
    linker = CrossLinker()
    linker.discover()           # 自动发现关联
    links = linker.get_links("miro", "a1b2c3d4")  # 查某卡片的跨库链接
"""
import os
import re
import json
import hashlib
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
USER_KB_DIR = os.path.join(KNOWLEDGE_DIR, "用户知识库")
MIROFISH_DB_PATH = os.path.join(KNOWLEDGE_DIR, "mirofish_db.json")
CROSSLINKS_PATH = os.path.join(KNOWLEDGE_DIR, "crosslinks.json")

# 相似度阈值：超过此值才建立链接
SIMILARITY_THRESHOLD = 0.25


class CrossLinker:
    """双库交叉链接管理器"""

    def __init__(self):
        self._mirofish_cards = None
        self._user_kb_cards = None

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------
    def _load_mirofish(self):
        """加载MiroFish卡片（精简字段）"""
        if self._mirofish_cards is not None:
            return self._mirofish_cards
        cards = []
        try:
            with open(MIROFISH_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for c in data.get("cards", []):
                cards.append({
                    "id": c.get("id", ""),
                    "title": c.get("title", ""),
                    "tags": c.get("tags", []),
                    "domain": c.get("domain", "general"),
                    "category": c.get("category", ""),
                    "content_preview": c.get("content", "")[:200],
                })
        except (IOError, json.JSONDecodeError) as e:
            logger.error("加载MiroFish失败: %s", e)
        self._mirofish_cards = cards
        return cards

    def _load_user_kb(self):
        """加载用户知识库卡片（从INDEX.json + 文件内容）"""
        if self._user_kb_cards is not None:
            return self._user_kb_cards
        cards = []
        index_path = os.path.join(USER_KB_DIR, "INDEX.json")
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except (IOError, json.JSONDecodeError):
            index = []

        for entry in index:
            title = entry.get("title", "")
            tags = entry.get("tags", [])
            filename = entry.get("file", "")
            # 读取文件前200字作为内容预览
            content_preview = ""
            filepath = os.path.join(USER_KB_DIR, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content_preview = f.read(400)
                except IOError:
                    pass
            cards.append({
                "id": hashlib.md5(filename.encode()).hexdigest()[:8],
                "title": title,
                "tags": tags,
                "domain": "general",
                "category": "user_kb",
                "content_preview": content_preview,
                "file": filename,
            })
        self._user_kb_cards = cards
        return cards

    # ------------------------------------------------------------------
    # 相似度计算
    # ------------------------------------------------------------------
    @staticmethod
    def _tokenize(text):
        """中文分词（简易：按标点和空格切 + 2字bigram）"""
        # 去除标点，保留中文、英文、数字
        clean = re.sub(r'[^\w\u4e00-\u9fff]', ' ', text.lower())
        words = set(clean.split())
        # 对中文部分生成bigram
        chinese = re.findall(r'[\u4e00-\u9fff]+', text.lower())
        for seg in chinese:
            for i in range(len(seg) - 1):
                words.add(seg[i:i+2])
        return words

    def _similarity(self, card_a, card_b):
        """计算两张卡片的综合相似度（0~1）"""
        score = 0.0

        # 1. 标签Jaccard（权重0.4）
        tags_a = set(t.lower() for t in card_a.get("tags", []))
        tags_b = set(t.lower() for t in card_b.get("tags", []))
        if tags_a and tags_b:
            jaccard = len(tags_a & tags_b) / len(tags_a | tags_b)
            score += jaccard * 0.4

        # 2. 标题关键词重叠（权重0.35）
        title_a = self._tokenize(card_a.get("title", ""))
        title_b = self._tokenize(card_b.get("title", ""))
        if title_a and title_b:
            overlap = len(title_a & title_b) / min(len(title_a), len(title_b))
            score += overlap * 0.35

        # 3. 内容预览关键词重叠（权重0.15）
        content_a = self._tokenize(card_a.get("content_preview", ""))
        content_b = self._tokenize(card_b.get("content_preview", ""))
        if content_a and content_b:
            # 取交集占较小集合的比例
            overlap = len(content_a & content_b) / min(len(content_a), len(content_b))
            score += min(overlap, 1.0) * 0.15

        # 4. 领域匹配加分（权重0.1）
        if card_a.get("domain") == card_b.get("domain") and card_a.get("domain") != "general":
            score += 0.1

        return round(score, 4)

    # ------------------------------------------------------------------
    # 核心功能：自动发现链接
    # ------------------------------------------------------------------
    def discover(self, threshold=None, save=True):
        """
        自动发现两库间的关联。

        返回:
            {
                "new_links": [...],     # 新发现的链接
                "total_links": int,     # 链接总数
                "mirofish_count": int,
                "user_kb_count": int,
            }
        """
        if threshold is None:
            threshold = SIMILARITY_THRESHOLD

        # 重置缓存，确保读最新数据
        self._mirofish_cards = None
        self._user_kb_cards = None

        miro_cards = self._load_mirofish()
        user_cards = self._load_user_kb()

        # 加载已有链接
        existing = self._load_links()
        existing_pairs = set()
        for link in existing.get("links", []):
            pair = (link["source_id"], link["target_id"])
            existing_pairs.add(pair)

        new_links = []
        for mc in miro_cards:
            for uc in user_cards:
                pair = (mc["id"], uc["id"])
                if pair in existing_pairs:
                    continue
                sim = self._similarity(mc, uc)
                if sim >= threshold:
                    new_links.append({
                        "source_id": mc["id"],
                        "source_lib": "mirofish",
                        "source_title": mc["title"],
                        "target_id": uc["id"],
                        "target_lib": "user_kb",
                        "target_title": uc["title"],
                        "target_file": uc.get("file", ""),
                        "similarity": sim,
                        "relation": "auto_similar",
                        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })

        # 按相似度降序
        new_links.sort(key=lambda x: x["similarity"], reverse=True)

        # 合并保存
        if save and new_links:
            all_links = existing.get("links", []) + new_links
            self._save_links(all_links)

        return {
            "new_links": new_links,
            "total_links": len(existing.get("links", [])) + len(new_links),
            "mirofish_count": len(miro_cards),
            "user_kb_count": len(user_cards),
        }

    # ------------------------------------------------------------------
    # 查询链接
    # ------------------------------------------------------------------
    def get_links(self, lib, card_id):
        """
        获取某张卡片的所有跨库链接。

        参数:
            lib: "mirofish" 或 "user_kb"
            card_id: 卡片ID

        返回:
            [{"target_id", "target_lib", "target_title", "target_file",
              "similarity", "relation", "created"}, ...]
        """
        data = self._load_links()
        results = []
        for link in data.get("links", []):
            if link["source_lib"] == lib and link["source_id"] == card_id:
                results.append({
                    "target_id": link["target_id"],
                    "target_lib": link["target_lib"],
                    "target_title": link["target_title"],
                    "target_file": link.get("target_file", ""),
                    "similarity": link["similarity"],
                    "relation": link["relation"],
                    "created": link["created"],
                })
            elif link["target_lib"] == lib and link["target_id"] == card_id:
                results.append({
                    "target_id": link["source_id"],
                    "target_lib": link["source_lib"],
                    "target_title": link["source_title"],
                    "target_file": "",
                    "similarity": link["similarity"],
                    "relation": link["relation"],
                    "created": link["created"],
                })
        # 按相似度降序
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results

    def get_all_links(self):
        """获取全部链接"""
        data = self._load_links()
        return data.get("links", [])

    def get_stats(self):
        """交叉链接统计"""
        data = self._load_links()
        links = data.get("links", [])
        auto_count = sum(1 for l in links if l.get("relation") == "auto_similar")
        manual_count = sum(1 for l in links if l.get("relation") == "manual")
        return {
            "total_links": len(links),
            "auto_links": auto_count,
            "manual_links": manual_count,
            "last_discovery": data.get("last_discovery", ""),
        }

    # ------------------------------------------------------------------
    # 手动管理
    # ------------------------------------------------------------------
    def add_manual_link(self, source_lib, source_id, source_title,
                        target_lib, target_id, target_title, target_file=""):
        """手动添加一条跨库链接"""
        data = self._load_links()
        links = data.get("links", [])

        # 去重
        for l in links:
            if (l["source_id"] == source_id and l["target_id"] == target_id):
                return {"ok": False, "message": "链接已存在"}

        links.append({
            "source_id": source_id,
            "source_lib": source_lib,
            "source_title": source_title,
            "target_id": target_id,
            "target_lib": target_lib,
            "target_title": target_title,
            "target_file": target_file,
            "similarity": 1.0,
            "relation": "manual",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        self._save_links(links)
        return {"ok": True, "message": "链接已添加"}

    def remove_link(self, source_id, target_id):
        """删除一条链接"""
        data = self._load_links()
        links = data.get("links", [])
        new_links = [l for l in links
                     if not (l["source_id"] == source_id and l["target_id"] == target_id)]
        if len(new_links) == len(links):
            return {"ok": False, "message": "未找到该链接"}
        self._save_links(new_links)
        return {"ok": True, "message": "链接已删除"}

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------
    def _load_links(self):
        """加载链接数据"""
        if not os.path.isfile(CROSSLINKS_PATH):
            return {"version": "1.0", "links": [], "last_discovery": ""}
        try:
            with open(CROSSLINKS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return {"version": "1.0", "links": [], "last_discovery": ""}

    def _save_links(self, links):
        """保存链接数据（原子写入）"""
        data = {
            "version": "1.0",
            "description": "金水谣双库交叉链接（左脑MiroFish ↔ 右脑用户知识库）",
            "links": links,
            "last_discovery": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            from utils.safe_json import safe_write_json
            safe_write_json(CROSSLINKS_PATH, data)
        except ImportError:
            import tempfile
            tmp = CROSSLINKS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CROSSLINKS_PATH)


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------
_linker_instance = None

def get_linker():
    """获取全局交叉链接器单例"""
    global _linker_instance
    if _linker_instance is None:
        _linker_instance = CrossLinker()
    return _linker_instance
