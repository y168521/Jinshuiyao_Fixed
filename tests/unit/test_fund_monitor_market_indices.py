# -*- coding: utf-8 -*-
"""批3·切片D（JS-20260924-18）单元测试：美股系/港股科技/伦敦金现行情接入。

离线验证 akshare 接线正确性（symbol 字符串 + close_col 列名），
不触发任何真实网络请求。重点防两类静默错误：
1) 恒生科技东财列名是 `latest` 不是 `close`（用错列会 KeyError→静默漏数据）；
2) 伦敦金现是 `XAU`，`ZSD` 实为 LME 锌（用错 symbol 会显示锌价冒充金价）。
"""
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
import scripts.daily_fund_monitor as m  # noqa: E402

import akshare  # noqa: E402  # 与 get_market_indices 内 import akshare as ak 同模块对象


def _df_with(col, v_today, v_prev):
    """构造两行日线 DF，列名 col。

    真实 akshare 日线为「时间升序」：上一交易日在前、最新日在最后，
    故 iloc[-1] 才是今日。此处顺序须与之一致，否则 _idx_from_df 取错行。
    """
    return pd.DataFrame([
        {"date": "2026-09-22", "open": 1, "high": 1, "low": 1, col: v_prev},
        {"date": "2026-09-23", "open": 1, "high": 1, "low": 1, col: v_today},
    ])


def test_get_market_indices_new_us_hk_gold(monkeypatch):
    """桩接 4 个新增 akshare 接口，断言行情区出现 4 个新指数且数值正确。"""
    captured_gold = {}

    def fake_us(symbol=".INX"):
        # 纳斯达克100(.NDX) / 标普500(.INX) 均用此函数，列名 close
        return _df_with("close", 18000.0, 18200.0)

    def fake_hk_em(symbol="HSTECH"):
        # 东财港股指数列名是 latest（不是 close）
        return _df_with("latest", 5000.0, 5050.0)

    def fake_hk_sina(symbol="HSTECH"):
        # 新浪港股指数列名是 close（备源，正常不会被用到）
        return _df_with("close", 5000.0, 5050.0)

    def fake_gold(symbol="XAU"):
        captured_gold["symbol"] = symbol
        return _df_with("close", 2600.0, 2590.0)

    monkeypatch.setattr(akshare, "index_us_stock_sina", fake_us)
    monkeypatch.setattr(akshare, "stock_hk_index_daily_em", fake_hk_em)
    monkeypatch.setattr(akshare, "stock_hk_index_daily_sina", fake_hk_sina)
    monkeypatch.setattr(akshare, "futures_foreign_hist", fake_gold)
    # 旧源（上证/沪深300/恒生/沪金）未桩接，让其快速失败、不阻塞（不触网）
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline")))

    # FundDataFetcher.__init__ 会触网加载当日基金表，桩掉
    monkeypatch.setattr(m.FundDataFetcher, "_load_daily_data", lambda self: None)

    fetcher = m.FundDataFetcher()
    indices = fetcher.get_market_indices()

    for name in ("纳斯达克100", "标普500", "恒生科技指数", "伦敦金现"):
        assert name in indices, f"行情区缺失: {name}"
        assert "value" in indices[name] and "change_pct" in indices[name]

    # 恒生科技必须取自东财 latest 列（5000.0），确认 close_col 接线正确
    assert indices["恒生科技指数"]["value"] == 5000.0
    # 伦敦金现必须走 XAU（不是 ZSD=LME锌）；这是此前踩过的坑
    assert captured_gold["symbol"] == "XAU"


def test_report_renders_new_indices(monkeypatch, tmp_path):
    """端到端：4 个新指数传入 _build_html 后出现在报告里。"""
    monkeypatch.setattr(m, "FUND_CONFIG", [{
        "code": "X", "name": "测试基金", "category": "QDII-宽基",
        "investment": 10, "related_index": "标普500",
    }])
    rg = m.ReportGenerator(output_dir=str(tmp_path))
    data = {"X": {
        "config": {"name": "测试基金", "code": "X"},
        "interval_returns": {}, "risks": {}, "snapshot": {}, "signals": {},
    }}
    indices = {
        "纳斯达克100": {"value": 18000.0, "change_pct": -1.10},
        "标普500": {"value": 5500.0, "change_pct": -0.80},
        "恒生科技指数": {"value": 4000.0, "change_pct": 2.10},
        "伦敦金现": {"value": 2600.0, "change_pct": 0.30},
    }
    html = rg._build_html("2026-09-24", "09:00", data, indices, {})
    for name in ("纳斯达克100", "标普500", "恒生科技指数", "伦敦金现"):
        assert name in html, f"报告未渲染: {name}"
