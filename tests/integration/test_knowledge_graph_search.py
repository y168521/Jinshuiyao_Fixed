# -*- coding: utf-8 -*-
"""P3-1 集成：知识检索端点并入图谱三元组（/api/knowledge/search + /api/knowledge/graph/search）"""
import os
import sys
import urllib.parse
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from server.handlers import knowledge as hk


class FakeHandler:
    def __init__(self, path):
        self.path = path
        self.headers = {"Content-Length": "0"}
        self.sent = None

    def _send_json(self, data, code=200):
        self.sent = (code, data)

    def _is_local(self):
        return True

    def _is_safe_http_url(self, url):
        return True, "ok"


class TestKgSearchEndpoint(unittest.TestCase):
    def test_kg_search_returns_triples(self):
        fake = [{"subject": "熔断", "predicate": "导致", "object": "源降权", "source": "经验收集箱.md"}]
        with patch("core.auto_knowledge.search_graph_triples", return_value=fake):
            h = FakeHandler("/api/knowledge/graph/search?q=熔断")
            hk.handle_kg_search(h, urllib.parse.urlparse(h.path))
        code, data = h.sent
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["triples"][0]["subject"], "熔断")

    def test_kg_search_missing_q(self):
        h = FakeHandler("/api/knowledge/graph/search")
        hk.handle_kg_search(h, urllib.parse.urlparse(h.path))
        code, data = h.sent
        self.assertEqual(code, 400)
        self.assertIn("q", data["error"])

    def test_knowledge_search_includes_triples(self):
        fake = [{"subject": "缓存", "predicate": "提升", "object": "命中率", "source": "s"}]
        with patch("core.auto_knowledge.search_graph_triples", return_value=fake):
            with patch("knowledge.mirofish_db.MiroFishDB") as MockDB:
                MockDB.return_value.search.return_value = [{"title": "缓存命中率说明"}]
                h = FakeHandler("/api/knowledge/search?q=缓存")
                hk.handle_knowledge_search(h, urllib.parse.urlparse(h.path))
        code, data = h.sent
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["triples"][0]["subject"], "缓存")


if __name__ == "__main__":
    unittest.main(verbosity=2)
