# -*- coding: utf-8 -*-
"""多多视频带货 · 选品过滤器

为什么选品是第一道闸：
  原创实拍路线要过审，最大风险是「素材与他人重复」被平台判同质化。
  冷门非标品（农用工具、五金、电器、毛绒娃娃、轮胎、袜子、内存卡等）
  发的人少、链接多、不要求品牌外观一致，是原创路线唯一能规模化过审的品类带。

来源：
  - 起点8「选择冷门商品是关键……这类商品发的人少，不容易重复，因此更容易通过审核」
  - 亿邦动力「除宠物、居家以及部分美食种草内容外，其他品类都需要真人出镜」
  - 爱企查「拼多多佣金大多不高，多数商品一两元左右……佣金需每单至少 2 元以上更佳」
  - 淘客Show「选择合适价格的产品……价格最好在 0-20 元之间，这样比较容易出单」
  - 万店精灵「避免选择食品类（通过率低）」
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from domains.pdd_video.models import ProductItem

# 直接淘汰的类目（含需前置审查资质与低通过率品类）
# 来源：《互联网广告管理办法》第六/七/十二条 + 万店精灵「食品类通过率低」
BLOCKED_CATEGORIES = [
    "烟草", "电子烟", "处方药", "医疗", "药品", "医疗器械",
    "保健食品", "特殊医学用途配方食品", "农药", "兽药",
    "化妆品", "酒类", "美容", "教育培训", "减肥", "丰胸", "增高", "医美",
    "食品", "生鲜", "保健品",
]


@dataclass
class FilterResult:
    passed: bool
    score: float
    reasons: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class ProductFilter:
    """硬闸门（淘汰）+ 软评分（排序）

    硬闸门不满足 → passed=False，直接淘汰，不进候选。
    软评分只影响排序，不影响去留 —— 这样「合格但不够好」与「不合格」不会混淆。
    """

    def __init__(self,
                 min_commission: float = 2.0,
                 max_price: float = 20.0,
                 require_hot_boom: bool = True,
                 blocked_categories: Optional[List[str]] = None):
        self.min_commission = min_commission
        self.max_price = max_price
        self.require_hot_boom = require_hot_boom
        self.blocked_categories = blocked_categories or BLOCKED_CATEGORIES

    # ------------------------------------------------------------------

    def _hard_gates(self, p: ProductItem) -> List[str]:
        reasons = []
        if p.commission < self.min_commission:
            reasons.append("佣金不足：%.2f 元 < %.2f 元（社区经验：单均佣金至少 2 元更优）"
                           % (p.commission, self.min_commission))
        for c in self.blocked_categories:
            if c in p.category:
                reasons.append("类目「%s」在黑名单内（禁发/需前置审查/通过率低）" % p.category)
                break
        if self.require_hot_boom and not p.is_hot_boom:
            reasons.append("不在「热门爆款」池内（平台任务要求从热门爆款选品）")
        if p.price <= 0:
            reasons.append("价格异常：%s" % p.price)
        elif p.price > self.max_price:
            reasons.append("价格 %.1f 元超出 0-%.0f 元区间（低价品更容易出单）"
                           % (p.price, self.max_price))
        return reasons

    def _soft_score(self, p: ProductItem) -> Tuple[float, List[str]]:
        score = 40.0
        tags = []

        # 非标品：不易与他人素材重复，是过审率的核心变量
        if not p.is_standard:
            score += 20
            tags.append("非标品")
        # 冷门：发的人少，重复风险低
        if p.sales_30d < 500:
            score += 15
            tags.append("冷门")
        elif p.sales_30d < 5000:
            score += 8
            tags.append("次冷门")
        # 价格带
        if 0 < p.price <= 15:
            score += 10
            tags.append("低价带")
        elif p.price <= self.max_price:
            score += 5
        # 佣金厚度
        if p.commission >= self.min_commission * 1.5:
            score += 10
            tags.append("高佣")
        if p.is_hot_boom:
            score += 5

        return min(score, 100.0), tags

    # ------------------------------------------------------------------

    def score(self, p: ProductItem) -> FilterResult:
        reasons = self._hard_gates(p)
        if reasons:
            return FilterResult(passed=False, score=0.0, reasons=reasons, tags=[])
        s, tags = self._soft_score(p)
        return FilterResult(passed=True, score=s, reasons=[], tags=tags)

    def filter(self, products: List[ProductItem]) -> List[Tuple[ProductItem, FilterResult]]:
        """返回 [(商品, 结果), ...] 按得分降序；不合格的已剔除"""
        out = []
        for p in products:
            r = self.score(p)
            if r.passed:
                out.append((p, r))
        out.sort(key=lambda x: (-x[1].score, x[0].goods_id))
        return out
