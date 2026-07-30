# -*- coding: utf-8 -*-
"""
金水谣知识引擎 - 三层渐进增强架构
====================================
Layer 0: 本地知识层（永远可用）- SQLite FTS5 全文检索
Layer 1: 联网抓取层（有网时）- 抓取新来源补充索引
Layer 2: API增强层（有密钥+有网时）- 语义重排、摘要生成

设计原则：
  - 纯标准库，零第三方依赖
  - 自动检测能力，无需用户手动切换模式
  - 每层增强下层，不替代
  - 本地数据为唯一真相源（Local-First）
"""
import os
import re
import json
import sqlite3
import socket
import hashlib
import logging
import threading
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE_DIR = os.path.join(BASE_DIR, "knowledge")
USER_KB_DIR = os.path.join(KNOWLEDGE_DIR, "用户知识库")
MIROFISH_DB_PATH = os.path.join(KNOWLEDGE_DIR, "mirofish_db.json")
KB_INDEX_DB = os.path.join(KNOWLEDGE_DIR, "kb_index.db")
CONFIG_DIR = os.path.join(BASE_DIR, "config")

# ---------------------------------------------------------------------------
# 能力检测
# ---------------------------------------------------------------------------
class CapabilityDetector:
    """检测当前环境可用的能力层"""

    _network_cache = None
    _network_cache_time = 0
    _CACHE_TTL = 30  # 秒

    @classmethod
    def detect(cls):
        """返回可用能力字典 {local, network, api}"""
        return {
            "local": True,  # 永远可用
            "network": cls._check_network(),
            "api": cls._check_api_key(),
        }

    @classmethod
    def _check_network(cls):
        """检测网络连接（带缓存）"""
        now = datetime.now().timestamp()
        if cls._network_cache is not None and (now - cls._network_cache_time) < cls._CACHE_TTL:
            return cls._network_cache
        try:
            sock = socket.create_connection(("223.5.5.5", 53), timeout=2)
            sock.close()
            cls._network_cache = True
        except (OSError, socket.timeout):
            cls._network_cache = False
        cls._network_cache_time = now
        return cls._network_cache

    @classmethod
    def _check_api_key(cls):
        """检测是否有可用的API密钥（复用 core.ai_service 统一入口）"""
        try:
            from core.ai_service import get_api_key
            return bool(get_api_key())
        except Exception:
            return False

    @classmethod
    def invalidate_cache(cls):
        """强制刷新网络缓存（网络调用失败时调用）"""
        cls._network_cache = None
        cls._network_cache_time = 0


# ---------------------------------------------------------------------------
# 中文分词工具（纯标准库，二元切分）
# ---------------------------------------------------------------------------
def tokenize_chinese(text):
    """
    中文二元切分 + 英文单词切分。
    纯标准库实现，不依赖jieba。
    """
    if not text:
        return []
    tokens = []
    # 提取英文单词和数字
    en_words = re.findall(r'[a-zA-Z0-9_]+', text)
    tokens.extend(w.lower() for w in en_words)
    # 提取中文字符序列，做二元切分
    cn_segments = re.findall(r'[\u4e00-\u9fff]+', text)
    for seg in cn_segments:
        # 单字也保留
        for ch in seg:
            tokens.append(ch)
        # 二元组
        for i in range(len(seg) - 1):
            tokens.append(seg[i:i+2])
    return tokens


