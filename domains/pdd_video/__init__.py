# -*- coding: utf-8 -*-
"""多多视频带货子系统（Jinshuiyao · pdd_video）

定位：**合规的选品 + 文案 + 自检辅助工具**，不是批量搬运发片器。

设计边界（对应 JS-20261017-03「高质量过审」方案）：
  - 能自动化的：选品过滤、脚本生成、合规闸、规格自检、清单打分、发布台账
  - 必须人工的：真人出镜拍摄、商品到手、露脸时长申报
  - 数据结构层面不支持：多账号矩阵、素材搬运

零第三方依赖：所有模块只用标准库，视频/人脸分析留给后续显式接入
（接入时必须走「未检测」三态，不得静默降级）。
"""
from domains.pdd_video.models import (  # noqa: F401
    LEGAL_ASSET_SOURCES,
    ProductItem,
    PublishTask,
    ScriptDraft,
    VideoAsset,
)
from domains.pdd_video.compliance import (  # noqa: F401
    SEVERITY_BLOCK,
    SEVERITY_WARN,
    ComplianceGuard,
    Violation,
)
from domains.pdd_video.product_filter import ProductFilter, FilterResult  # noqa: F401
from domains.pdd_video.script_builder import ScriptBuilder  # noqa: F401
from domains.pdd_video.shoot_checklist import ShootChecklist, ChecklistResult  # noqa: F401

__all__ = [
    "LEGAL_ASSET_SOURCES", "ProductItem", "PublishTask", "ScriptDraft", "VideoAsset",
    "SEVERITY_BLOCK", "SEVERITY_WARN", "ComplianceGuard", "Violation",
    "ProductFilter", "FilterResult", "ScriptBuilder",
    "ShootChecklist", "ChecklistResult",
]
