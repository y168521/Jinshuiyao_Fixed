# -*- coding: utf-8 -*-
"""状态筛选口径统一（P0 / S-01 配套，JS-20261015-04）。

为什么要这个闸
--------------
统一查询层要同时服务**两个数据源**，它们的"命中"字段天然不同：

  数据源                       命中字段      未中
  ---------------------------  -----------   -----------
  彩票预测（金水谣数据）        hits > 0      hits <= 0
  Q&A 预测沉淀（predictions）  outcome=hit   outcome=miss

而前端 `prediction-tracker.html` 的下拉值是 **英文** `hit/miss/pending`
（见 renderDetails 第 247-249 行），统一层原本只认**中文**「命中/未中」。
两者直接对接会**静默返回空列表** —— 用户看到"没有数据"，实际是口径不通。

这是本项目反复出现那一类病（静默失败伪装成正常状态）的又一个变体，
故在此用断言锁死，而不是靠记忆。
"""
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from utils.list_query import (  # noqa: E402
    parse_query, filter_records, QuerySpec,
)

QA_FIELDS = ("question", "answer", "domain", "time")
LOT_FIELDS = ("lot", "period", "date", "nums", "type", "scheme")
LOT_NUMBER_FIELDS = ("period", "nums")


def _qa(question, outcome, qid="x"):
    return {"id": qid, "question": question, "answer": "a",
            "domain": "lottery", "outcome": outcome,
            "time": "2026-10-01 10:00:00"}


def _lot(lot, hits):
    return {"lot": lot, "period": "2026115", "nums": "01 02 03",
            "hits": hits, "time": "2026-10-01 10:00:00"}


class TestStatusAlias(unittest.TestCase):
    """英文状态值必须在入参解析阶段归一成中文，且不误伤未知值。"""

    def test_hit_alias(self):
        self.assertEqual("命中", parse_query({"status": "hit"}).status)

    def test_miss_alias(self):
        self.assertEqual("未中", parse_query({"status": "miss"}).status)

    def test_pending_alias(self):
        self.assertEqual("待复盘", parse_query({"status": "pending"}).status)

    def test_reviewed_alias(self):
        self.assertEqual("已复盘", parse_query({"status": "reviewed"}).status)

    def test_chinese_passthrough(self):
        """已是中文时幂等，别二次翻译。"""
        self.assertEqual("已复盘", parse_query({"status": "已复盘"}).status)
        self.assertEqual("待复盘", parse_query({"status": "待复盘"}).status)

    def test_empty_and_unknown(self):
        self.assertEqual("", parse_query({"status": ""}).status)
        # 未知值原样保留：交给筛选逻辑判空，不在入参层静默吞掉
        self.assertEqual("weird", parse_query({"status": "weird"}).status)

    def test_case_and_space_insensitive(self):
        self.assertEqual("命中", parse_query({"status": " HIT "}).status)


class TestQaHitJudgement(unittest.TestCase):
    """Q&A 数据源按 outcome 判定命中（它没有 hits 字段）。"""

    def test_filter_hit_by_outcome(self):
        recs = [_qa("q1", "hit", "a1"), _qa("q2", "miss", "a2"),
                _qa("q3", None, "a3")]
        spec = parse_query({"status": "hit"})
        out = filter_records(recs, spec, QA_FIELDS)
        self.assertEqual(["a1"], [r["id"] for r in out])

    def test_filter_miss_by_outcome(self):
        recs = [_qa("q1", "hit", "a1"), _qa("q2", "miss", "a2"),
                _qa("q3", None, "a3")]
        spec = parse_query({"status": "miss"})
        out = filter_records(recs, spec, QA_FIELDS)
        self.assertEqual(["a2"], [r["id"] for r in out])

    def test_filter_pending_by_outcome(self):
        recs = [_qa("q1", "hit", "a1"), _qa("q2", "miss", "a2"),
                _qa("q3", None, "a3")]
        spec = parse_query({"status": "pending"})
        out = filter_records(recs, spec, QA_FIELDS)
        self.assertEqual(["a3"], [r["id"] for r in out])

    def test_qa_hit_is_not_all_filtered_out(self):
        """回归防护：不能因为 Q&A 缺 hits 就把命中记录全过滤掉。"""
        recs = [_qa("q1", "hit", "a1"), _qa("q2", "hit", "a2")]
        spec = parse_query({"status": "hit"})
        out = filter_records(recs, spec, QA_FIELDS)
        self.assertEqual(2, len(out), "Q&A 命中记录被错误过滤空")


class TestLotteryHitJudgement(unittest.TestCase):
    """彩票数据源仍按 hits 判定命中，不被 Q&A 口径顶替。"""

    def test_filter_hit_by_hits(self):
        recs = [_lot("双色球", 3), _lot("福彩3D", 0)]
        spec = parse_query({"status": "命中"})
        out = filter_records(recs, spec, LOT_FIELDS, LOT_NUMBER_FIELDS)
        self.assertEqual(["双色球"], [r["lot"] for r in out])

    def test_filter_miss_by_hits(self):
        recs = [_lot("双色球", 3), _lot("福彩3D", 0)]
        spec = parse_query({"status": "未中"})
        out = filter_records(recs, spec, LOT_FIELDS, LOT_NUMBER_FIELDS)
        self.assertEqual(["福彩3D"], [r["lot"] for r in out])


if __name__ == "__main__":
    unittest.main(verbosity=2)