def tokenize_for_fts(text):
    """将文本转为FTS5可索引的格式（空格分隔的token）"""
    tokens = tokenize_chinese(text)
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# Layer 0: 本地知识层（SQLite FTS5）
# ---------------------------------------------------------------------------
class LocalKnowledgeLayer:
    """
    本地全文检索层 - 永远可用。
    索引来源：MiroFish DB卡片 + 用户知识库Markdown + 经验收集箱
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or KB_INDEX_DB
        self._conn = None
        # 数据库操作锁：本引擎会被调度器/监听器/HTTP等多个线程并发调用，
        # 使用可重入锁(RLock)序列化数据库读写，避免并发写入冲突。
        self._lock = threading.RLock()
        self._ensure_schema()

    def _get_conn(self):
        if self._conn is None:
            # check_same_thread=False 允许连接在创建它的线程之外使用，
            # 线程安全由 self._lock 保证。
            self._conn = sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self):
        with self._lock:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS kb_docs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    domain TEXT DEFAULT '',
                    tags TEXT DEFAULT '',
                    layer TEXT DEFAULT 'local',
                    created TEXT DEFAULT '',
                    updated TEXT DEFAULT '',
                    effectiveness INTEGER DEFAULT 50
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
                    title, content, tags,
                    content='kb_docs',
                    content_rowid='rowid',
                    tokenize='unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS kb_ai AFTER INSERT ON kb_docs BEGIN
                    INSERT INTO kb_fts(rowid, title, content, tags)
                    VALUES (new.rowid, new.title, new.content, new.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS kb_ad AFTER DELETE ON kb_docs BEGIN
                    INSERT INTO kb_fts(kb_fts, rowid, title, content, tags)
                    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS kb_au AFTER UPDATE ON kb_docs BEGIN
                    INSERT INTO kb_fts(kb_fts, rowid, title, content, tags)
                    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
                    INSERT INTO kb_fts(rowid, title, content, tags)
                    VALUES (new.rowid, new.title, new.content, new.tags);
                END;
                CREATE TABLE IF NOT EXISTS kb_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            conn.commit()

    def index_all(self):
        """重建索引：从所有知识源导入"""
        count = 0
        count += self._index_mirofish()
        count += self._index_user_kb()
        count += self._index_experience_box()
        # 记录索引时间
        self._set_meta("last_index", datetime.now().isoformat())
        self._set_meta("doc_count", str(count))
        logger.info("知识库索引完成: %d 篇文档", count)
        return count

    def _index_mirofish(self):
        """索引 MiroFish DB 的93张卡片"""
        if not os.path.isfile(MIROFISH_DB_PATH):
            return 0
        try:
            with open(MIROFISH_DB_PATH, "r", encoding="utf-8") as f:
                db = json.load(f)
        except Exception:
            return 0

        cards = db.get("cards", [])
        conn = self._get_conn()
        count = 0
        with self._lock:
            for card in cards:
                doc_id = f"miro_{card.get('id', '')}"
                tags_str = " ".join(card.get("tags", []))
                conn.execute("""
                    INSERT OR REPLACE INTO kb_docs
                    (id, title, content, source, category, domain, tags, effectiveness, created, updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id,
                    card.get("title", ""),
                    card.get("content", ""),
                    card.get("source", ""),
                    card.get("category", ""),
                    card.get("domain", ""),
                    tags_str,
                    card.get("effectiveness", 50),
                    card.get("created", ""),
                    card.get("updated", ""),
                ))
                count += 1
            conn.commit()
        return count

    def _index_user_kb(self):
        """索引用户知识库的Markdown卡片"""
        if not os.path.isdir(USER_KB_DIR):
            return 0
        conn = self._get_conn()
        count = 0
        with self._lock:
            for fname in os.listdir(USER_KB_DIR):
                if not fname.endswith(".md"):
                    continue
                if fname in ("README.md", "schema.md", "索引.md"):
                    continue
                fpath = os.path.join(USER_KB_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    # 提取标题（第一个#行）
                    title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                    title = title_match.group(1) if title_match else fname
                    # 提取tags
                    tags_match = re.search(r'tags:\s*\[(.+?)\]', content)
                    tags = tags_match.group(1) if tags_match else ""
                    doc_id = f"ukb_{hashlib.md5(fname.encode()).hexdigest()[:8]}"
                    conn.execute("""
                        INSERT OR REPLACE INTO kb_docs
                        (id, title, content, source, category, domain, tags, created)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (doc_id, title, content, "用户知识库", "concept", "general", tags,
                          datetime.now().isoformat()))
                    count += 1
                except Exception:
                    continue
            conn.commit()
        return count

    def _index_experience_box(self):
        """索引经验收集箱"""
        exp_path = os.path.join(BASE_DIR, "金水谣数据", "log", "经验收集箱.md")
        if not os.path.isfile(exp_path):
            return 0
        try:
            with open(exp_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return 0

        # 按 ### 分割为独立经验条目
        entries = re.split(r'\n###\s+', content)
        conn = self._get_conn()
        count = 0
        with self._lock:
            for i, entry in enumerate(entries[1:], 1):  # 跳过文件头
                lines = entry.strip().split("\n")
                title = lines[0] if lines else f"经验{i}"
                doc_id = f"exp_{hashlib.md5(title.encode()).hexdigest()[:8]}"
                conn.execute("""
                    INSERT OR REPLACE INTO kb_docs
                    (id, title, content, source, category, domain, tags, created)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (doc_id, title, entry, "经验收集箱", "skill", "general",
                      "经验 踩坑 修复", datetime.now().isoformat()))
                count += 1
            conn.commit()
        return count

    def search(self, query, limit=10):
        """
        混合检索：LIKE模糊匹配（中文可靠）+ FTS5加权（英文精确）。
        返回 [{id, title, content, source, category, score}]
        """
        conn = self._get_conn()
        if not query or not query.strip():
            return []

        # 策略：LIKE为主（中文友好），多关键词AND匹配提高精度
        keywords = [w for w in re.split(r'[\s,，、/]+', query.strip()) if len(w) >= 1]
        if not keywords:
            keywords = [query.strip()]

        # 构建多关键词LIKE查询（所有关键词都要命中）
        conditions = []
        params = []
        for kw in keywords[:6]:  # 最多6个关键词
            conditions.append("(title LIKE ? OR content LIKE ? OR tags LIKE ?)")
            like_pat = f"%{kw}%"
            params.extend([like_pat, like_pat, like_pat])

        where_clause = " AND ".join(conditions)
        sql = f"SELECT * FROM kb_docs WHERE {where_clause} LIMIT ?"
        params.append(limit * 2)  # 多取一些用于排序

        with self._lock:
            try:
                # sql 由内部字段名拼接、用户输入经 params 占位符参数化传入，无注入风险（semgrep sqlalchemy-execute-raw-query 误报）
                rows = conn.execute(sql, params).fetchall()  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
            except Exception:
                # 最终降级：单关键词
                rows = conn.execute(
                    "SELECT * FROM kb_docs WHERE title LIKE ? OR content LIKE ? LIMIT ?",
                    (f"%{query}%", f"%{query}%", limit)).fetchall()

        # 计算相关度评分
        results = []
        query_lower = query.lower()
        for row in rows:
            score = 0
            title = row["title"] or ""
            content = row["content"] or ""
            tags = row["tags"] or ""

            # 标题命中权重最高
            for kw in keywords:
                if kw in title:
                    score += 10
                if kw in tags:
                    score += 5
                if kw in content:
                    score += 2

            # 完整查询命中加分
            if query_lower in title.lower():
                score += 20
            if query_lower in content.lower():
                score += 5

            # effectiveness加权
            score += (row["effectiveness"] or 50) / 50

            results.append({
                "id": row["id"],
                "title": title,
                "content": content[:500],
                "source": row["source"],
                "category": row["category"],
                "domain": row["domain"],
                "score": score,
                "layer": "local",
            })

        # 按分数降序排列
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def get_stats(self):
        """获取索引统计"""
        conn = self._get_conn()
        with self._lock:
            try:
                count = conn.execute("SELECT COUNT(*) FROM kb_docs").fetchone()[0]
                last_index = self._get_meta("last_index")
                by_category = conn.execute(
                    "SELECT category, COUNT(*) as cnt FROM kb_docs GROUP BY category"
                ).fetchall()
                return {
                    "total_docs": count,
                    "last_index": last_index,
                    "by_category": {r["category"]: r["cnt"] for r in by_category},
                }
            except Exception:
                return {"total_docs": 0, "last_index": None, "by_category": {}}

    def _set_meta(self, key, value):
        with self._lock:
            self._get_conn().execute(
                "INSERT OR REPLACE INTO kb_meta (key, value) VALUES (?, ?)", (key, value))
            self._get_conn().commit()

    def _get_meta(self, key):
        with self._lock:
            row = self._get_conn().execute(
                "SELECT value FROM kb_meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None


# ---------------------------------------------------------------------------
# Layer 1: 联网抓取层
# ---------------------------------------------------------------------------
class _TextExtractor(HTMLParser):
    """从HTML中提取纯文本"""
    def __init__(self):
        super().__init__()
        self._texts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self._texts.append(text)

    def get_text(self):
        return "\n".join(self._texts)


class WebScrapeLayer:
    """
    联网抓取层 - 有网时可用。
    抓取网页内容，提取文本，索引到本地。
    """

    TIMEOUT = 10
    MAX_CONTENT_LEN = 50000  # 最大抓取长度

    def fetch_and_index(self, url, local_layer):
        """
        抓取URL内容并索引到本地层。
        返回 {success, title, doc_id, error}
        """
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JinshuiyaoKB/1.0"
            })
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                html = resp.read(self.MAX_CONTENT_LEN).decode("utf-8", errors="replace")

            # 提取文本
            parser = _TextExtractor()
            parser.feed(html)
            text = parser.get_text()

            if len(text) < 50:
                return {"success": False, "error": "页面内容太少，可能抓取失败"}

            # 提取标题
            title_match = re.search(r'<title[^>]*>(.+?)</title>', html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else url

            # 生成文档ID（URL哈希）
            doc_id = f"web_{hashlib.md5(url.encode()).hexdigest()[:12]}"

            # 索引到本地（使用本地层的锁，保证跨线程写入串行化）
            conn = local_layer._get_conn()
            with local_layer._lock:
                conn.execute("""
                    INSERT OR REPLACE INTO kb_docs
                    (id, title, content, source, category, domain, tags, layer, created)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (doc_id, title, text[:20000], url, "resource", "general",
                      "联网抓取", "web", datetime.now().isoformat()))
                conn.commit()

            return {"success": True, "title": title, "doc_id": doc_id}

        except Exception as e:
            CapabilityDetector.invalidate_cache()
            return {"success": False, "error": str(e)}

    def search_web(self, query, limit=3):
        """
        简单的网络搜索（通过公开搜索API）。
        返回 [{title, url, snippet}]
        """
        # 使用 DuckDuckGo HTML 接口（无需API密钥）
        try:
            encoded_q = urllib.parse.quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            })
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                html = resp.read(100000).decode("utf-8", errors="replace")

            # 提取搜索结果
            results = []
            # DuckDuckGo HTML结果格式
            pattern = r'<a rel="nofollow" class="result__a" href="(.+?)">(.+?)</a>'
            matches = re.findall(pattern, html)
            for link, title in matches[:limit]:
                # 清理HTML标签
                clean_title = re.sub(r'<[^>]+>', '', title)
                results.append({
                    "title": clean_title,
                    "url": link,
                    "snippet": "",
                })
            return results
        except Exception as e:
            CapabilityDetector.invalidate_cache()
            logger.debug("网络搜索失败: %s", e)
            return []


# ---------------------------------------------------------------------------
# Layer 2: API增强层
# ---------------------------------------------------------------------------
class APIEnhanceLayer:
    """
    API增强层 - 有密钥+有网时可用。
    复用 core.ai_service（连接池/熔断/重试/token追踪/对话日志）。
    """

    def __init__(self):
        self._ai = None

    def _get_ai(self):
        if self._ai is not None:
            return self._ai
        try:
            from core.ai_service import AIService
            self._ai = AIService()
        except Exception:
            self._ai = False
        return self._ai

    def rerank_and_summarize(self, query, local_results, max_tokens=800):
        """
        用LLM对本地结果做智能重排和摘要。
        返回 {answer, sources, enhanced}
        """
        ai = self._get_ai()
        if not ai or not getattr(ai, 'api_key', None):
            return {"answer": "", "sources": [], "enhanced": False}

        context_parts = []
        for i, r in enumerate(local_results[:5], 1):
            context_parts.append(f"[{i}] {r['title']}\n{r['content'][:300]}")
        context = "\n\n".join(context_parts)

        system_prompt = "你是金水谣知识库助手。根据检索结果回答用户问题。如果检索结果不足以回答，请如实说明。请用中文简洁回答（200字内），并标注引用了哪些来源编号。"
        user_prompt = f"检索结果：\n{context}\n\n用户问题：{query}"

        try:
            answer = ai.chat(system_prompt, user_prompt, temperature=0.3, max_tokens=max_tokens)
            if not answer:
                CapabilityDetector.invalidate_cache()
                return {"answer": "", "sources": [], "enhanced": False}
            return {
                "answer": answer,
                "sources": [r["title"] for r in local_results[:5]],
                "enhanced": True,
            }
        except Exception as e:
            CapabilityDetector.invalidate_cache()
            logger.debug("API增强失败: %s", e)
            return {"answer": "", "sources": [], "enhanced": False}


# ---------------------------------------------------------------------------
# 统一入口：知识引擎
# ---------------------------------------------------------------------------
class KnowledgeEngine:
    """
    金水谣知识引擎 - 统一检索接口。
    自动检测能力层，渐进增强，优雅降级。

    用法：
        engine = KnowledgeEngine()
        results = engine.query("什么是位置感知")
        # results = {answer, items, layers_used, stats}
    """

    def __init__(self, auto_index=True):
        self.local = LocalKnowledgeLayer()
        self.web = WebScrapeLayer()
        self.api = APIEnhanceLayer()
        self._caps = None

        # 首次使用时自动建索引（如果索引为空）
        if auto_index:
            stats = self.local.get_stats()
            if stats["total_docs"] == 0:
                self.local.index_all()

    @property
    def capabilities(self):
        if self._caps is None:
            self._caps = CapabilityDetector.detect()
        return self._caps

    def refresh_capabilities(self):
        """强制刷新能力检测"""
        CapabilityDetector.invalidate_cache()
        self._caps = CapabilityDetector.detect()
        return self._caps

    def query(self, question, limit=8, use_web=False, use_api=True):
        """
        统一检索接口。

        参数:
            question: 用户问题
            limit: 返回结果数
            use_web: 是否启用联网抓取补充（Layer 1）
            use_api: 是否启用API增强（Layer 2）

        返回:
            {
                "answer": str,       # API生成的综合回答（Layer 2可用时）
                "items": [...],      # 检索结果列表
                "layers_used": [...],# 实际使用了哪些层
                "stats": {...},      # 统计信息
            }
        """
        caps = self.capabilities
        layers_used = ["local"]
        all_results = []

        # Layer 0: 本地检索（永远执行）
        local_results = self.local.search(question, limit=limit)
        all_results.extend(local_results)

        # Layer 1: 联网抓取（可选，需要用户触发或配置）
        if use_web and caps["network"]:
            layers_used.append("web")
            web_results = self.web.search_web(question, limit=3)
            for wr in web_results:
                all_results.append({
                    "id": f"web_{hashlib.md5(wr['url'].encode()).hexdigest()[:8]}",
                    "title": wr["title"],
                    "content": wr.get("snippet", ""),
                    "source": wr["url"],
                    "category": "web",
                    "score": 0,
                    "layer": "web",
                })

        # Layer 2: API增强（默认启用，有密钥+有网时）
        answer = ""
        if use_api and caps["api"] and caps["network"] and local_results:
            layers_used.append("api")
            api_result = self.api.rerank_and_summarize(question, local_results)
            if api_result["enhanced"]:
                answer = api_result["answer"]

        return {
            "answer": answer,
            "items": all_results[:limit],
            "layers_used": layers_used,
            "stats": {
                "local_count": len(local_results),
                "total_count": len(all_results),
                "capabilities": caps,
            },
        }

    def ingest_url(self, url):
        """抓取URL并索引到本地知识库（Layer 1功能）"""
        if not self.capabilities["network"]:
            return {"success": False, "error": "当前无网络连接"}
        return self.web.fetch_and_index(url, self.local)

    def reindex(self):
        """重建全部索引"""
        return self.local.index_all()

    def get_status(self):
        """获取引擎状态"""
        return {
            "capabilities": self.capabilities,
            "index_stats": self.local.get_stats(),
            "mode_description": self._describe_mode(),
        }

    def _describe_mode(self):
        caps = self.capabilities
        if caps["api"] and caps["network"]:
            return "完整模式（本地+联网+API增强）"
        elif caps["network"]:
            return "联网模式（本地+网页抓取）"
        else:
            return "离线模式（纯本地检索）"

    def close(self):
        self.local.close()


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------
_engine_instance = None

def get_engine():
    """获取全局知识引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = KnowledgeEngine()
    return _engine_instance


def query_knowledge(question, **kwargs):
    """便捷查询函数"""
    return get_engine().query(question, **kwargs)


# ---------------------------------------------------------------------------
# 命令行入口（手动测试）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    print("=" * 50)
    print("  金水谣知识引擎 v1.0")
    print("=" * 50)

    engine = KnowledgeEngine()
    status = engine.get_status()
    print(f"\n  运行模式: {status['mode_description']}")
    print(f"  索引文档: {status['index_stats']['total_docs']} 篇")
    print(f"  能力检测: {status['capabilities']}")

    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        print(f"\n  查询: {q}")
        print("-" * 50)
        result = engine.query(q)
        if result["answer"]:
            print(f"\n  AI回答: {result['answer']}")
        print(f"\n  检索结果 ({len(result['items'])} 条):")
        for i, item in enumerate(result["items"], 1):
            print(f"    {i}. [{item['layer']}] {item['title']}")
            print(f"       来源: {item['source']}")
        print(f"\n  使用层: {result['layers_used']}")
    else:
        print("\n  用法: python kb_engine.py <查询内容>")
        print("  示例: python kb_engine.py 位置感知是什么")

    engine.close()
