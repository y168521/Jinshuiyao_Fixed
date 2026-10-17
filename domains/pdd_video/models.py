# -*- coding: utf-8 -*-
"""多多视频带货 · 数据模型

纯数据结构，零第三方依赖。所有字段默认值都取「安全侧」——
例如 VideoAsset.face_visible_ratio 默认 None 表示「未检测」，
调用方必须显式区分「检测为 0」与「没测」，不得把 None 当成合格
（这是本项目反复吃亏的静默失败模式）。
"""
from dataclasses import dataclass, field
from typing import List, Optional


# 素材来源白名单：只允许原创/自制/授权三种，其余一律视为不可发布
LEGAL_ASSET_SOURCES = ("original", "self_shot", "licensed")


@dataclass
class ProductItem:
    """候选带货商品"""

    goods_id: str
    goods_name: str
    category: str
    price: float
    commission: float                     # 单件佣金（元），非比率
    brand: str = ""
    spec: str = ""
    sales_30d: int = 0                    # 近 30 天销量，用于判断冷门程度
    is_standard: bool = True              # True=标品（易与他人素材重复）/ False=非标品
    is_hot_boom: bool = False             # 是否在「热门爆款」池内
    mall_name: str = ""


@dataclass
class VideoAsset:
    """视频素材（自检结果的载体）

    face_visible_ratio: 真人露脸时长占比，0.0~1.0。
        None = 未检测（环境无 cv2/ffmpeg，工具测不了，必须由人工申报）
        这是显式三态，绝不用 0.0 冒充「未检测」。
    """

    asset_id: str
    source: str                           # 必须 ∈ LEGAL_ASSET_SOURCES
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    has_audio: bool = True
    shot_changes: int = 0                 # 镜头切换次数，0 = 一镜到底
    black_bars: bool = False
    ai_generated: bool = False
    face_visible_ratio: Optional[float] = None
    license_note: str = ""


@dataclass
class PublishTask:
    """一次发布任务"""

    task_id: str
    goods_id: str
    asset_id: str
    title: str
    copy_text: str
    tags: List[str] = field(default_factory=list)
    ad_label: bool = False                # 是否已显著标明「广告」
    category: str = ""
    brand: str = ""
    spec: str = ""
    status: str = "draft"                 # draft/submitted/approved/rejected
    feeds_id: str = ""
    reject_reason: str = ""


@dataclass
class ScriptDraft:
    """三段式脚本草稿"""

    hook: str          # 前 3-5 秒：抓注意力 + 商品整体亮相
    body: str          # 中 25-30 秒：核心卖点
    cta: str           # 尾 10-15 秒：购买引导
    full_text: str
    est_duration_sec: float
