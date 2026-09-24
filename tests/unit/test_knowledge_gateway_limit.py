# -*- coding: utf-8 -*-
"""知识网关 limit 参数回归测试（JS-20260925-01）

背景（真实缺陷，实测取证 2026-09-25）：`_bm25(query, docs, limit)` 的签名里
**有 limit 参数，但函数体从头到尾没用它** —— `return scored` 直接把全部
得分>0 的文档返回。实测：

    _bm25(docs=50, limit=1)  -> 返回 50 条   ← limit 被完全忽略
    search('彩票命中率', limit=1) -> total=328 条（本应约 5 条）

影响面：cards / triples / experiences 三个源全走 _bm25，只有 vectors 与
project_docs 遵守 limit。所以 API `/api/knowledge/gateway?limit=8` 实际返回
**约 40 倍**的数据量 —— 对 LLM 而言不是"召回更全"，而是噪声淹没 + 上下文爆炸。
`server/handlers/knowledge.py:225` 传 `_bm25(query, docs, 50)` 同样是受害者。

判定为真 bug（而非有意设计）的依据：函数签名明确声明 limit，且 5 个源中
2 个遵守、3 个不遵守 —— 行为不一致本身就是实现遗漏的证据。

本文件的价值：把「参数写了却不用」这类静默失效钉死。它不报错，只是在
调用方眼里"召回了好多知识"，实际是把噪声当召回。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def _docs(n, kw="彩票"):
    return [{"id": str(i), "text": "%s 命中 口径 内容%d" % (kw, i)} for i in range(n)]


class TestBm25RespectsLimit(unittest.TestCase):
    """_bm25 必须遵守 limit"""

    def test_limit_one(self):
        from core.infra.knowledge_gateway import _bm25
        res = _bm25("彩票", _docs(50), 1)
        self.assertEqual(len(res), 1, "_bm25 忽略了 limit 参数（应返回 1 条）")

    def test_limit_five(self):
        from core.infra.knowledge_gateway import _bm25
        res = _bm25("彩票", _docs(50), 5)
        self.assertEqual(len(res), 5)

    def test_limit_larger_than_docs(self):
        from core.infra.knowledge_gateway import _bm25
        res = _bm25("彩票", _docs(3), 50)
        self.assertEqual(len(res), 3, "文档不足时不应报错，返回全部即可")

    def test_limit_zero_or_none_returns_all(self):
        """limit=0/None 视为不限制（保持向后兼容，老调用方不受影响）"""
        from core.infra.knowledge_gateway import _bm25
        self.assertEqual(len(_bm25("彩票", _docs(20), 0)), 20)
        self.assertEqual(len(_bm25("彩票", _docs(20), None)), 20)

    def test_truncation_keeps_top_scores(self):
        """截断必须保留最相关的（按 score 降序取前 N），不能随机裁"""
        from core.infra.knowledge_gateway import _bm25
        docs = [{"id": "a", "text": "彩票 命中 率"},
                {"id": "b", "text": "彩票 命中 率 命中 率 命中 率"},
                {"id": "c", "text": "彩票"},
                {"id": "d", "text": "彩票 命中 率 口径 命中"}]
        top = _bm25("彩票 命中 率", docs, 2)
        self.assertEqual(len(top), 2)
        self.assertGreaterEqual(top[0]["score"], top[1]["score"], "未按相关度降序截断")


class TestSearchRespectsLimit(unittest.TestCase):
    """search() 各源都必须遵守 limit"""

    def test_all_sources_within_limit(self):
        from core.infra.knowledge_gateway import search
        r = search("彩票命中率", limit=2)
        for key in ("cards", "triples", "experiences", "project_docs"):
            got = len(r.get(key) or [])
            self.assertLessEqual(got, 2,
                                 "源 %s 返回 %d 条，超过 limit=2" % (key, got))

    def test_total_grows_with_limit(self):
        """limit 越大召回越多（证明确实受控，而不是恒返回全量）"""
        from core.infra.knowledge_gateway import search
        t1 = search("彩票命中率", limit=1).get("total", 0)
        t8 = search("彩票命中率", limit=8).get("total", 0)
        self.assertLess(t1, t8, "limit 未生效：1 与 8 的召回量相同")


if __name__ == "__main__":
    unittest.main()
