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
from domains.pdd_video.harvest import (  # noqa: F401
    ERROR_CODES,
    ITEM_STATUSES,
    SCOPE_MODES,
    STATUS_FETCH_FAILED,
    STATUS_HAS_VIDEO,
    STATUS_NO_VIDEO,
    STATUS_OUT_OF_SCOPE,
    STATUS_READY,
    ApiGoodsVideoSource,
    FetchError,
    FFmpegMissingError,
    GoodsVideoRef,
    HarvestItem,
    Harvester,
    HarvestReport,
    HarvestScope,
    ManifestGoodsVideoSource,
    NormalizedAsset,
    ProcessError,
    RightsViolationError,
    VideoFetcher,
    VideoMeta,
    VideoNormalizer,
)
from domains.pdd_video.material_source import (  # noqa: F401
    LICENSE_REQUIRES_EVIDENCE,
    LICENSE_TYPES,
    LicenseError,
    MaterialRecord,
    MaterialRegistry,
)

__all__ = [
    "LEGAL_ASSET_SOURCES", "ProductItem", "PublishTask", "ScriptDraft", "VideoAsset",
    "SEVERITY_BLOCK", "SEVERITY_WARN", "ComplianceGuard", "Violation",
    "ProductFilter", "FilterResult", "ScriptBuilder",
    "ShootChecklist", "ChecklistResult",
    "ERROR_CODES", "ITEM_STATUSES", "SCOPE_MODES",
    "STATUS_FETCH_FAILED", "STATUS_HAS_VIDEO", "STATUS_NO_VIDEO",
    "STATUS_OUT_OF_SCOPE", "STATUS_READY",
    "ApiGoodsVideoSource", "FetchError", "FFmpegMissingError", "GoodsVideoRef",
    "HarvestItem", "Harvester", "HarvestReport", "HarvestScope",
    "ManifestGoodsVideoSource", "NormalizedAsset", "ProcessError",
    "RightsViolationError", "VideoFetcher", "VideoMeta", "VideoNormalizer",
    "LICENSE_REQUIRES_EVIDENCE", "LICENSE_TYPES", "LicenseError",
    "MaterialRecord", "MaterialRegistry",
]
