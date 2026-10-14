"""JS-20261012-20：当日购票数据（诚实记账层）单测。

定位：本模块**只记账，不预测**。数据禁止用于选号/权重/杀号。
依据：JS-20261012-13 决策 + 官方返奖率锚点（财政部公告 2026 年第 24 号）。

双向覆盖：
- 正向：能记账、能汇总、幂等覆盖；
- 反向：红线字段必须被剔除且不落库；`net` 派生值不得录入；
        空样本 `ratio` 必须是 None（「不知道」不是「0」）。
"""

import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import utils.purchase_log as pl


# ── 1. 记账与幂等 ──

def test_record_and_get(tmp_path, monkeypatch):
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    e, dropped = pl.record({"lot": "双色球", "period": "2026116",
                            "purchased": True, "purchase_amount": 4.0,
                            "purchase_count": 2, "payout": 0.0})
    assert dropped == []
    assert e["purchased"] is True
    got = pl.get("双色球", "2026116")
    assert got is not None and got["purchase_amount"] == 4.0


def test_record_is_idempotent_by_lot_and_period(tmp_path, monkeypatch):
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    pl.record({"lot": "大乐透", "period": "2026116", "purchased": True,
               "purchase_amount": 2.0, "payout": 0.0})
    pl.record({"lot": "大乐透", "period": "2026116", "purchased": True,
               "purchase_amount": 6.0, "payout": 5.0})
    assert len(pl.load_log()) == 1
    assert pl.get("大乐透", "2026116")["purchase_amount"] == 6.0


def test_get_missing_returns_none(tmp_path, monkeypatch):
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    assert pl.get("快乐8", "9999999") is None


# ── 2. 语义兜底：缺数据 ≠ 没发生 ──

def test_missing_purchased_defaults_false(tmp_path, monkeypatch):
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    e, _ = pl.record({"lot": "福彩3D", "period": "2026271"})
    assert e["purchased"] is False
    assert "payout" not in e, "未购票不得凭空产生兑奖额"


def test_payout_defaults_zero_when_bought(tmp_path, monkeypatch):
    """未中奖记 0，不得留空——空值会被误读为「没统计」。"""
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    e, _ = pl.record({"lot": "排列三", "period": "2026271", "purchased": True,
                      "purchase_amount": 4.0})
    assert e["payout"] == 0.0


def test_net_is_derived_not_stored(tmp_path, monkeypatch):
    """net 是派生值：传入也剔除，只在 summary 里计算。"""
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    e, dropped = pl.record({"lot": "双色球", "period": "2026117", "purchased": True,
                                 "purchase_amount": 10.0, "payout": 5.0, "net": 999.0})
    assert "net" not in e
    assert "net" in dropped
    assert e["purchase_amount"] - e["payout"] == 5.0


# ── 3. 红线字段：拒收并留痕，绝不静默丢弃 ──

def test_banned_fields_are_dropped_and_logged(tmp_path, monkeypatch, caplog):
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    with caplog.at_level(logging.WARNING):
        e, dropped = pl.record({"lot": "双色球", "period": "2026118", "purchased": True,
                                     "purchase_amount": 2.0, "payout": 0.0,
                                     "ticket_no": "ABC123", "phone": "13800000000"})
    assert "ticket_no" not in e and "phone" not in e
    assert "ticket_no" in dropped and "phone" in dropped
    txt = caplog.text
    assert "拒绝红线字段" in txt
    # 日志里绝不能出现字段值
    assert "ABC123" not in txt and "13800000000" not in txt


def test_unknown_field_is_ignored(tmp_path, monkeypatch):
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    e, _ = pl.record({"lot": "快乐8", "period": "2026272",
                   "purchased": True, "purchase_amount": 2.0,
                   "payout": 0.0, "随便一个字段": "x"})
    assert "随便一个字段" not in e


# ── 4. 校验与汇总 ──

def test_missing_key_raises(tmp_path, monkeypatch):
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    try:
        pl.record({"purchased": True})
    except ValueError:
        return
    raise AssertionError("缺少 lot/period 应抛 ValueError")


def test_summary_math(tmp_path, monkeypatch):
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    pl.record({"lot": "双色球", "period": "2026116", "purchased": True,
                  "purchase_amount": 100.0, "payout": 50.0})
    s = pl.summary("双色球")
    assert s["bought"] == 1
    assert s["spend"] == 100.0
    assert s["payout"] == 50.0
    assert s["net"] == -50.0
    assert s["ratio"] == 0.5
    assert s["official_ratio"] == 0.51


def test_summary_empty_ratio_is_none(tmp_path, monkeypatch):
    """反向：空样本 ratio 必须是 None，不能是 0（0 会被读成「一分没回」）。"""
    p = tmp_path / "purchase_log.json"
    monkeypatch.setattr(pl, "PURCHASE_LOG_PATH", str(p))
    s = pl.summary("七星彩")
    assert s["records"] == 0
    assert s["ratio"] is None


def test_official_ratio_unknown_lot_is_none():
    assert pl.official_payout_ratio("不存在的彩种") is None


def test_log_file_not_committed():
    """运行时数据不入仓：purchase_log.json 必须被 .gitignore 覆盖。"""
    gi = os.path.join(_ROOT, ".gitignore")
    with open(gi, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    assert "purchase_log.json" in txt
