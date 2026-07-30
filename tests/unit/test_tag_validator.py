# -*- coding: utf-8 -*-
"""P3-3 单元测试：经验箱标签校验器（knowledge.tag_validator）。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from knowledge import tag_validator as tv


def test_extract_entries_parses_title_tags():
    text = (
        "### 2026-07-24（WorkBuddy）示例条目 · JS-X [后端][测试]\n"
        "### 2026-07-24 另一条 [架构]\n"
    )
    entries = tv.extract_entries(text)
    assert len(entries) == 2
    assert entries[0]["tags"] == ["后端", "测试"]
    assert entries[1]["tags"] == ["架构"]
    assert entries[0]["line"] == 1


def test_extract_index_categories():
    text = (
        "### 🏗️ 架构类（[架构]）\n- x\n"
        "### 🔧 后端类（[后端]）\n- x\n"
    )
    cats = tv.extract_index_categories(text)
    assert cats == {"架构": "### 🏗️ 架构类（[架构]）", "后端": "### 🔧 后端类（[后端]）"}


def test_validate_whitelist_flags_unknown():
    entries = [{"line": 1, "title": "t", "tags": ["魔法"]}]
    v = tv.validate_whitelist(entries)
    assert len(v) == 1
    assert v[0]["type"] == "unknown_tag"
    assert v[0]["tag"] == "魔法"


def test_validate_count():
    entries = [
        {"line": 1, "title": "无标签", "tags": []},
        {"line": 2, "title": "多标签", "tags": ["后端", "前端", "测试", "安全"]},
        {"line": 3, "title": "正常", "tags": ["后端"]},
    ]
    v = tv.validate_count(entries)
    types = [x["type"] for x in v]
    assert "no_tag" in types
    assert "too_many_tags" in types
    assert len(v) == 2


def test_validate_format_missing_title_tag():
    entries = [{"line": 5, "title": "标题无标签格式", "tags": []}]
    v = tv.validate_format(entries)
    assert v[0]["type"] == "missing_title_tag"


def test_validate_consistency_ok():
    text = (
        "### 🏗️ 架构类（[架构]）\n- x\n"
        "### 🔧 后端类（[后端]）\n- x\n"
        "### 🎨 前端类（[前端]）\n- x\n"
        "### 🧪 测试类（[测试]）\n- x\n"
        "### 🤝 协作类（[协作]）\n- x\n"
        "### 🚀 运维类（[运维]）\n- x\n"
        "### 🔒 安全类（[安全]）\n- x\n"
        "### 💡 最佳实践（[最佳实践]）\n- x\n"
        "### 2026-07-24 经验 [架构][后端]\n"
    )
    entries = tv.extract_entries(text)
    v = tv.validate_consistency(entries, text)
    assert v == []


def test_validate_consistency_missing_and_empty_category():
    text = (
        "### 🔧 后端类（[后端]）\n- x\n"
        "### 2026-07-24 经验 [架构]\n"
    )
    entries = tv.extract_entries(text)
    v = tv.validate_consistency(entries, text)
    assert any(x["type"] == "missing_index_category" and x["tag"] == "架构" for x in v)
    assert any(x["type"] == "empty_index_category" for x in v)


def test_validate_experience_tags_full_report(tmp_path):
    sample = (
        "# 经验收集箱\n"
        "### 🏗️ 架构类（[架构]）\n- x\n"
        "### 🔧 后端类（[后端]）\n- x\n"
        "### 🎨 前端类（[前端]）\n- x\n"
        "### 🧪 测试类（[测试]）\n- x\n"
        "### 🤝 协作类（[协作]）\n- x\n"
        "### 🚀 运维类（[运维]）\n- x\n"
        "### 🔒 安全类（[安全]）\n- x\n"
        "### 💡 最佳实践（[最佳实践]）\n- x\n"
        "### 2026-07-24 正常 [架构][后端]\n"
        "### 2026-07-24 自创标签 [魔法]\n"
        "### 2026-07-24 过多 [后端][前端][测试][安全]\n"
        "### 2026-07-24 无标签\n"
    )
    p = tmp_path / "经验收集箱.md"
    p.write_text(sample, encoding="utf-8")
    report = tv.validate_experience_tags(str(p))
    assert report["ok"] is False
    assert report["total_entries"] >= 12
    assert "魔法" in report["unknown_tags"]
    assert any(x["type"] == "too_many_tags" for x in report["violations"])
    assert any(x["type"] == "no_tag" for x in report["violations"])
