# -*- coding: utf-8 -*-
"""彩票预测列表查询单测（JS-20261015-04，P0）。

隔离方式：用临时文件顶掉 `prediction._LOT_PREDICTION_FILE`，
不依赖会随时间增长的 `金水谣数据/predictions.json`，保证可重复。
"""

import io
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from server.handlers import prediction as P  # noqa: E402

SAMPLE = [
    {"lot": "快乐8", "period": "2026288", "time": "2026-10-12 21:30:00",
     "nums": "01 02 03 04 05 06", "type": "综合", "scheme": "A",
     "confidence": 72.0, "hits": 3, "reviewed": True},
    {"lot": "大乐透", "period": "2026115", "time": "2026-10-10 21:25:00",
     "nums": "07 08 09 10 11 12", "type": "热号", "scheme": "B",
     "confidence": 65.0, "hits": 0, "reviewed": False},
    {"lot": "快乐8", "period": "2026287", "time": "2026-10-11 20:30:00",
     "nums": "11 12 13", "type": "遗漏", "scheme": "A",
     "confidence": None, "hits": 1, "reviewed": True},
]


class _FakeRFile(object):
    def __init__(self, payload):
        self._p = payload

    def read(self, n=0):
        return self._p


class _FakeHandler(object):
    """仅实现 handler 实际用到的接口（读 body / 回 JSON / 本机判定）。"""

    def __init__(self, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = _FakeRFile(raw)
        self.sent = None

    def _send_json(self, obj, code=200):
        self.sent = (code, obj)

    def _is_local(self):
        return True


def _with_tmp(data):
    """上下文：把 _LOT_PREDICTION_FILE 临时指向 tmp，退出后还原并删文件。"""
    import contextlib
    import tempfile

    @contextlib.contextmanager
    def _ctx():
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        old = P._LOT_PREDICTION_FILE
        P._LOT_PREDICTION_FILE = path
        try:
            yield path
        finally:
            P._LOT_PREDICTION_FILE = old
            try:
                os.remove(path)
            except OSError:
                pass

    return _ctx()


def test_query_lottery_filter_by_lot():
    with _with_tmp(SAMPLE) as _:
        spec = P.parse_query({"lot": "快乐8"})
        r = P.query_lottery_predictions(spec)
        assert r["ok"] is True
        assert r["total"] == 2
        assert {x["lot"] for x in r["records"]} == {"快乐8"}


def test_query_lottery_keyword_on_period():
    with _with_tmp(SAMPLE) as _:
        spec = P.parse_query({"q": "2026115"})
        r = P.query_lottery_predictions(spec)
        assert r["total"] == 1
        assert r["records"][0]["lot"] == "大乐透"


def test_query_lottery_keyword_on_numbers_ignores_separators():
    with _with_tmp(SAMPLE) as _:
        # 库里存的是 "07 08 09 10 11 12"，用无空格写法也应能搜到
        spec = P.parse_query({"q": "070809"})
        r = P.query_lottery_predictions(spec)
        assert r["total"] == 1
        assert r["records"][0]["lot"] == "大乐透"


def test_query_lottery_sort_by_sqi_desc():
    with _with_tmp(SAMPLE) as _:
        spec = P.parse_query({"sort": "sqi", "order": "desc"})
        r = P.query_lottery_predictions(spec)
        vals = [x.get("confidence") for x in r["records"]]
        assert vals[0] == 72.0
        assert vals[-1] is None       # 缺失值恒排最后


def test_query_lottery_pagination():
    with _with_tmp(SAMPLE) as _:
        p1 = P.query_lottery_predictions(P.parse_query({"page": 1, "limit": 2}))
        p2 = P.query_lottery_predictions(P.parse_query({"page": 2, "limit": 2}))
        assert len(p1["records"]) == 2
        assert len(p2["records"]) == 1
        assert p1["total"] == 3 and p1["total_pages"] == 2
        # 两页不重叠
        a = {json.dumps(x, sort_keys=True, ensure_ascii=False)
             for x in p1["records"]}
        b = {json.dumps(x, sort_keys=True, ensure_ascii=False)
             for x in p2["records"]}
        assert not (a & b)


def test_query_lottery_filter_plus_pagination_keeps_condition():
    with _with_tmp(SAMPLE) as _:
        spec = P.parse_query({"lot": "快乐8", "page": 1, "limit": 10})
        r = P.query_lottery_predictions(spec)
        assert r["total"] == 2
        assert {x["lot"] for x in r["records"]} == {"快乐8"}


def test_query_lottery_empty_reason():
    with _with_tmp([]) as _:
        spec = P.parse_query({})
        r = P.query_lottery_predictions(spec)
        assert r["empty_reason"] == "no_data"
    with _with_tmp(SAMPLE) as _:
        spec = P.parse_query({"q": "绝对不存在的词xyz"})
        r = P.query_lottery_predictions(spec)
        assert r["empty_reason"] == "no_match"
