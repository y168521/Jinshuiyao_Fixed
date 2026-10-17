# -*- coding: utf-8 -*-
"""JS-20261017-03 · 多多视频带货 端到端自检脚本

走完整链路：选品过滤 → 脚本生成 → 合规闸 → 素材规格闸 → 拍摄清单 → 可发布判定。
不依赖 pytest，可独立运行；退出码 0 = 全链路通。

设计约束（对应项目铁律）：
  - 每一步都同时验「该拦的拦得住」和「不该拦的不误伤」
  - 无人脸检测能力时，露脸占比必须走人工申报三态，不得静默放过
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from domains.pdd_video.compliance import SEVERITY_BLOCK, ComplianceGuard  # noqa: E402
from domains.pdd_video.models import ProductItem, PublishTask, VideoAsset  # noqa: E402
from domains.pdd_video.product_filter import ProductFilter  # noqa: E402
from domains.pdd_video.script_builder import ScriptBuilder  # noqa: E402
from domains.pdd_video.shoot_checklist import ShootChecklist  # noqa: E402

FAILS = []
OKS = []


def check(name, cond, detail=""):
    if cond:
        OKS.append(name)
        print("  [OK] %s" % name)
    else:
        FAILS.append(name)
        print("  [FAIL] %s  %s" % (name, detail))


def main():
    guard = ComplianceGuard()
    pf = ProductFilter()
    sb = ScriptBuilder()
    cl = ShootChecklist()

    print("=" * 66)
    print("多多视频带货 · 端到端自检")
    print("=" * 66)

    # ---------- 环节 1：选品 ----------
    print("\n[1] 选品过滤")
    candidates = [
        ProductItem(goods_id="A", goods_name="家用五金工具箱套装", category="五金工具",
                    price=12.0, commission=3.0, brand="长城牌", spec="32件套",
                    is_standard=False, is_hot_boom=True, sales_30d=60),
        ProductItem(goods_id="B", goods_name="内存卡64G", category="数码配件",
                    price=18.0, commission=2.2, is_standard=False, is_hot_boom=True,
                    sales_30d=300),
        ProductItem(goods_id="C", goods_name="某品牌保健品", category="保健食品",
                    price=99.0, commission=8.0, is_standard=True, is_hot_boom=True),
        ProductItem(goods_id="D", goods_name="低价小商品", category="日用百货",
                    price=5.0, commission=0.8, is_standard=False, is_hot_boom=True),
    ]
    ranked = pf.filter(candidates)
    ids = [p.goods_id for p, _ in ranked]
    check("选品：保健品被淘汰", "C" not in ids, "实际入选 %s" % ids)
    check("选品：低佣品被淘汰", "D" not in ids, "实际入选 %s" % ids)
    check("选品：合格品保留", set(ids) == {"A", "B"}, "实际入选 %s" % ids)
    check("选品：按得分降序", ids == ["A", "B"], "实际顺序 %s" % ids)

    best = ranked[0][0]
    check("选品：最优品打了非标品+冷门标签",
          set(ranked[0][1].tags) >= {"非标品", "冷门"}, "tags=%s" % ranked[0][1].tags)

    # ---------- 环节 2：脚本生成 + 合规 ----------
    print("\n[2] 脚本生成与合规闸")
    d, v = sb.build_checked(best, ["铬钒钢扳手手感扎实", "箱子带锁能收纳"], guard=guard)
    check("脚本：三段式完整", bool(d.hook and d.body and d.cta))
    check("脚本：时长落在 15-60s", 15.0 <= d.est_duration_sec <= 60.0,
          "%.1fs" % d.est_duration_sec)
    check("脚本：含商品名", best.goods_name in d.full_text)
    blocks = [x for x in v if x.severity == SEVERITY_BLOCK]
    check("脚本：干净卖点无阻断项", not blocks, "%s" % blocks)

    # 反向：违规卖点必须被拦
    d2, v2 = sb.build_checked(best, ["质量最好", "全网第一"], guard=guard)
    check("脚本：极限词卖点被拦",
          any(x.severity == SEVERITY_BLOCK for x in v2), "未拦住")

    # ---------- 环节 3：素材规格闸 ----------
    print("\n[3] 素材规格闸")
    good_asset = VideoAsset(asset_id="A1", source="self_shot", duration_sec=45.0,
                            width=1080, height=1920, has_audio=True, shot_changes=4,
                            face_visible_ratio=0.6)
    bad_assets = {
        "时长过短": VideoAsset(asset_id="B1", source="self_shot", duration_sec=8.0,
                              width=1080, height=1920),
        "横屏": VideoAsset(asset_id="B2", source="self_shot", duration_sec=30.0,
                          width=1920, height=1080),
        "540P": VideoAsset(asset_id="B3", source="self_shot", duration_sec=30.0,
                          width=540, height=960),
        "无声": VideoAsset(asset_id="B4", source="self_shot", duration_sec=30.0,
                          width=1080, height=1920, has_audio=False),
        "搬运来源": VideoAsset(asset_id="B5", source="downloaded", duration_sec=30.0,
                             width=1080, height=1920),
    }
    for label, a in bad_assets.items():
        vv = guard.check_asset(a)
        check("素材：%s 被拦" % label,
              any(x.severity == SEVERITY_BLOCK for x in vv), "未拦住")
    check("素材：合规素材放行",
          not [x for x in guard.check_asset(good_asset) if x.severity == SEVERITY_BLOCK])

    # 露脸三态
    undetected = VideoAsset(asset_id="A2", source="self_shot", duration_sec=45.0,
                            width=1080, height=1920, face_visible_ratio=None)
    vu = guard.check_asset(undetected)
    check("露脸：未检测时明确告警（不静默放过）",
          any(x.rule == "face_ratio_undetected" for x in guard.is_publishable(
              PublishTask("T", "A", "A2", "t", "c", ad_label=True,
                          category="五金工具"), undetected, product=best)[1]))
    low_face = VideoAsset(asset_id="A3", source="self_shot", duration_sec=45.0,
                          width=1080, height=1920, face_visible_ratio=0.3)
    ok_low, vl = guard.is_publishable(
        PublishTask("T", "A", "A3", "t", "c", ad_label=True, category="五金工具"),
        low_face, product=best)
    check("露脸：低于 50% 判不可发布", not ok_low)

    # ---------- 环节 4：任务级 ----------
    print("\n[4] 任务级合规（广告标识 + 货不对板）")
    task_ok = PublishTask(task_id="T1", goods_id=best.goods_id, asset_id="A1",
                          title="家用五金工具箱", copy_text=d.full_text, tags=["五金"],
                          ad_label=True, category=best.category,
                          brand=best.brand, spec=best.spec)
    ok, v_ok = guard.is_publishable(task_ok, good_asset, product=best)
    check("任务：全合规可发布", ok, "%s" % [x.detail for x in v_ok
                                            if x.severity == SEVERITY_BLOCK])

    no_ad = PublishTask(task_id="T2", goods_id=best.goods_id, asset_id="A1",
                        title="工具箱", copy_text="好用", tags=[], ad_label=False,
                        category=best.category)
    ok2, v2b = guard.is_publishable(no_ad, good_asset, product=best)
    check("任务：未标广告被拦", not ok2 and
          any(x.rule == "ad_label_missing" for x in v2b))

    mismatch = PublishTask(task_id="T3", goods_id=best.goods_id, asset_id="A1",
                           title="工具箱", copy_text="好用", tags=[], ad_label=True,
                           category=best.category, brand="另一品牌", spec=best.spec)
    ok3, v3 = guard.is_publishable(mismatch, good_asset, product=best)
    check("任务：品牌货不对板被拦", not ok3 and
          any(x.rule == "brand_mismatch" for x in v3))

    # ---------- 环节 5：拍摄清单 ----------
    print("\n[5] 拍摄 / 自检清单")
    items = cl.items(best.category)
    checked = {i.key: True for i in items}
    res_all = cl.evaluate(checked=checked, category=best.category, face_ratio=0.6)
    check("清单：全勾选即通过", res_all.passed,
          "%s" % res_all.missing_blockers)
    res_none = cl.evaluate(checked={}, category=best.category, face_ratio=0.6)
    check("清单：全不勾被阻断", not res_none.passed and res_none.missing_blockers)
    res_face = cl.evaluate(checked=checked, category=best.category, face_ratio=None)
    check("清单：露脸未申报被阻断", not res_face.passed and
          any("露脸" in r for r in res_face.missing_blockers))
    res_exempt = cl.evaluate(checked=checked, category="宠物用品", face_ratio=None)
    check("清单：宠物类目豁免露脸", res_exempt.passed,
          "%s" % res_exempt.missing_blockers)

    # ---------- 汇总 ----------
    print("\n" + "=" * 66)
    print("通过 %d 项 / 失败 %d 项" % (len(OKS), len(FAILS)))
    if FAILS:
        print("失败项：%s" % FAILS)
    print("=" * 66)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
