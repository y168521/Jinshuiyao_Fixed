# -*- coding: utf-8 -*-
"""
金水谣系统 - 策略知识卡提炼测试 (P1)

测试 engines/strategy_cards.py:
复盘数据 → 策略卡提炼（三类引擎挂钩）、样本不足跳过、幂等更新
"""

import os
import sys
import json
import tempfile

# 确保项目根目录在 sys.path 中
_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_test_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import engines.strategy_cards as sc


class FakeCardStore:
    """替代 MiroFishDB 的内存实现（不触碰真实知识库）"""

    def __init__(self):
        self._data = {"cards": []}
        self.saved = 0

    def add_card(self, **kwargs):
        card = dict(kwargs)
        card["title"] = kwargs["title"]
        card.setdefault("effectiveness", 50)
        card.setdefault("use_count", 0)
        card["effectiveness"] = min(90, max(10, card["effectiveness"]))
        self._data["cards"].append(card)
        return card

    def _save(self):
        self.saved += 1


def _make_reviews(lot, n, hits_pattern):
    """构造 n 条已复盘记录: hits_pattern 为命中数列表（循环使用）"""
    return [
        {"lot": lot, "reviewed": True, "hits": hits_pattern[i % len(hits_pattern)],
         "scheme": "双色球" if i % 2 == 0 else "杀号方案"}
        for i in range(n)
    ]


