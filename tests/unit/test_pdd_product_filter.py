# -*- coding: utf-8 -*-
"""JS-20261017-03 · 多多视频选品过滤器单测

覆盖 domains/pdd_video/product_filter.py。
选品是「高质量过审」的第一道闸：冷门非标品不易与他人素材重复，
这是原创路线能过审的前提。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from domains.pdd_video.models import ProductItem  # noqa: E402
from domains.pdd_video.product_filter import ProductFilter  # noqa: E402


@pytest.fixture
def f():
    return ProductFilter(min_commission=2.0, max_price=20.0, require_hot_boom=True)


def _p(**kw):
    base = dict(goods_id="G1", goods_name="测试商品", category="五金工具",
                price=15.0, commission=2.5, sales_30d=200, is_standard=False,
                is_hot_boom=True)
    base.update(kw)
    return ProductItem(**base)


# ----------------------------------------------------------------------
# 硬闸门：不满足必须淘汰
# ----------------------------------------------------------------------

def test_rejects_below_min_commission(f):
    res = f.score(_p(commission=1.2))
    assert not res.passed
    assert any("佣金" in r for r in res.reasons)


def test_rejects_blocked_category(f):
    res = f.score(_p(category="保健食品"))
    assert not res.passed
    assert any("禁发" in r or "类目" in r for r in res.reasons)


def test_rejects_review_required_category(f):
    """需前置审查类目直接淘汰（无资质不该碰）"""
    res = f.score(_p(category="医疗器械"))
    assert not res.passed


def test_rejects_not_hot_boom_when_required(f):
    res = f.score(_p(is_hot_boom=False))
    assert not res.passed
    assert any("热门爆款" in r for r in res.reasons)


def test_allows_not_hot_boom_when_not_required():
    f2 = ProductFilter(require_hot_boom=False)
    assert f2.score(_p(is_hot_boom=False)).passed


def test_rejects_oversize_price(f):
    res = f.score(_p(price=68.0))
    assert not res.passed
    assert any("价格" in r for r in res.reasons)


# ----------------------------------------------------------------------
# 软评分：冷门非标品应得高分（这是过审率的核心变量）
# ----------------------------------------------------------------------

def test_non_standard_scores_higher_than_standard(f):
    non_std = f.score(_p(is_standard=False, sales_30d=100))
    std = f.score(_p(is_standard=True, sales_30d=100))
    assert non_std.score > std.score, \
        "非标品（不易与他人素材重复）未获加分：%s vs %s" % (non_std.score, std.score)


def test_low_sales_scores_higher_than_hot(f):
    cold = f.score(_p(sales_30d=50))
    hot = f.score(_p(sales_30d=50000))
    assert cold.score > hot.score, "冷门品未获加分：%s vs %s" % (cold.score, hot.score)


def test_ideal_product_scores_high(f):
    res = f.score(_p(price=12.0, commission=3.0, sales_30d=80, is_standard=False))
    assert res.score >= 70, "理想冷门非标品得分过低：%s" % res.score


# ----------------------------------------------------------------------
# 防误伤：合规好产品绝不能被筛掉
# ----------------------------------------------------------------------

def test_good_product_not_filtered_out(f):
    """反向验证：若评分逻辑写反，好产品会被误杀"""
    good = _p(goods_id="OK1", price=9.9, commission=2.8, sales_30d=60, is_standard=False)
    res = f.score(good)
    assert res.passed, "合规好产品被误杀：%s" % res.reasons
    assert res.score > 0


def test_filter_returns_sorted_by_score(f):
    products = [
        _p(goods_id="A", price=12.0, commission=3.0, sales_30d=50, is_standard=False),
        _p(goods_id="B", price=18.0, commission=2.1, sales_30d=9000, is_standard=True),
        _p(goods_id="C", price=15.0, commission=2.5, sales_30d=300, is_standard=False),
    ]
    out = f.filter(products)
    assert [p.goods_id for p, _ in out] == ["A", "C", "B"], \
        "未按得分降序：%s" % ([p.goods_id for p, _ in out],)


def test_filter_drops_failed(f):
    products = [_p(goods_id="A"), _p(goods_id="B", commission=0.5), _p(goods_id="C")]
    out = f.filter(products)
    ids = [p.goods_id for p, _ in out]
    assert "B" not in ids
    assert len(ids) == 2


# ----------------------------------------------------------------------
# 反向验证：过滤器不是永远放行
# ----------------------------------------------------------------------

def test_filter_not_always_pass(f):
    """若硬闸门失效，所有产品都会 passed —— 用一批明确不合格产品证明闸门活着"""
    bad = [
        _p(goods_id="X1", commission=0.1),          # 佣金不足
        _p(goods_id="X2", category="处方药"),        # 禁发类目
        _p(goods_id="X3", price=999.0),              # 超价
        _p(goods_id="X4", is_hot_boom=False),        # 非热门爆款
    ]
    for p in bad:
        assert not f.score(p).passed, "不合格产品「%s」被放行" % p.goods_id
