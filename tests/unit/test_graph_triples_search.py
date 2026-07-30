# -*- coding: utf-8 -*-
"""P3-1 单元：search_graph_triples 三元组检索（全来源，离线 fail-safe）"""
import os
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from knowledge.triple_store import _TRIPLE_STORE_PATH as _ts_path_attr
from knowledge.knowledge_search import search_graph_triples


class TestSearchGraphTriples(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _store(self, triples):
        path = os.path.join(self.tmp, "graph_triples.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "triples": triples, "sources": {}}, f, ensure_ascii=False)
        return path

    def test_match_subject(self):
        path = self._store([
            {"subject": "熔断", "predicate": "导致", "object": "源降权", "source": "经验收集箱.md"},
            {"subject": "缓存", "predicate": "提升", "object": "命中率", "source": "ai_decisions.md"},
        ])
        import knowledge.triple_store as ts_mod
        with patch.object(ts_mod, "_TRIPLE_STORE_PATH", path):
            res = search_graph_triples("熔断")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["subject"], "熔断")

    def test_source_filter(self):
        path = self._store([
            {"subject": "A", "predicate": "p", "object": "B", "source": "经验收集箱.md"},
            {"subject": "C", "predicate": "p", "object": "D", "source": "ai_decisions.md"},
        ])
        import knowledge.triple_store as ts_mod
        with patch.object(ts_mod, "_TRIPLE_STORE_PATH", path):
            res = search_graph_triples("p", source="ai_decisions.md")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["source"], "ai_decisions.md")

    def test_empty_query(self):
        path = self._store([{"subject": "x", "predicate": "y", "object": "z"}])
        import knowledge.triple_store as ts_mod
        with patch.object(ts_mod, "_TRIPLE_STORE_PATH", path):
            self.assertEqual(search_graph_triples("  "), [])

    def test_limit(self):
        triples = [{"subject": "缓存", "predicate": "p", "object": str(i), "source": "s"} for i in range(5)]
        path = self._store(triples)
        import knowledge.triple_store as ts_mod
        with patch.object(ts_mod, "_TRIPLE_STORE_PATH", path):
            res = search_graph_triples("缓存", limit=3)
        self.assertEqual(len(res), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
