# -*- coding: utf-8 -*-
"""JS-20261017-03 · 三段式脚本生成 + 拍摄自检清单单测

覆盖 domains/pdd_video/script_builder.py 与 shoot_checklist.py。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from domains.pdd_video.compliance import SEVERITY_BLOCK, ComplianceGuard  # noqa: E402
from domains.pdd_video.models import ProductItem  # noqa: E402
from domains.pdd_video.script_builder import ScriptBuilder  # noqa: E402
from domains.pdd_video.shoot_checklist import ShootChecklist  # noqa: E402


@pytest.fixture
def product():
    return ProductItem(goods_id="G1", goods_name="家用五金工具箱套装",
                       category="五金工具", price=19.9, commission=2.5,
                       brand="长城牌", spec="32件套", is_standard=False,
                       is_hot_boom=True)


@pytest.fixture
def builder():
    return ScriptBuilder()


@pytest.fixture
def guard():
    return ComplianceGuard()


@pytest.fixture
def checklist():
    return ShootChecklist()


# ----------------------------------------------------------------------
# 脚本生成：三段式结构 + 时长落在过审区间
# ----------------------------------------------------------------------

def test_script_has_three_sections(builder, product):
    d = builder.build(product, selling_points=["铬钒钢扳手", "箱子能锁"])
    assert d.hook and d.body and d.cta, "三段式不完整"
    assert d.hook != d.body != d.cta


def test_script_duration_within_review_window(builder, product):
    """平台要求带货视频 15s–60s（最佳 15–60s），脚本预估时长必须落在区间内"""
    d = builder.build(product, selling_points=["扳手是铬钒钢的", "箱子能锁"])
    assert 15.0 <= d.est_duration_sec <= 60.0, \
        "预估时长 %s 不在过审区间 15-60s" % d.est_duration_sec


def test_script_full_text_contains_product_name(builder, product):
    d = builder.build(product, selling_points=["手感扎实"])
    assert product.goods_name in d.full_text


def test_script_cta_uses_allowed_phrase(builder, product):
    """CTA 必须用平台允许的购买引导，不得出现引流词"""
    d = builder.build(product, selling_points=["手感扎实"])
    assert "购物车" in d.cta or "详情页" in d.cta
    for bad in ["小黄车", "加微信", "抖音"]:
        assert bad not in d.full_text


# ----------------------------------------------------------------------
# 脚本必须过合规闸（关键：生成 ≠ 可用）
# ----------------------------------------------------------------------

def test_script_rejects_illegal_selling_point(builder, guard, product):
    """卖点里含极限词 → 生成后必须被闸门拦下，不允许直接产出可用脚本"""
    d, violations = builder.build_checked(product, ["质量最好", "全网第一"], guard=guard)
    assert any(v.severity == SEVERITY_BLOCK for v in violations), \
        "含极限词卖点未被拦：%s" % violations


def test_script_clean_selling_point_passes(builder, guard, product):
    d, violations = builder.build_checked(product, ["铬钒钢材质", "箱子带锁"], guard=guard)
    assert not [v for v in violations if v.severity == SEVERITY_BLOCK], \
        "干净卖点被误拦：%s" % violations


def test_builder_not_always_pass(builder, guard, product):
    """反向验证：build_checked 不能对所有输入都放行"""
    _, bad = builder.build_checked(product, ["三天祛痘", "根治"], guard=guard)
    assert any(v.severity == SEVERITY_BLOCK for v in bad)
    _, good = builder.build_checked(product, ["材质扎实"], guard=guard)
    assert not [v for v in good if v.severity == SEVERITY_BLOCK]


def test_builder_refuses_banned_category(builder, product):
    """禁发类目不得生成脚本"""
    p = ProductItem(goods_id="G2", goods_name="某保健食品", category="保健食品",
                    price=99.0, commission=5.0)
    d, violations = builder.build_checked(p, ["效果好"], guard=ComplianceGuard())
    assert any(v.rule == "banned_category" for v in violations)


# ----------------------------------------------------------------------
# 拍摄自检清单：露脸 >50% 是硬门槛（除豁免类目）
# ----------------------------------------------------------------------

def test_checklist_requires_face_ratio_for_most_categories(checklist):
    res = checklist.evaluate(checked={}, category="五金工具", face_ratio=None)
    assert not res.passed
    assert any("露脸" in r for r in res.missing_blockers)


def test_checklist_face_ratio_below_half_blocked(checklist):
    res = checklist.evaluate(checked={}, category="五金工具", face_ratio=0.3)
    assert not res.passed
    assert any("露脸" in r for r in res.missing_blockers)


@pytest.mark.parametrize("cat", ["宠物", "居家", "美食"])
def test_checklist_face_ratio_exempt_categories(checklist, cat):
    """宠物/居家/部分美食豁免露脸要求（不得误伤）"""
    res = checklist.evaluate(checked={}, category=cat, face_ratio=None)
    assert not any("露脸" in r for r in res.missing_blockers), \
        "豁免类目「%s」被误要求露脸" % cat


def test_checklist_all_clear_passes(checklist):
    checked = {i.key: True for i in checklist.items("五金工具")}
    res = checklist.evaluate(checked=checked, category="五金工具", face_ratio=0.6)
    assert res.passed, "全部勾选仍不通过：%s / %s" % (res.missing_blockers, res.missing_warnings)


def test_checklist_missing_critical_blocks(checklist):
    res = checklist.evaluate(checked={}, category="五金工具", face_ratio=0.6)
    assert not res.passed
    assert len(res.missing_blockers) > 0


def test_checklist_warns_not_block(checklist):
    """WARN 级项缺失不得阻断（否则清单退化为全有或全无）"""
    items = checklist.items("五金工具")
    warn_keys = [i.key for i in items if i.severity == "warn"]
    assert warn_keys, "清单里没有任何 WARN 级项，分级失效"
    checked = {i.key: True for i in items}
    for k in warn_keys:
        checked[k] = False
    res = checklist.evaluate(checked=checked, category="五金工具", face_ratio=0.6)
    assert res.passed, "仅缺 WARN 项却被阻断"
    assert res.missing_warnings


def test_checklist_items_carry_source(checklist):
    """每个清单项必须带来源标注（外部规则不可无出处）"""
    for i in checklist.items("五金工具"):
        assert i.source, "清单项 %s 无来源标注" % i.key


# ----------------------------------------------------------------------
# 端到端：选品 → 脚本 → 过闸 → 清单 全链路
# ----------------------------------------------------------------------

def test_end_to_end_happy_path(builder, guard, checklist):
    p = ProductItem(goods_id="G1", goods_name="家用五金工具箱套装", category="五金工具",
                    price=19.9, commission=2.5, brand="长城牌", spec="32件套",
                    is_standard=False, is_hot_boom=True)
    d, v1 = builder.build_checked(p, ["铬钒钢扳手手感扎实", "箱子带锁能收纳"], guard=guard)
    assert not [x for x in v1 if x.severity == SEVERITY_BLOCK]

    checked = {i.key: True for i in checklist.items("五金工具")}
    res = checklist.evaluate(checked=checked, category="五金工具", face_ratio=0.6)
    assert res.passed
