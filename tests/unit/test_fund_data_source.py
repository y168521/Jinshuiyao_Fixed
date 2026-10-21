# -*- coding: utf-8 -*-
"""基金数据来源诚实性测试（JS-20261021-04 · P0-1 基金假数据 / P1-12 日期过滤）

背景（先证它红，全部有实测依据）：
  akshare 一失败，取数层就生成模拟数据，而且**把模拟数据写进缓存**，
  上层（domain.fetch）又一律标 "real"。本机实测证据：
    - 金水谣数据/fund/cache/holdings_*.json 共 11 个文件，十大重仓股
      **逐字相同**（茅台/五粮液/平安/美的/招行/比亚迪/宁德/紫金/海康/长电，
      持股数与持仓市值完全一致）—— 与 domains/fund/fund_mock.py 的固定表一致，
      物理上不可能 11 只基金持仓完全相同 ⇒ 确实是模拟数据；
    - 这些文件却被标成 "real" 展示给用户。
  另外 `_filter_by_date` 里 pd 只在函数内 import 过（模块作用域没有），
  一调用就 NameError，又被 `except Exception: return df` 吞掉 ⇒ 用户按日期
  区间取数，拿回来的却是全量历史，且没有任何提示（静默失效）。
"""
import os
import sys
import json
import tempfile
import shutil
import unittest
from datetime import datetime, timedelta

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.normpath(os.path.join(_this_dir, "..", ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

import pandas as pd

from domains.fund.fetcher import FundFetcher, SOURCE_REAL, SOURCE_MOCK
from domains.fund.domain import FundDomain
from core.ai.agent_formatters import format_fund_result
from core.infra.data_truth_guard import (
    _dtg_check_fund_cache, _dtg_check_fund, CACHE_SOURCE_REAL, CACHE_SOURCE_MOCK,
)


def _nav_df(rows=None):
    """构造净值 DataFrame（列名与 _standardize_nav 之后一致）"""
    if rows is None:
        rows = [
            ("2026-10-15", 1.5000),
            ("2026-10-16", 1.5100),
            ("2026-10-19", 1.4900),
            ("2026-10-20", 1.5200),
        ]
    return pd.DataFrame(
        [{"净值日期": d, "单位净值": v, "日增长率": 0.1} for d, v in rows])


def _hold_df():
    return pd.DataFrame([
        {"股票代码": "600519", "股票名称": "贵州茅台", "占净值比例": 9.85,
         "持股数(万股)": 120.5, "持仓市值(万元)": 58600},
    ])


class _FakeFetcher:
    """按指定来源回数据的假取数器（用于验证 domain 不再无条件标 real）"""

    def __init__(self, source="mock"):
        self._src = source

    def get_fund_nav(self, code, **kw):
        return _nav_df()

    def get_fund_info(self, code, **kw):
        return {"基金代码": code, "基金名称": "测试基金", "基金经理": "测试经理"}

    def get_fund_holdings(self, code, **kw):
        return _hold_df()

    def get_source(self, kind, code=""):
        return self._src


class TestMockNeverWrittenToCache(unittest.TestCase):
    """模拟数据永不写缓存（P0-1 第 1 条）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = FundFetcher(cache_dir=self.tmp)
        # 强制 akshare 不可用 → 走模拟降级分支
        self.f._has_akshare = False
        self.f._ak = None

    def test_mock_nav_not_written_to_cache(self):
        df = self.f.get_fund_nav("000001")
        self.assertIsNotNone(df)
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp, "nav_000001.json")),
            "模拟净值绝不写缓存——写了就会被下一次读取当成真实数据")

    def test_mock_info_not_written_to_cache(self):
        info = self.f.get_fund_info("000001")
        self.assertTrue(info)
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp, "info_000001.json")),
            "模拟基金信息绝不写缓存")

    def test_mock_holdings_not_written_to_cache(self):
        df = self.f.get_fund_holdings("000001")
        self.assertIsNotNone(df)
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp, "holdings_000001.json")),
            "模拟持仓绝不写缓存")

    def test_mock_list_not_written_to_cache(self):
        df = self.f.get_fund_list()
        self.assertIsNotNone(df)
        self.assertFalse(
            os.path.exists(os.path.join(self.tmp, "list_all.json")),
            "模拟基金列表绝不写缓存")

    def test_write_cache_refuses_mock_source(self):
        """兜底闸：即便调用方忘了判断，写盘这一层也要拦住非真实数据"""
        self.f._write_cache("manual_key", _nav_df(), source=SOURCE_MOCK)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "manual_key.json")))

    def test_mock_source_marked(self):
        self.f.get_fund_nav("000001")
        self.assertEqual(self.f.get_source("nav", "000001"), SOURCE_MOCK)
        self.f.get_fund_info("000001")
        self.assertEqual(self.f.get_source("info", "000001"), SOURCE_MOCK)
        self.f.get_fund_holdings("000001")
        self.assertEqual(self.f.get_source("holdings", "000001"), SOURCE_MOCK)
        self.f.get_fund_list()
        self.assertEqual(self.f.get_source("list", None), SOURCE_MOCK)


class TestRealOnlyUnified(unittest.TestCase):
    """real_only 四个取数入口统一（原只有排名入口有）"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = FundFetcher(cache_dir=self.tmp)
        self.f._has_akshare = False
        self.f._ak = None

    def test_real_only_nav_returns_none(self):
        self.assertIsNone(self.f.get_fund_nav("000001", real_only=True))

    def test_real_only_info_returns_none(self):
        self.assertIsNone(self.f.get_fund_info("000001", real_only=True))

    def test_real_only_holdings_returns_none(self):
        self.assertIsNone(self.f.get_fund_holdings("000001", real_only=True))

    def test_real_only_list_returns_none(self):
        self.assertIsNone(self.f.get_fund_list(real_only=True))

    def test_mock_tagged_cache_not_returned_as_real(self):
        """缓存文件标明 source=mock 时，real_only 也绝不返回它"""
        path = os.path.join(self.tmp, "rank_default.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"source": SOURCE_MOCK,
                       "records": [{"基金代码": "000001", "基金名称": "华夏成长混合"}]}, fh)
        self.assertIsNone(self.f.get_rank(real_only=True))


class TestRealPathMarksSource(unittest.TestCase):
    """真实路径：标 real + 缓存带来源标记"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = FundFetcher(cache_dir=self.tmp)
        self.f._fetch_nav_from_akshare = lambda code, start, end: _nav_df()

    def test_real_source_marked_and_cache_tagged(self):
        self.f.get_fund_nav("000001")
        self.assertEqual(self.f.get_source("nav", "000001"), SOURCE_REAL)
        path = os.path.join(self.tmp, "nav_000001.json")
        self.assertTrue(os.path.exists(path), "真实数据应当写缓存")
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload.get("source"), SOURCE_REAL)
        self.assertIn("records", payload)

    def test_cache_hit_marks_real(self):
        self.f.get_fund_nav("000001")          # 先写一份真实缓存
        f2 = FundFetcher(cache_dir=self.tmp)   # 新实例，只读缓存
        f2._has_akshare = False                # 即便 akshare 不可用
        df = f2.get_fund_nav("000001")
        self.assertIsNotNone(df)
        self.assertEqual(f2.get_source("nav", "000001"), SOURCE_REAL)
        self.assertEqual(len(df), 4)


class TestLegacyCacheNotTrusted(unittest.TestCase):
    """旧格式缓存（无来源标记）不冒充当真实数据"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = FundFetcher(cache_dir=self.tmp)
        self.f._has_akshare = False
        self.f._ak = None

    def test_legacy_cache_not_returned(self):
        # 旧格式：裸 list，没有 source 标记（修复前写入的格式）
        path = os.path.join(self.tmp, "nav_000001.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([{"净值日期": "2001-12-18", "单位净值": 1.0, "日增长率": 0.0}], fh)
        df = self.f.get_fund_nav("000001")
        self.assertIsNotNone(df)
        # 不能把 2001 年那条旧缓存当真实数据返回
        self.assertNotEqual(df.iloc[0]["净值日期"], "2001-12-18")
        self.assertEqual(self.f.get_source("nav", "000001"), SOURCE_MOCK)


class TestDomainFetchSourceHonesty(unittest.TestCase):
    """上层不再无条件标 real（P0-1 第 2 条）"""

    def _domain(self, source):
        d = FundDomain({})
        d._fetcher = _FakeFetcher(source)
        return d

    def test_fetch_marks_mock(self):
        d = self._domain("mock")
        r = d.fetch(funds=["000001"])
        self.assertEqual(d._data_mode["000001"], "mock")
        self.assertEqual(r["mode"], "mock")

    def test_fetch_marks_real(self):
        d = self._domain("real")
        r = d.fetch(funds=["000001"])
        self.assertEqual(d._data_mode["000001"], "real")
        self.assertEqual(r["mode"], "real")

    def test_fetch_mixed_sources_is_mock(self):
        """只要有一项不能自证真实，整只基金就按不真实标记（宁可错标 mock）"""
        class Mixed(_FakeFetcher):
            def get_source(self, kind, code=""):
                return "real" if kind == "nav" else "mock"

        d = FundDomain({})
        d._fetcher = Mixed("mock")
        d.fetch(funds=["000001"])
        self.assertEqual(d._data_mode["000001"], "mock")


class TestFormatterProminentWarning(unittest.TestCase):
    """模拟数据必须醒目提示，不能只放在一行小字里（P0-1 第 4 条）"""

    def test_quote_mode_warns_on_mock(self):
        text = format_fund_result(
            {"mode": "mock", "data": {"000001": {"info": {"基金名称": "测试基金"},
                                                 "nav": _nav_df()}}},
            None, None, mode="quote")
        self.assertIn("重要提示", text)
        self.assertIn("模拟兜底数据", text)
        self.assertNotIn("数据来源：真实行情", text)

    def test_quote_mode_says_real(self):
        text = format_fund_result(
            {"mode": "real", "data": {"000001": {"info": {"基金名称": "测试基金"},
                                                 "nav": _nav_df()}}},
            None, None, mode="quote")
        self.assertIn("数据来源：真实行情", text)
        self.assertNotIn("重要提示", text)

    def test_recommend_mode_warns_on_mock(self):
        """推荐链路原先压根没有数据来源提示"""
        analysis = {"results": {"000001": {
            "info": {"基金名称": "测试基金"},
            "nav_analysis": {"returns": {"年化收益率": 10.0},
                             "risk": {"最大回撤": -5.0}},
            "composite_score": {"总分": 80, "等级": "B"},
        }}}
        text = format_fund_result(
            {"mode": "mock", "data": {"000001": {}}}, analysis, None, mode="recommend")
        self.assertIn("重要提示", text)
        self.assertIn("模拟兜底数据", text)
        self.assertNotIn("数据来源：真实行情", text)

    def test_recommend_mode_real_no_warning(self):
        analysis = {"results": {"000001": {
            "info": {"基金名称": "测试基金"},
            "nav_analysis": {"returns": {"年化收益率": 10.0},
                             "risk": {"最大回撤": -5.0}},
            "composite_score": {"总分": 80, "等级": "B"},
        }}}
        text = format_fund_result(
            {"mode": "real", "data": {"000001": {}}}, analysis, None, mode="recommend")
        self.assertNotIn("重要提示", text)
        self.assertIn("数据来源：真实行情", text)


class TestFilterByDate(unittest.TestCase):
    """P1-12 日期过滤静默失效"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = FundFetcher(cache_dir=self.tmp)
        self.f._has_akshare = False
        self.f._ak = None

    def test_filter_actually_filters(self):
        rows = [
            ("2025-12-31", 1.0),
            ("2026-01-05", 1.1),
            ("2026-06-30", 1.2),
            ("2026-12-31", 1.3),
        ]
        out = self.f._filter_by_date(_nav_df(rows), "20260101", "20261231")
        self.assertEqual(len(out), 3, "只应保留 2026 年内的 3 条")
        self.assertEqual(out.iloc[0]["净值日期"], "2026-01-05")

    def test_filter_failure_is_loud_not_silent(self):
        """日期格式不对时必须留下日志，不许静默返回未过滤数据"""
        rows = [("2026-01-05", 1.1), ("2026-06-30", 1.2)]
        with self.assertLogs("domains.fund.fetcher", level="WARNING") as cm:
            out = self.f._filter_by_date(_nav_df(rows), "2026-01-01", "不是日期")
        self.assertEqual(len(out), 2)          # 仍然返回数据，不崩
        self.assertTrue(
            any("日期过滤失败" in m for m in cm.output),
            "必须打 warning，不能静默：%s" % cm.output)

    def test_end_to_end_nav_range(self):
        """缓存命中 + 带日期区间 → 拿到的是过滤后的数据"""
        path = os.path.join(self.tmp, "nav_000001.json")
        rows = [("2026-01-05", 1.1), ("2026-06-30", 1.2), ("2026-10-20", 1.3)]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"source": SOURCE_REAL,
                       "records": [{"净值日期": d, "单位净值": v, "日增长率": 0.1}
                                   for d, v in rows]}, fh)
        df = self.f.get_fund_nav("000001", start="20260601", end="20261231")
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[-1]["净值日期"], "2026-10-20")


class TestFundCacheVocabulary(unittest.TestCase):
    """守卫与取数层的来源标记取值必须一致（防两套口径）"""

    def test_values_match_fetcher(self):
        self.assertEqual(CACHE_SOURCE_REAL, SOURCE_REAL)
        self.assertEqual(CACHE_SOURCE_MOCK, SOURCE_MOCK)


def _guard_make_dirs(case):
    """造 <tmp>/jinshuiyao + <tmp>/金水谣数据/fund/cache，用完自动清理"""
    base = tempfile.mkdtemp()
    case.addCleanup(shutil.rmtree, base, True)
    jsy = os.path.join(base, "jinshuiyao")
    os.makedirs(jsy)
    cache = os.path.join(base, "金水谣数据", "fund", "cache")
    os.makedirs(cache)
    return jsy, cache


def _guard_write(cache, name, payload, age_hours=1):
    """往缓存目录写一个文件，并按 age_hours 改它的修改时间（造过期场景）"""
    path = os.path.join(cache, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    old = datetime.now() - timedelta(hours=age_hours)
    os.utime(path, (old.timestamp(), old.timestamp()))


class TestGuardFundCacheCheck(unittest.TestCase):
    """真实性守卫的基金缓存检查项（治假绿：守卫以前压根不查基金）"""

    def test_mock_tagged_cache_is_fail(self):
        jsy, cache = _guard_make_dirs(self)
        _guard_write(cache, "holdings_000001.json",
                     {"source": SOURCE_MOCK, "records": [{"股票代码": "600519"}]})
        status, detail, action = _dtg_check_fund_cache(jsy)
        self.assertEqual(status, "fail")
        self.assertIn("holdings_000001.json", detail)
        self.assertIsNotNone(action)

    def test_legacy_cache_is_warn(self):
        jsy, cache = _guard_make_dirs(self)
        _guard_write(cache, "nav_000001.json",
                     [{"净值日期": "2001-12-18", "单位净值": 1.0}])
        status, detail, action = _dtg_check_fund_cache(jsy)
        self.assertEqual(status, "warn")
        self.assertIn("无来源标记", detail)

    def test_all_real_cache_is_pass(self):
        jsy, cache = _guard_make_dirs(self)
        _guard_write(cache, "nav_000001.json",
                     {"source": SOURCE_REAL, "records": [{"净值日期": "2026-10-20"}]})
        status, detail, action = _dtg_check_fund_cache(jsy)
        self.assertEqual(status, "pass")
        self.assertIsNone(action)

    def test_backup_files_ignored(self):
        """safe_write_json 的 .bak.N 滚动备份不算在用的缓存"""
        jsy, cache = _guard_make_dirs(self)
        _guard_write(cache, "nav_000001.json",
                     {"source": SOURCE_REAL, "records": [{"净值日期": "2026-10-20"}]})
        _guard_write(cache, "nav_000001.json.bak.0",
                     {"source": SOURCE_MOCK, "records": []})
        status, _, _ = _dtg_check_fund_cache(jsy)
        self.assertEqual(status, "pass")

    def test_stale_cache_is_warn(self):
        jsy, cache = _guard_make_dirs(self)
        _guard_write(cache, "nav_000001.json",
                     {"source": SOURCE_REAL, "records": [{"净值日期": "2026-10-20"}]},
                     age_hours=48)
        status, detail, _ = _dtg_check_fund_cache(jsy)
        self.assertEqual(status, "warn")
        self.assertIn("未更新", detail)

    def test_no_cache_dir_is_pass(self):
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        jsy = os.path.join(base, "jinshuiyao")
        os.makedirs(jsy)
        status, _, _ = _dtg_check_fund_cache(jsy)
        self.assertEqual(status, "pass")


class TestGuardFundSubsystem(unittest.TestCase):
    """基金子系统必须出现在守卫全量报告里，且字段齐全"""

    def test_fund_subsystem_in_full_report(self):
        from core.infra import data_truth_guard as g
        report = g.run_truth_check()
        report_subsystems = report["subsystems"]
        self.assertIn("fund", report_subsystems)
        for chk in report_subsystems["fund"]["checks"]:
            for field in ("name", "status", "source", "detail"):
                self.assertIn(field, chk)


if __name__ == "__main__":
    unittest.main()
