"""JS-20261012-20：彩票数据新鲜度门槛 —— 按彩种开奖节奏动态取值。

修复前的缺陷（已实证）：
- 阈值全仓固定 1440 分钟，而大乐透 draw_days=[0,2,5] 相邻开奖最长间隔 3 天
  ⇒ **数据完全最新时也恒判陈旧** ⇒ domain.generate() 整批返回 stale_data 拒绝出号
  ⇒ 表象是「某个开奖日压根没生成预测」（正是 JS-20261012-12 里大乐透缺 4 期的嫌疑之一）。
- time 字段全是纯日期，却按零点解析 ⇒ freshness 系统性虚增近 1 天。

实测取证（2026-10-12 21:05，周一，各彩种今晚均未到开奖时刻）：
修复前 7 个彩种 is_fresh(1440) **全部 False**，而数据其实都是最新的 ⇒ 纯属误杀。

本文件守卫两个方向：
- 正向：非每日型在正常间隔内**必须判新鲜**（不再天天误杀）；
- 反向：真的陈旧时**必须仍判陈旧**（不能为了不误杀就改到永不报警——那等于把闸拆了）。
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from models.lottery_data import (
    Data, FRESH_SLACK_MINUTES, suggest_fresh_threshold, _parse_time_to_ts,
)

_DAY = 1440


# ── 1. suggest_fresh_threshold：按 draw_days 算最大相邻开奖间隔 ──

def test_daily_lottery_threshold():
    assert suggest_fresh_threshold("福彩3D") == _DAY + FRESH_SLACK_MINUTES
    assert suggest_fresh_threshold("排列三") == _DAY + FRESH_SLACK_MINUTES
    assert suggest_fresh_threshold("快乐8") == _DAY + FRESH_SLACK_MINUTES


def test_multi_draw_days_use_max_gap_including_week_wrap():
    """最大间隔必须含跨周回环：[0,2,5] 的周六→周一也是间隔之一（2 天），而周三→周六是 3 天。"""
    # 大乐透 [0,2,5] → gaps=[2,3]，回环=2 ⇒ max=3 天
    assert suggest_fresh_threshold("大乐透") == 3 * _DAY + FRESH_SLACK_MINUTES
    # 七乐彩 [0,2,4] → gaps=[2,2]，回环 7-4+0=3 ⇒ max=3 天（**回环才是最大值**，漏算回环就会错）
    assert suggest_fresh_threshold("七乐彩") == 3 * _DAY + FRESH_SLACK_MINUTES
    # 双色球 [1,3,6] / 七星彩 [1,4,6] 同理 max=3 天
    assert suggest_fresh_threshold("双色球") == 3 * _DAY + FRESH_SLACK_MINUTES
    assert suggest_fresh_threshold("七星彩") == 3 * _DAY + FRESH_SLACK_MINUTES


def test_single_draw_day_is_a_week():
    """每周只开一天 ⇒ 间隔 7 天。这是最容易漏的形态。"""
    from models import lottery_data as _mod
    old = dict(_mod.LOTTERY_RULES)
    try:
        _mod.LOTTERY_RULES["_测试周开奖"] = {"draw_days": [2]}
        assert suggest_fresh_threshold("_测试周开奖") == 7 * _DAY + FRESH_SLACK_MINUTES
    finally:
        _mod.LOTTERY_RULES.clear()
        _mod.LOTTERY_RULES.update(old)


def test_missing_or_invalid_draw_days_defaults_to_one_day():
    from models import lottery_data as _mod
    old = dict(_mod.LOTTERY_RULES)
    try:
        _mod.LOTTERY_RULES["_无规则"] = {}
        _mod.LOTTERY_RULES["_非法"] = {"draw_days": "garbage"}
        _mod.LOTTERY_RULES["_空表"] = {"draw_days": []}
        for k in ("_无规则", "_非法", "_空表"):
            assert suggest_fresh_threshold(k) == _DAY + FRESH_SLACK_MINUTES, k
    finally:
        _mod.LOTTERY_RULES.clear()
        _mod.LOTTERY_RULES.update(old)


def test_threshold_never_below_max_gap():
    """不变式：阈值必须 ≥ 相邻开奖最大间隔，否则又会回到「开奖日恒判陈旧」。"""
    from config import LOTTERY_RULES
    for lot, rule in LOTTERY_RULES.items():
        days = rule.get("draw_days")
        if isinstance(days, (list, tuple)) and len(days) >= 2:
            ds = sorted(days)
            max_gap = max(max(ds[i + 1] - ds[i] for i in range(len(ds) - 1)),
                          7 - ds[-1] + ds[0])
            assert suggest_fresh_threshold(lot) >= max_gap * _DAY, lot


# ── 2. _parse_time_to_ts：纯日期解析 ──

def test_day_end_parses_pure_date_as_end_of_day():
    """day_end=True 时纯日期按 23:59:59，消除 freshness 虚增近 1 天。"""
    import datetime
    a = _parse_time_to_ts("2026-10-11", day_end=True)
    b = _parse_time_to_ts("2026-10-11", day_end=False)
    assert a is not None and b is not None
    assert datetime.datetime.fromtimestamp(a).hour == 23
    assert datetime.datetime.fromtimestamp(b).hour == 0
    # 同一天内相差约 24 小时（23:59:59 - 00:00:00）
    assert 23 * 3600 < (a - b) <= 24 * 3600


def test_day_end_does_not_affect_datetime_string():
    """带时刻的字符串不受 day_end 影响（防越界改动）。"""
    s = "2026-10-11 21:15:00"
    assert _parse_time_to_ts(s, day_end=True) == _parse_time_to_ts(s, day_end=False)


def test_unparsable_returns_none_in_both_modes():
    assert _parse_time_to_ts("", day_end=True) is None
    assert _parse_time_to_ts("乱码-not-date", day_end=True) is None


# ── 3. is_fresh：默认阈值动态化 + 反向验证不能改太松 ──

class _FakeFresh:
    """临时替换 Data.freshness_minutes 以隔离真实数据，保证用例可复现。"""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self._old = Data.freshness_minutes
        Data.freshness_minutes = staticmethod(lambda name, now=None: self.value)
        return self

    def __exit__(self, *exc):
        Data.freshness_minutes = self._old
        return False


def test_dlt_fresh_within_gap_is_not_killed():
    """正向：大乐透在正常间隔（3 天内）必须判新鲜 —— 修复前这里恒 False。"""
    thr = suggest_fresh_threshold("大乐透")
    with _FakeFresh(3 * _DAY - 1):          # 差 1 分钟到 3 天
        assert Data.is_fresh("大乐透") is True
    # 反证：改前用固定 1440 时，(3天-1分钟) 会被判陈旧
    with _FakeFresh(3 * _DAY - 1):
        assert Data.is_fresh("大乐透", threshold_min=1440) is False


def test_really_stale_is_still_blocked():
    """反向：真陈旧必须仍判 False —— 不能为了不误杀把阈改到永不报警。"""
    thr = suggest_fresh_threshold("大乐透")
    with _FakeFresh(thr + 1):
        assert Data.is_fresh("大乐透") is False
    thr_daily = suggest_fresh_threshold("快乐8")
    with _FakeFresh(thr_daily + 1):
        assert Data.is_fresh("快乐8") is False


def test_no_data_is_not_fresh():
    with _FakeFresh(None):
        assert Data.is_fresh("大乐透") is False


def test_explicit_threshold_still_wins():
    """调用方显式传参时优先（回测脚本等有明确意图的场景不受影响）。"""
    with _FakeFresh(100):
        assert Data.is_fresh("大乐透", threshold_min=50) is False
        assert Data.is_fresh("大乐透", threshold_min=200) is True


# ── 4. 端到端：真实数据现状 ──

def test_all_lots_pass_freshness_gate_with_real_data():
    """端到端：当前真实数据下，7 彩种都不应被门禁误杀。

    注意：这条会随时间/抓取状态变化。若某天真的陈旧了，它失败是对的
    （那就是真实告警，需要去抓数据），不是用例本身失效。
    """
    from config import LOTTERY_RULES
    killed = []
    for lot in LOTTERY_RULES:
        fm = Data.freshness_minutes(lot)
        thr = suggest_fresh_threshold(lot)
        if fm is None or fm > thr:
            killed.append("%s(freshness=%s, 阈值=%d)" % (lot, fm, thr))
    assert not killed, (
        "以下彩种被新鲜度门禁拒绝（若为真实陈旧请先抓取最新开奖）:\n" + "\n".join(killed)
    )
