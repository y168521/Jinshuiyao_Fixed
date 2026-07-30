# -*- coding: utf-8 -*-
"""P3-4 集成测试：手动重建语义向量索引端点 /api/knowledge/vector/rebuild。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest import mock

from server.handlers import knowledge as h_knowledge


class FakeHandler:
    """捕获 _send_json 输出的轻量 handler，支持本机守卫开关。"""

    def __init__(self, local=True):
        self.sent = None
        self.status = 200
        self._local = local

    def _send_json(self, payload, status=200):
        self.sent = payload
        self.status = status

    def _is_local(self):
        return self._local


def test_vector_rebuild_endpoint_returns_counts():
    h = FakeHandler(local=True)
    fake_idx = type("FakeIdx", (), {
        "doc_count": 7,
        "built_at": "2026-07-24 12:00:00",
        "source_mtime": 1234.5,
    })()
    with mock.patch("knowledge.vector_index.rebuild_vector_index", return_value=fake_idx):
        h_knowledge.handle_knowledge_vector_rebuild(h)
    assert h.status == 200
    assert h.sent["ok"] is True
    assert h.sent["doc_count"] == 7
    assert h.sent["built_at"] == "2026-07-24 12:00:00"
    assert h.sent["source_mtime"] == 1234.5


def test_vector_rebuild_endpoint_remote_forbidden():
    h = FakeHandler(local=False)
    h_knowledge.handle_knowledge_vector_rebuild(h)
    assert h.status == 403
    assert "error" in h.sent


def test_vector_rebuild_endpoint_propagates_error():
    h = FakeHandler(local=True)
    with mock.patch("knowledge.vector_index.rebuild_vector_index",
                    side_effect=RuntimeError("rebuild failed")):
        h_knowledge.handle_knowledge_vector_rebuild(h)
    assert h.status == 500
    assert "error" in h.sent


def test_router_registers_vector_rebuild_route():
    """router 应把 /api/knowledge/vector/rebuild 路由到对应 handler。"""
    try:
        import server.router as router_module
    except Exception as e:
        raise AssertionError("无法导入 router: %s" % e)

    # 检查路由源码中包含该路径分支（静态校验，避免启动整服务）
    source = open(router_module.__file__, "r", encoding="utf-8").read()
    assert "/api/knowledge/vector/rebuild" in source
    assert "handle_knowledge_vector_rebuild" in source
