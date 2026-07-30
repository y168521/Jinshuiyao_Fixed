# -*- coding: utf-8 -*-
"""P3-3 集成测试：标签校验端点 /api/knowledge/tags/validate。"""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest import mock

from server.handlers import knowledge as h_knowledge


class FakeHandler:
    def __init__(self):
        self.sent = None
        self.status = 200

    def _send_json(self, payload, status=200):
        self.sent = payload
        self.status = status


def _parsed(path):
    p = types.SimpleNamespace()
    p.path = path
    p.query = ""
    return p


FAKE_REPORT = {
    "ok": False,
    "total_entries": 73,
    "unknown_tags": ["魔法"],
    "violations": [{"type": "unknown_tag", "line": 100, "tag": "魔法", "title": "x"}],
}


def test_tags_validate_endpoint_returns_report():
    h = FakeHandler()
    with mock.patch("knowledge.tag_validator.validate_experience_tags",
                    return_value=FAKE_REPORT):
        h_knowledge.handle_knowledge_tags_validate(h, _parsed("/api/knowledge/tags/validate"))
    assert h.sent["ok"] is True
    assert "report" in h.sent
    assert h.sent["report"]["unknown_tags"] == ["魔法"]


def test_tags_validate_endpoint_ok_true():
    h = FakeHandler()
    with mock.patch("knowledge.tag_validator.validate_experience_tags",
                    return_value={"ok": True, "total_entries": 73,
                                   "unknown_tags": [], "violations": []}):
        h_knowledge.handle_knowledge_tags_validate(h, _parsed("/api/knowledge/tags/validate"))
    assert h.sent["report"]["ok"] is True
    assert h.sent["report"]["violations"] == []
