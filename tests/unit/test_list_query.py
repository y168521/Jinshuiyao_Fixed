# -*- coding: utf-8 -*-
"""utils/list_query.py 单测（JS-20261015-04，P0 检索层）。

刻意使用**模块级 test 函数**而非 class：`tools/code_health_gate.py` 的
`max_function_lines` 会把 class 体当成一个"函数"计数（已知口径缺陷），
包成 class 会凭空触发超阈值告警。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from utils.list_query import (  # noqa: E402
    QuerySpec, parse_query, apply_query, filter_records, sort_records,
    paginate, to_query_string, describe_filters, normalize_text,
    extract_numbers, numbers_match, keyword_hit, MAX_PAGE_SIZE,
)

FIELDS = ("lot", "period", "date", "nums", "type", "scheme")

SAMPLE = [
    {"lot": "双色球", "period": "2026116", "time": "2026-10-12 21:30:00",
     "nums": "01 02 03 04 05 06", "type": "综合", "scheme": "A",
     "confidence": 72.0, "hits": 3, "reviewed": True},
    {"lot": "大乐透", "period": "2026115", "time": "2026-10-10 21:25:00",
     "nums": "07 08 09 10 11 12", "type": "热号", "scheme": "B",
     "confidence": 65.0, "hits": 0, "reviewed": False},
    {"lot": "排列三", "period": "2026289", "time": "2026-10-11 20:30:00",
     "nums": "1 2 3", "type": "遗漏", "scheme": "A",
     "confidence": None, "hits": 1, "reviewed": True},
]


def test_normalize_basic():
    assert normalize_text("Hello World") == "helloworld"
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


def test_normalize_fullwidth_and_separators():
    # 全角数字 + 空格 + 逗号，归一后应完全一致
    assert normalize_text("０１ ０２") == normalize_text("01,02")


def test_extract_numbers():
    assert extract_numbers("01 02 03") == {"01", "02", "03"}
    assert extract_numbers("010203") == {"01", "02", "03"}


def test_numbers_match_ignores_separator_style():
    # 「01 02 03」与「010203」应互相命中
    assert numbers_match("01 02 03 04", "010203")
    assert numbers_match("07 08 09", "07,08")


def test_numbers_match_rejects_non_number_query():
    # 普通关键词不走号码比对
    assert numbers_match("01 02 03", "双色球") is False
    assert numbers_match("01 02 03", "abc") is False


def test_keyword_hit_number_formats():
    rec = {"lot": "双色球", "nums": "01 02 03 04 05 06", "period": "2026116"}
    assert keyword_hit(rec, "010203", ("nums",))
    assert keyword_hit(rec, "01,02,03", ("nums",))


def test_keyword_hit_plain_substring():
    rec = {"lot": "双色球"}
    assert keyword_hit(rec, "双色", ("lot",))
    assert keyword_hit(rec, "大乐透", ("lot",)) is False


def test_keyword_hit_empty_means_all():
    assert keyword_hit({"lot": "x"}, "", ("lot",))


def test_spec_is_empty():
    assert QuerySpec().is_empty() is True
    assert QuerySpec(q="a").is_empty() is False
    assert QuerySpec(lots=["双色球"]).is_empty() is False
    assert QuerySpec(date_from="2026-01-01").is_empty() is False


def test_parse_query_defaults():
    s = parse_query({})
    assert s.page == 1
    assert s.page_size == 50
    assert s.sort == "time"
    assert s.desc is True


def test_parse_query_clamps_bad_values():
    s = parse_query({"limit": "999999", "page": "-5"})
    assert s.page_size == MAX_PAGE_SIZE
    assert s.page == 1


def test_parse_query_tolerates_garbage():
    s = parse_query({"limit": "abc", "page": "xyz"})
    assert s.page_size == 50
    assert s.page == 1


def test_parse_query_lots_splitting():
    assert parse_query({"lot": "双色球,大乐透"}).lots == ["双色球", "大乐透"]
    assert parse_query({"lot": "双色球，大乐透"}).lots == ["双色球", "大乐透"]
    assert parse_query({"lot": "全部"}).lots == []


def test_filter_by_lot():
    spec = QuerySpec(lots=["双色球"])
    rows = filter_records(SAMPLE, spec, FIELDS)
    assert len(rows) == 1 and rows[0]["lot"] == "双色球"


def test_filter_by_date_range():
    spec = QuerySpec(date_from="2026-10-11", date_to="2026-10-12")
    rows = filter_records(SAMPLE, spec, FIELDS)
    assert len(rows) == 2


def test_filter_by_status_pending():
    spec = QuerySpec(status="待复盘")
    rows = filter_records(SAMPLE, spec, FIELDS)
    assert [r["lot"] for r in rows] == ["大乐透"]


def test_filter_by_status_hit_and_miss():
    hit = filter_records(SAMPLE, QuerySpec(status="命中"), FIELDS)
    miss = filter_records(SAMPLE, QuerySpec(status="未中"), FIELDS)
    assert len(hit) == 2 and len(miss) == 1


def test_sort_numeric_with_none_last():
    spec = QuerySpec(sort="sqi", desc=True)
    rows = sort_records(list(SAMPLE), spec)
    assert rows[0]["confidence"] == 72.0
    assert rows[-1]["confidence"] is None


def test_paginate_basic():
    data = [{"i": i} for i in range(120)]
    spec = QuerySpec(page=1, page_size=50)
    page, total, pages = paginate(data, spec)
    assert len(page) == 50 and total == 120 and pages == 3


def test_paginate_page_overflow_clamps():
    data = [{"i": i} for i in range(120)]
    spec = QuerySpec(page=99, page_size=50)
    page, total, pages = paginate(data, spec)
    assert len(page) == 20 and total == 120 and pages == 3


def test_apply_query_end_to_end():
    spec = parse_query({"lot": "排列三,双色球", "sort": "period", "order": "desc",
                        "page": 1, "limit": 10})
    page, total, pages = apply_query(SAMPLE, spec, FIELDS)
    assert total == 2 and pages == 1
    assert [r["period"] for r in page] == ["2026289", "2026116"]


def test_query_string_roundtrip():
    """条件 -> query 串 -> 条件，应可无损还原（刷新/分享后回显）。"""
    import urllib.parse
    spec = parse_query({'q': '双色球', 'lot': '双色球,大乐透', 'status': '命中'})
    qs = to_query_string(spec)
    # 模拟真实 HTTP 解析（parse_qs 会自动 percent-decode）
    again = parse_query(urllib.parse.parse_qs(qs))
    assert again.q == spec.q
    assert again.lots == spec.lots
    assert again.status == spec.status


def test_query_string_omits_empty():
    """空条件不进 URL，避免 ?q=&lot=&status= 这种噪音。"""
    assert to_query_string(QuerySpec()) == ''
    assert 'q=' not in to_query_string(QuerySpec(status='待复盘'))


def test_describe_filters_chips():
    spec = parse_query({"q": "abc", "lot": "双色球", "status": "待复盘",
                        "date_from": "2026-01-01"})
    chips = describe_filters(spec)
    assert len(chips) == 4
    assert {c["key"] for c in chips} == {"q", "lot", "status", "date"}
