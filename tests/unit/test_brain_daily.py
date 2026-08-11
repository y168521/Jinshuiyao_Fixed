# -*- coding: utf-8 -*-
"""大脑日报引擎单测 (engines/brain_daily.py) — 第2步·长脑子"""
import io
import json
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engines import brain_daily


def _fake_predictions(tmp_path):
    rows = []
    for i in range(40):
        rows.append({
            "lot": "福彩3D", "period": 2026000 + i, "nums": "04,15,26",
            "type": "单注", "scheme": "默认方案", "hits": 1 if i % 3 else 0,
        })
        rows.append({
            "lot": "快乐8", "period": 2026000 + i, "nums": "01,22,33,44,55,66,77,88,11,12",
            "type": "复式", "scheme": "默认方案", "hits": 2 if i % 3 else 1,
        })
        rows.append({
            "lot": "七乐彩", "period": 2026000 + i, "nums": "01,02,03,04,05,06,07",
            "type": "胆拖", "scheme": "默认方案", "hits": 0,
        })
    return rows


class TestBrainDaily(unittest.TestCase):

    def setUp(self):
        self._td = brain_daily._today()
        self._orig_dirs = (brain_daily._BRAIN_DIR, brain_daily._REPORT_DIR)
        brain_daily._BRAIN_DIR = os.path.join(_HERE, "_tmp_brain")
        brain_daily._REPORT_DIR = os.path.join(_HERE, "_tmp_report")
        for d in (brain_daily._BRAIN_DIR, brain_daily._REPORT_DIR):
            os.makedirs(d, exist_ok=True)

    def tearDown(self):
        brain_daily._BRAIN_DIR, brain_daily._REPORT_DIR = self._orig_dirs

    def _clear(self):
        for d in (brain_daily._BRAIN_DIR, brain_daily._REPORT_DIR):
            for f in os.listdir(d):
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass

    @mock.patch("engines.brain_daily._get_ai", return_value=None)
    def test_no_ai_degrades_silently(self, _m):
        """无AI时AI相关能力静默降级；日报为纯统计仍可生成"""
        self.assertEqual(brain_daily.ensure_daily_brief("福彩3D", []), None)
        self.assertEqual(brain_daily.ensure_daily_summary(), None)
        path = brain_daily.gen_daily_report()
        self.assertTrue(path and os.path.isfile(path))
        self._clear()

    @mock.patch("engines.brain_daily._get_ai")
    def test_brief_parse_and_cache(self, m_ai):
        """AI返回JSON围栏 → 正确解析；同一天第二次调用不再调AI"""
        m_ai.return_value.chat.return_value = (
            '```json\n{"hot": [7, 2, 9], "kill": [0, 5], "morph": "组三", "reason": "近期7活跃"}'
            '\n```'
        )
        arr = [{"period": i, "nums": "01,02,03"} for i in range(20)]
        b1 = brain_daily.ensure_daily_brief("福彩3D", arr)
        self.assertEqual(b1["hot"], [2, 7, 9])
        self.assertEqual(b1["kill"], [0, 5])
        self.assertEqual(b1["morph"], "组三")
        # 缓存：第二次调用不再调AI
        m_ai.return_value.chat.reset_mock()
        b2 = brain_daily.ensure_daily_brief("福彩3D", arr)
        self.assertEqual(b1, b2)
        m_ai.return_value.chat.assert_not_called()
        self._clear()

    @mock.patch("engines.brain_daily._get_ai", return_value=None)
    def test_report_stats(self, _m):
        """日报统计：从复盘数据算 实际/期望 与结论"""
        pred = os.path.join(_HERE, "_tmp_predictions.json")
        with io.open(pred, "w", encoding="utf-8") as f:
            json.dump(_fake_predictions(pred), f)
        brain_daily._PRED_FILE = pred
        try:
            path = brain_daily.gen_daily_report(self._td)
            self.assertTrue(path and os.path.isfile(path))
            txt = io.open(path, encoding="utf-8").read()
            self.assertIn("大脑日报", txt)
            self.assertIn("福彩3D", txt)
            self.assertIn("胆拖", txt)
            self.assertIn("已停用", txt)  # 胆拖全禁结论
            self.assertIn("维持", txt)    # 正常玩法维持
        finally:
            brain_daily._PRED_FILE = os.path.join("金水谣数据", "predictions.json")
            try:
                os.remove(pred)
            except OSError:
                pass
            self._clear()

    @mock.patch("engines.brain_daily._get_ai")
    def test_summary_ai_and_file(self, m_ai):
        """AI复盘总结：解析JSON并落盘，当天第二次直接读文件"""
        m_ai.return_value.chat.return_value = (
            '{"pattern": "近3期单注命中偏低", "advice": "减少单注注数"}'
        )
        brain_daily._PRED_FILE = os.path.join("金水谣数据", "predictions.json")
        summary = brain_daily.ensure_daily_summary()
        self.assertIsNotNone(summary)
        self.assertIn("复盘总结", summary)
        f = os.path.join(brain_daily._BRAIN_DIR, "ai_summary_%s.md" % self._td)
        self.assertTrue(os.path.isfile(f))
        # 缓存命中：不再调AI
        m_ai.return_value.chat.reset_mock()
        brain_daily.ensure_daily_summary()
        m_ai.return_value.chat.assert_not_called()
        self._clear()


if __name__ == "__main__":
    unittest.main()