def _run_refresh(tmpdir, reviews_by_lot, monkeypatch, existing_cards=None):
    fake = FakeCardStore()
    if existing_cards:
        fake._data["cards"] = existing_cards
    pred_file = os.path.join(tmpdir, "predictions.json")
    json.dump(reviews_by_lot, open(pred_file, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    monkeypatch.setattr(sc, "_PRED_FILE", pred_file)
    import knowledge.mirofish_db as mdb
    monkeypatch.setattr(mdb, "MiroFishDB", lambda: fake)
    result = sc.refresh_strategy_cards()
    return fake, result


# =========================================================================
# 纯统计函数
# =========================================================================

def test_stats_basic():
    reviews = _make_reviews("福彩3D", 20, [1, 0, 1, 1])
    st = sc._stats(reviews)
    assert st["n"] == 20
    assert st["avg_hits"] == 0.75
    assert abs(st["hit_rate"] - 0.75) < 1e-9
    assert abs(st["zero_rate"] - 0.25) < 1e-9
    assert "双色球" in st["by_scheme"] and "杀号方案" in st["by_scheme"]
    assert -1.0 <= st["trend"] <= 1.0


def test_stats_skip_small_scheme():
    """方案样本 < 3 条不进入 by_scheme（防止噪音）"""
    reviews = _make_reviews("福彩3D", 10, [1, 0])
    st = sc._stats(reviews)
    assert all(info["n"] >= 3 for info in st["by_scheme"].values())


def test_effectiveness_range():
    """effectiveness 强制落在 10~90 有效区间"""
    assert all(10 <= sc._eff_weight(st) <= 90 for st in [
        {"by_scheme": {"a": {"hit_rate": 0.0, "n": 3}}},
        {"by_scheme": {"a": {"hit_rate": 1.0, "n": 3}}},
    ])
    assert all(10 <= sc._eff_kill(st) <= 90 for st in [
        {"zero_rate": 0.0}, {"zero_rate": 1.0},
    ])
    assert all(10 <= sc._eff_miss(st) <= 90 for st in [
        {"trend": -1.0}, {"trend": 1.0}, {"trend": 0.0},
    ])


def test_eff_weight_neutral_without_schemes():
    assert sc._eff_weight({"by_scheme": {}}) == 50


# =========================================================================
# 提炼流程
# =========================================================================

def test_refresh_creates_cards(tmp_path, monkeypatch):
    """一个彩种 → 3 张挂钩卡（权重校准/杀号策略/遗漏突破）"""
    reviews = _make_reviews("福彩3D", 20, [1, 0, 1, 1])
    fake, result = _run_refresh(str(tmp_path), reviews, monkeypatch)

    assert len(result["created"]) == 3
    assert not result["skipped"]
    titles = {c["title"] for c in fake._data["cards"]}
    assert titles == {f"[策略] 福彩3D {label}" for label in ("权重校准", "杀号策略", "遗漏突破")}
    for c in fake._data["cards"]:
        assert c["engine_hook"] in sc.ALL_HOOKS
        assert 10 <= c["effectiveness"] <= 90
        assert "复盘数据自动提炼" in c["content"]
        assert c["subsystem"] == "lottery"
    assert fake.saved == 1, "应保存一次知识库"


def test_refresh_domain_mapping(tmp_path, monkeypatch):
    """福彩3D/排列三 → domain=3d；其他彩种 → domain=lottery"""
    reviews = (
        _make_reviews("福彩3D", 12, [1, 1, 1, 0]) +
        _make_reviews("快乐8", 12, [1, 1, 1, 0])
    )
    fake, _ = _run_refresh(str(tmp_path), reviews, monkeypatch)
    by_domain = {}
    for c in fake._data["cards"]:
        by_domain[c["title"]] = c["domain"]
    assert by_domain["[策略] 福彩3D 权重校准"] == "3d"
    assert by_domain["[策略] 快乐8 权重校准"] == "lottery"


def test_refresh_skips_low_sample(tmp_path, monkeypatch):
    """样本不足 10 条 → 跳过且不写卡"""
    reviews = _make_reviews("排列三", 5, [1, 0, 1, 1])
    fake, result = _run_refresh(str(tmp_path), reviews, monkeypatch)
    assert result["created"] == []
    assert len(result["skipped"]) == 1
    assert "样本5<10" in result["skipped"][0]
    assert fake._data["cards"] == []


def test_refresh_unreviewed_ignored(tmp_path, monkeypatch):
    """未复盘记录不参与统计"""
    reviews = [
        {"lot": "福彩3D", "reviewed": True, "hits": 1, "scheme": "a"},
    ] + [{"lot": "福彩3D", "reviewed": False, "hits": 5, "scheme": "b"}
         for _ in range(9)]
    fake, result = _run_refresh(str(tmp_path), reviews, monkeypatch)
    assert result["created"] == []
    assert len(result["skipped"]) == 1, "未复盘记录不计数，样本仍不足"


def test_refresh_updates_existing(tmp_path, monkeypatch):
    """同标题卡已存在 → 走更新路径（不改引擎挂钩）"""
    existing = [{
        "title": "[策略] 福彩3D 权重校准",
        "content": "旧内容", "effectiveness": 50,
        "engine_hook": sc.HOOK_WEIGHT, "domain": "3d",
    }]
    reviews = _make_reviews("福彩3D", 20, [1, 0, 1, 1])
    fake, result = _run_refresh(str(tmp_path), reviews, monkeypatch,
                                existing_cards=existing)

    assert len(result["updated"]) == 1
    assert len(result["created"]) == 2
    card = [c for c in fake._data["cards"] if c["title"] == "[策略] 福彩3D 权重校准"][0]
    assert card["effectiveness"] != 50, "effectiveness 应被新统计更新"
    assert card["engine_hook"] == sc.HOOK_WEIGHT
    assert "旧内容" not in card["content"]


def test_refresh_no_data(tmp_path, monkeypatch):
    """无复盘数据 → 空结果，不异常"""
    fake, result = _run_refresh(str(tmp_path), [], monkeypatch)
    assert result == {"created": [], "updated": [], "skipped": []}
    assert fake._data["cards"] == []


def test_ensure_initial_only_when_empty(tmp_path, monkeypatch):
    """已有挂钩卡时 ensure_initial 不重复提炼"""
    reviews = _make_reviews("福彩3D", 20, [1, 0, 1, 1])
    fake, _ = _run_refresh(str(tmp_path), reviews, monkeypatch)

    monkeypatch.setattr(sc, "refresh_strategy_cards",
                        lambda on_log=None: {"created": ["X"], "updated": [], "skipped": []})
    result = sc.ensure_initial_strategy_cards()
    assert result == {"created": [], "updated": [], "skipped": []}, "已有卡不应重复提炼"
