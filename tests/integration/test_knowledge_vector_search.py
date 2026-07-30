# -*- coding: utf-8 -*-
"""P3-2 集成测试：知识搜索 handler 并入向量召回 + 专用向量检索端点。"""
import sys
import os
import json
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest import mock

from server.handlers import knowledge as h_knowledge


class FakeHandler:
    """捕获 _send_json 输出的轻量 handler。"""

    def __init__(self):
        self.sent = None
        self.status = 200

    def _send_json(self, payload, status=200):
        self.sent = payload
        self.status = status


def _parsed(path):
    p = types.SimpleNamespace()
    p.path = path
    from urllib.parse import urlparse
    p.query = urlparse(path).query if "?" in path else ""
    return p


FAKE_VECTORS = [
    {"id": "v1", "title": "价值投资", "snippet": "长期持有", "score": 0.42, "domain": "stock", "tags": ["股票"]},
]


def test_knowledge_search_includes_vectors():
    h = FakeHandler()
    with mock.patch("core.auto_knowledge.search_knowledge_vector", return_value=FAKE_VECTORS), \
         mock.patch("core.auto_knowledge.search_graph_triples", return_value=[]), \
         mock.patch("knowledge.mirofish_db.MiroFishDB") as mdb:
        mdb.return_value.search.return_value = [{"id": "r1", "title": "x"}]
        h_knowledge.handle_knowledge_search(h, _parsed("/api/knowledge/search?q=投资"))
    assert h.sent["ok"] is True
    assert "vectors" in h.sent
    assert h.sent["vectors"] == FAKE_VECTORS
    assert "triples" in h.sent


def test_vector_search_endpoint_returns_vectors():
    h = FakeHandler()
    with mock.patch("core.auto_knowledge.search_knowledge_vector", return_value=FAKE_VECTORS):
        h_knowledge.handle_knowledge_vector_search(h, _parsed("/api/knowledge/vector/search?q=投资"))
    assert h.sent["ok"] is True
    assert h.sent["vectors"] == FAKE_VECTORS
    assert h.sent["total"] == 1
    assert h.sent["query"] == "投资"


def test_vector_search_missing_q_returns_400():
    h = FakeHandler()
    h_knowledge.handle_knowledge_vector_search(h, _parsed("/api/knowledge/vector/search"))
    assert h.status == 400
    assert "error" in h.sent


def test_vector_search_passes_limit_and_min_score():
    h = FakeHandler()
    with mock.patch("core.auto_knowledge.search_knowledge_vector",
                    return_value=[]) as vs:
        h_knowledge.handle_knowledge_vector_search(
            h, _parsed("/api/knowledge/vector/search?q=投资&limit=5&min_score=0.05"))
    vs.assert_called_once_with("投资", limit=5, min_score=0.05)
