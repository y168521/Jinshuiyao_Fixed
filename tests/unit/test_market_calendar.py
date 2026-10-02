# -*- coding: utf-8 -*-
"""休市日历测试（JS-20261002-21）

事故背景：用户问「昨天(10-01)怎么没有复盘」。我第一反应是「数据源断了」，
列了一堆证据（每次刷新返回同样条数、curl 连不上），**全错**——
国庆本来就休市，没开奖，复盘当然跳过。curl 失败是沙箱限制，根本不是证据。

根因：**系统不知道「休市」这件事**，只会说「未开奖」，于是人和 AI 一起
往「数据源故障」的方向误判。

本模块提供休市感知后，本测试锁死最关键的一点：
    **休市 ≠ 数据源故障，两者必须给出不同的结论**。
前者让人白修一圈，后者掩盖真实的线路中断，同样有害。
"""
import io
import os
import sys
import unittest
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from utils.market_calendar import (  # noqa: E402
    classify,
    calendar_freshness,
    current_holiday,
    days_since,
    is_market_closed,
    load_calendar,
    normal_interval_days,
)

REAL_CAL = None
MISSING_PATH = os.path.join(BASE, "config", "__不存在的日历__.json")


def setUpModule():
    global REAL_CAL
    REAL_CAL = load_calendar()


class TestLoadIsSafe(unittest.TestCase):
    """缺省降级：文件没了也不能让服务挂。"""

    def test_missing_file_returns_empty(self):
        cal = load_calendar(MISSING_PATH)
        self.assertEqual(cal.get("holidays"), [])
        # 不得抛异常

    def test_real_calendar_has_holidays(self):
        self.assertGreater(len(REAL_CAL.get("holidays", [])), 0)


class TestNationalDayHoliday(unittest.TestCase):
    """国庆休市：这是本次事故的核心场景。"""

    def test_closed_on_oct_2_2026(self):
        self.assertTrue(is_market_closed("福彩3D", date(2026, 10, 2), REAL_CAL))

    def test_closed_first_and_last_day(self):
        for d in (date(2026, 10, 1), date(2026, 10, 4)):
            self.assertTrue(is_market_closed("双色球", d, REAL_CAL),
                            "%s 应处于休市期" % d)

    def test_open_before_and_after(self):
        for d in (date(2026, 9, 30), date(2026, 10, 5)):
            self.assertFalse(is_market_closed("双色球", d, REAL_CAL),
                             "%s 不在休市期" % d)

    def test_holiday_entry_has_resume_date(self):
        h = current_holiday(date(2026, 10, 2), REAL_CAL)
        self.assertIsNotNone(h)
        self.assertEqual(h.get("resume_date"), "2026-10-05")


class TestClassifySeparatesHolidayFromOutage(unittest.TestCase):
    """最关键：休市 与 数据源故障 必须给出不同结论。"""

    def test_holiday_status(self):
        # 10-02 休市中，上次开奖 9-30（2 天前）
        r = classify("福彩3D", "2026-09-30", REAL_CAL, today=date(2026, 10, 2))
        self.assertEqual(r["status"], "holiday")
        self.assertIn("休市", r["message"])
        self.assertIn("2026-10-05", r["message"], "文案必须给出预计恢复日")
        self.assertTrue(r["verified"])

    def test_holiday_even_if_stalled_long(self):
        """哪怕已停滞很久，只要处于休市期，就必须归因休市而非故障。"""
        r = classify("福彩3D", "2026-09-20", REAL_CAL, today=date(2026, 10, 3))
        self.assertEqual(r["status"], "holiday")

    def test_suspect_stale_when_not_holiday(self):
        """不在休市期却长期没新数据 → 疑似异常（不能假装正常）。"""
        r = classify("福彩3D", "2026-06-01", REAL_CAL, today=date(2026, 8, 1))
        self.assertEqual(r["status"], "suspect_stale")
        self.assertIn("请人工确认", r["message"])

    def test_normal_cycle(self):
        r = classify("福彩3D", "2026-06-01", REAL_CAL, today=date(2026, 6, 2))
        self.assertEqual(r["status"], "normal")

    def test_interval_respected_per_lot(self):
        """双色球隔天开，同样停滞 2 天不该报警；停 6 天该报。"""
        self.assertEqual(normal_interval_days("双色球", REAL_CAL), 2)
        ok = classify("双色球", "2026-06-01", REAL_CAL, today=date(2026, 6, 3))
        self.assertEqual(ok["status"], "normal")
        bad = classify("双色球", "2026-06-01", REAL_CAL, today=date(2026, 6, 8))
        self.assertEqual(bad["status"], "suspect_stale")


class TestUnverifiedHonesty(unittest.TestCase):
    """未核实的休市区间必须说清楚，不许冒充确定的事实。"""

    def test_unverified_note_present(self):
        # 2027 春节条目标了 verified=false
        r = classify("福彩3D", "2027-01-30", REAL_CAL, today=date(2027, 2, 6))
        self.assertEqual(r["status"], "holiday")
        self.assertFalse(r["verified"])
        self.assertIn("以中彩中心官方公告为准", r["message"])


class TestFreshnessReminder(unittest.TestCase):
    """日历本身也会过期，过期要提醒人工核对（不自动改数字）。"""

    def test_not_expired_now(self):
        f = calendar_freshness(REAL_CAL, today=date(2026, 10, 2))
        self.assertFalse(f["expired"])
        self.assertTrue(f["ok"])

    def test_expired_later(self):
        f = calendar_freshness(REAL_CAL, today=date(2028, 1, 1))
        self.assertTrue(f["expired"])
        self.assertIn("请对照官方公告更新", f["message"])


class TestDaysSince(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(days_since("2026-09-30", date(2026, 10, 2)), 2)

    def test_bad_input(self):
        self.assertIsNone(days_since("", date(2026, 10, 2)))
        self.assertIsNone(days_since(None, date(2026, 10, 2)))


class TestWiredIntoReview(unittest.TestCase):
    """接入闸：本模块必须真的被复盘链路用到，不能沦为孤儿。

    （MEMORY 教训：写了检查器/工具却没人调用 = 等于没有。）
    """

    def test_scheduler_imports_market_calendar(self):
        src = io.open(os.path.join(BASE, "core", "infra", "scheduler.py"),
                      encoding="utf-8").read()
        self.assertIn("utils.market_calendar", src,
                      "自动复盘必须引用休市日历，否则休市感知形同虚设")

    def test_scheduler_counts_holiday_skips(self):
        src = io.open(os.path.join(BASE, "core", "infra", "scheduler.py"),
                      encoding="utf-8").read()
        self.assertIn("skip_holiday", src)
        self.assertIn("holiday_skipped", src)


if __name__ == "__main__":
    unittest.main()
