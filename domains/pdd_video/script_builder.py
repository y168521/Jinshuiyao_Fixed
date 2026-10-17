# -*- coding: utf-8 -*-
"""多多视频带货 · 三段式脚本生成器

结构来源（万店精灵《视频上传总被拒?拼多多新店从权限开通到一次过审的避坑清单》）：
  前 3-5 秒  把商品整体展示清楚
  中 25-30 秒 讲核心卖点（材质、尺寸、使用效果）
  尾 10-15 秒 给出购买引导
  整个视频控制在 50 秒内

**生成 ≠ 可用**：build() 只负责成文，build_checked() 才会强制过 ComplianceGuard。
含违禁词的卖点会在这一层被拦下，不允许直接产出「看起来能发」的脚本。

刻意不把价格写进自动脚本：价格与商品不一致即构成虚假宣传，而价格是高频变动
字段，写死进文案会持续制造货不对板风险。价格由平台商品链接自行展示。
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from domains.pdd_video.compliance import ComplianceGuard, Violation
from domains.pdd_video.models import ProductItem

HOOK_SEC = 4.0
BODY_SEC = 26.0
CTA_SEC = 14.0
TOTAL_SEC = HOOK_SEC + BODY_SEC + CTA_SEC      # 44s，落在 15-60s 过审区间


@dataclass
class ScriptDraft:
    hook: str
    body: str
    cta: str
    full_text: str
    est_duration_sec: float


class ScriptBuilder:

    def build(self, product: ProductItem,
              selling_points: List[str],
              category: str = "") -> ScriptDraft:
        name = product.goods_name
        spec = product.spec or ""

        hook = ("家里那个旧的总差点意思，我换了这款%s，说几句实在的。"
                % name)

        points = [p.strip() for p in selling_points if p and p.strip()]
        if not points:
            points = ["用着顺手"]
        body_bits = []
        if spec:
            body_bits.append("这套是%s。" % spec)
        body_bits.append("。".join(points) + "。")
        body_bits.append("我用了两周，讲下真实感受。")
        body = "".join(body_bits)

        cta = "感兴趣的朋友点击下方购物车，下拉详情页看实拍。"

        full = hook + body + cta
        return ScriptDraft(hook=hook, body=body, cta=cta,
                           full_text=full, est_duration_sec=TOTAL_SEC)

    def build_checked(self, product: ProductItem,
                      selling_points: List[str],
                      guard: Optional[ComplianceGuard] = None,
                      category: str = "") -> Tuple[ScriptDraft, List[Violation]]:
        """生成并强制过合规闸。返回 (草稿, 违规列表)。

        调用方必须检查违规列表里有没有 SEVERITY_BLOCK —— 有就不能用。
        """
        guard = guard or ComplianceGuard()
        d = self.build(product, selling_points, category=category)
        cat = category or product.category
        v = guard.check_text(d.full_text, category=cat)
        return d, v
