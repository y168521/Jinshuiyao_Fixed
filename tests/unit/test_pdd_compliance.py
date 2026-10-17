# -*- coding: utf-8 -*-
"""JS-20261017-03 · 多多视频带货合规守卫单测

覆盖 domains/pdd_video/compliance.py。
每个守卫必须同时有「拦得住」与「不误伤」两类断言 —— 只测正向会让闸门退化成
永远放行（项目铁律：一个永远绿的闸可能是逻辑错了或根本没扫到目标）。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from domains.pdd_video.compliance import (  # noqa: E402
    SEVERITY_BLOCK,
    SEVERITY_WARN,
    ComplianceGuard,
)
from domains.pdd_video.models import ProductItem, PublishTask, VideoAsset  # noqa: E402


@pytest.fixture
def guard():
    return ComplianceGuard()


@pytest.fixture
def product():
    return ProductItem(
        goods_id="G001",
        goods_name="家用五金工具箱套装",
        category="五金工具",
        price=19.9,
        commission=2.5,
        brand="长城牌",
        spec="32件套",
        is_standard=False,
        is_hot_boom=True,
    )


# ----------------------------------------------------------------------
# 一、文本类守卫：必须拦得住
# ----------------------------------------------------------------------

@pytest.mark.parametrize("word", ["最好", "第一", "全网最低价", "国家级", "永久", "终身", "独家"])
def test_blocks_extreme_words(guard, word):
    v = guard.check_text("这个工具箱质量%s，大家放心买。" % word)
    assert any(x.severity == SEVERITY_BLOCK and x.rule == "extreme_word" for x in v), \
        "极限词「%s」未被拦截" % word


@pytest.mark.parametrize("phrase", ["三天祛痘", "根治", "药到病除", "保证有效", "无效退款"])
def test_blocks_overclaim(guard, phrase):
    v = guard.check_text("用了它%s，效果特别好。" % phrase)
    assert any(x.severity == SEVERITY_BLOCK for x in v), "过度承诺「%s」未被拦截" % phrase


@pytest.mark.parametrize("phrase", ["来我小黄车直接下单", "加微信", "加V", "抖音同款", "扫码领券"])
def test_blocks_third_party_drain(guard, phrase):
    v = guard.check_text("这款很好用，%s。" % phrase)
    assert any(x.severity == SEVERITY_BLOCK and x.rule == "third_party_drain" for x in v), \
        "引流信息「%s」未被拦截" % phrase


def test_allows_official_purchase_guide(guard):
    """平台允许的购买引导不得被误伤（防误伤断言）"""
    for phrase in ["点击下方购物车", "下拉详情页看实拍", "点击左下角链接"]:
        v = guard.check_text("感兴趣的朋友%s。" % phrase)
        blocks = [x for x in v if x.severity == SEVERITY_BLOCK]
        assert not blocks, "官方允许的购买引导「%s」被误拦：%s" % (phrase, blocks)


def test_clean_text_has_no_violation(guard):
    """干净文案必须零违规 —— 否则闸门没意义"""
    text = ("家里工具箱老是缺件，我换了这套32件套。"
            "扳手是铬钒钢的，手感扎实，箱子能锁。"
            "用了两周，修椅子修柜门都够用。"
            "点击下方购物车。")
    v = guard.check_text(text)
    assert v == [], "干净文案被误报：%s" % v


# ----------------------------------------------------------------------
# 二、类目守卫
# ----------------------------------------------------------------------

@pytest.mark.parametrize("cat", ["保健食品", "处方药", "医疗器械", "烟草", "电子烟", "农药"])
def test_blocks_banned_categories(guard, cat):
    v = guard.check_text("推荐一款商品", category=cat)
    assert any(x.severity == SEVERITY_BLOCK and x.rule == "banned_category" for x in v), \
        "禁发类目「%s」未被拦截" % cat


def test_warns_review_required_category(guard):
    """需前置审查类目：WARN 而非 BLOCK（由人工确认资质）"""
    v = guard.check_text("推荐一款面霜", category="化妆品")
    assert any(x.severity == SEVERITY_WARN and x.rule == "review_required_category" for x in v)
    assert not any(x.severity == SEVERITY_BLOCK for x in v)


# ----------------------------------------------------------------------
# 三、任务级守卫：广告标识 + 货不对板
# ----------------------------------------------------------------------

def test_requires_ad_label(guard, product):
    task = PublishTask(task_id="T1", goods_id=product.goods_id, asset_id="A1",
                       title="家用工具箱", copy_text="很好用", tags=[], ad_label=False)
    v = guard.check_task(task, product=product)
    assert any(x.severity == SEVERITY_BLOCK and x.rule == "ad_label_missing" for x in v)


def test_ad_label_present_passes(guard, product):
    task = PublishTask(task_id="T1", goods_id=product.goods_id, asset_id="A1",
                       title="家用工具箱", copy_text="很好用", tags=[], ad_label=True,
                       category=product.category)
    v = guard.check_task(task, product=product)
    assert not any(x.severity == SEVERITY_BLOCK for x in v), "已标广告仍被拦：%s" % v


def test_blocks_brand_mismatch(guard, product):
    """货不对板：文案写的品牌与商品不一致 → 虚假宣传"""
    task = PublishTask(task_id="T1", goods_id=product.goods_id, asset_id="A1",
                       title="工具箱", copy_text="很好用", tags=[], ad_label=True,
                       category=product.category, brand="另一品牌")
    v = guard.check_task(task, product=product)
    assert any(x.severity == SEVERITY_BLOCK and x.rule == "brand_mismatch" for x in v)


def test_blocks_spec_mismatch(guard, product):
    task = PublishTask(task_id="T1", goods_id=product.goods_id, asset_id="A1",
                       title="工具箱", copy_text="很好用", tags=[], ad_label=True,
                       category=product.category, brand=product.brand, spec="65件套")
    v = guard.check_task(task, product=product)
    assert any(x.severity == SEVERITY_BLOCK and x.rule == "spec_mismatch" for x in v)


# ----------------------------------------------------------------------
# 四、素材来源守卫
# ----------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["downloaded", "repost", "搬运", "unknown", ""])
def test_blocks_illegal_asset_source(guard, bad):
    asset = VideoAsset(asset_id="A1", source=bad, duration_sec=30.0,
                       width=1080, height=1920)
    v = guard.check_asset(asset)
    assert any(x.severity == SEVERITY_BLOCK and x.rule == "illegal_asset_source" for x in v), \
        "非法素材来源「%s」未被拦截" % bad


@pytest.mark.parametrize("good", ["original", "self_shot", "licensed"])
def test_allows_legal_asset_source(guard, good):
    asset = VideoAsset(asset_id="A1", source=good, license_note="自有" if good == "licensed" else "",
                       duration_sec=30.0, width=1080, height=1920)
    v = guard.check_asset(asset)
    assert not any(x.severity == SEVERITY_BLOCK for x in v), "合法来源「%s」被误拦：%s" % (good, v)


def test_licensed_source_requires_note(guard):
    asset = VideoAsset(asset_id="A1", source="licensed", license_note="",
                       duration_sec=30.0, width=1080, height=1920)
    v = guard.check_asset(asset)
    assert any(x.severity == SEVERITY_BLOCK and x.rule == "license_note_missing" for x in v)


# ----------------------------------------------------------------------
# 五、素材规格守卫（时长 / 竖屏 / 分辨率 / 有声）
# ----------------------------------------------------------------------

def test_blocks_too_short(guard):
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=8.0,
                       width=1080, height=1920)
    v = guard.check_asset(asset)
    assert any(x.rule == "duration_too_short" for x in v)


def test_blocks_too_long(guard):
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=400.0,
                       width=1080, height=1920)
    v = guard.check_asset(asset)
    assert any(x.rule == "duration_too_long" for x in v)


def test_blocks_landscape(guard):
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=30.0,
                       width=1920, height=1080)
    v = guard.check_asset(asset)
    assert any(x.rule == "not_portrait" for x in v)


def test_blocks_low_resolution(guard):
    """540P 是平台明文点名的驳回案例（系统检测分辨率只有 540P）"""
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=30.0,
                       width=540, height=960)
    v = guard.check_asset(asset)
    assert any(x.rule == "low_resolution" for x in v)


def test_allows_720p(guard):
    """防误伤：720×1280 就是合规的 720P，不得判低清"""
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=30.0,
                       width=720, height=1280, shot_changes=2)
    v = guard.check_asset(asset)
    assert not any(x.severity == SEVERITY_BLOCK for x in v), "合规 720P 被误拦：%s" % v


def test_blocks_silent(guard):
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=30.0,
                       width=1080, height=1920, has_audio=False)
    v = guard.check_asset(asset)
    assert any(x.rule == "no_audio" for x in v)


def test_warns_single_shot(guard):
    """无镜头切换：WARN（平台要求有明显镜头切换，但不一定驳回）"""
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=30.0,
                       width=1080, height=1920, shot_changes=0)
    v = guard.check_asset(asset)
    assert any(x.severity == SEVERITY_WARN and x.rule == "no_shot_change" for x in v)


def test_warns_black_bars(guard):
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=30.0,
                       width=1080, height=1920, black_bars=True)
    v = guard.check_asset(asset)
    assert any(x.rule == "black_bars" for x in v)


# ----------------------------------------------------------------------
# 六、反向验证：闸门必须真的在扫目标
# ----------------------------------------------------------------------

def test_gate_reverse_verification(guard):
    """反向验证：把一条干净文案逐个注入违规词，闸门必须逐个抓到。

    只跑正向（违规被拦）不够 —— 若规则表为空、check_text 直接 return []，
    正向测试会全绿而闸门实际是死的。这里用「干净文案 + 逐个注入」证明
    规则表非空且每个词真的命中。
    """
    clean = "家里工具箱缺件，换了这套32件套，铬钒钢扳手手感扎实。点击下方购物车。"
    assert guard.check_text(clean) == []

    for word in ["最好", "第一", "小黄车", "加微信", "根治"]:
        poisoned = clean.replace("点击下方购物车", word + "，点击下方购物车")
        v = guard.check_text(poisoned)
        assert any(x.severity == SEVERITY_BLOCK for x in v), \
            "反向验证失败：注入「%s」后闸门未报警（规则表可能为空）" % word


def test_gate_not_always_red(guard):
    """正向验证：同一条干净文案连续检查都必须是零违规（防永远红）"""
    for _ in range(3):
        assert guard.check_text("五金工具很好用，点击下方购物车。") == []


# ----------------------------------------------------------------------
# 八、坑变检查：规则表不得为空
# ----------------------------------------------------------------------

def test_rule_tables_not_empty():
    """坑变检查（不只写进记忆，落成闸）

    风险场景：有人「清理」规则表时把列表清空 → 正向测试（违规被拦）会全部
    因断言条件不满足而**报错**，但若清理时连测试一起删，闸门就静默死亡，
    表现为「什么都放行」且无人报警。

    这里用反射扫 compliance 模块所有规则表常量，断言全部非空。
    """
    from domains.pdd_video import compliance as C
    tables = []
    for name in dir(C):
        if not name.isupper():
            continue
        val = getattr(C, name)
        if isinstance(val, list) and name.endswith(("WORDS", "PHRASES", "DRAIN", "CATEGORIES")):
            tables.append(name)
            assert val, "规则表 %s 为空 —— 闸门已静默失效" % name
    # 自检：扫描本身必须真的找到了规则表，否则这条检查是空转
    assert len(tables) >= 5, "只找到 %d 张规则表（%s），扫描口径可能失效" % (len(tables), tables)


# ----------------------------------------------------------------------
# 七、可发布性判定
# ----------------------------------------------------------------------

def test_is_publishable_all_clear(guard, product):
    asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=45.0,
                       width=1080, height=1920, shot_changes=4)
    task = PublishTask(task_id="T1", goods_id=product.goods_id, asset_id="A1",
                       title="家用五金工具箱", copy_text="缺件就换这套，铬钒钢的。",
                       tags=["五金"], ad_label=True, category=product.category,
                       brand=product.brand, spec=product.spec)
    ok, violations = guard.is_publishable(task, asset, product=product)
    assert ok, "全部合规却判定不可发布：%s" % violations
    assert not [x for x in violations if x.severity == SEVERITY_BLOCK]


def test_is_publishable_blocked_by_asset(guard, product):
    asset = VideoAsset(asset_id="A1", source="downloaded", duration_sec=45.0,
                       width=1080, height=1920)
    task = PublishTask(task_id="T1", goods_id=product.goods_id, asset_id="A1",
                       title="工具箱", copy_text="好用", tags=[], ad_label=True,
                       category=product.category)
    ok, violations = guard.is_publishable(task, asset, product=product)
    assert not ok
    assert any(x.rule == "illegal_asset_source" for x in violations)
