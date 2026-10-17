# -*- coding: utf-8 -*-
"""多多视频带货 · 拍摄 / 自检清单

把外部平台的拍摄规范固化为可勾选清单，每条都带来源。
这是「高质量过审」里**唯一必须由人完成**的部分 —— 工具能查规格、查文案、
查选品，但拍不了一条真人出镜的原创视频。

关于露脸时长占比：
  平台要求（除宠物/居家/部分美食外）真人出镜且**露脸时长占比 > 50%**
  （亿邦动力《谁在拼多多短视频闷声发财》）。本环境无人脸检测能力
  （无 cv2 / ffmpeg），因此该值由人工申报，工具只做阈值判定，
  **绝不把「未申报」当成合格**。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"

# 露脸豁免类目关键词
# 来源：亿邦动力「除了宠物、居家以及部分美食种草内容外，其他品类都需要真人出镜」
FACE_EXEMPT_KEYWORDS = ("宠物", "居家", "美食")
FACE_RATIO_MIN = 0.5


@dataclass
class ChecklistItem:
    key: str
    group: str
    text: str
    severity: str
    source: str


@dataclass
class ChecklistResult:
    passed: bool
    missing_blockers: List[str] = field(default_factory=list)
    missing_warnings: List[str] = field(default_factory=list)
    checked_count: int = 0
    total_count: int = 0


# ----------------------------------------------------------------------
# 清单定义（severity + 来源）
# ----------------------------------------------------------------------

_ITEMS = [
    # ---- 场景 ----
    ChecklistItem("scene_clean", "场景",
                  "场景整洁，用日常生活/工作场景，风格平实接地气，不刻意布景",
                  SEVERITY_BLOCK, "甩手网《拼多多录制商品讲解内容,快速过审技巧》"),
    ChecklistItem("scene_closed", "场景",
                  "录制空间相对封闭，利于收音，保证人声清晰",
                  SEVERITY_BLOCK, "甩手网"),
    ChecklistItem("scene_no_logo", "场景",
                  "不露出其他品牌/平台 LOGO、二维码、电话号码",
                  SEVERITY_BLOCK, "甩手网"),
    ChecklistItem("scene_no_bgm", "场景",
                  "不播放背景音乐，录制现场保持安静",
                  SEVERITY_BLOCK, "甩手网"),

    # ---- 商品 ----
    ChecklistItem("goods_unpacked", "商品",
                  "已去除快递包装",
                  SEVERITY_BLOCK, "甩手网"),
    ChecklistItem("goods_pkg_shown", "商品",
                  "除穿戴类商品外，必须展示外包装",
                  SEVERITY_BLOCK, "甩手网"),
    ChecklistItem("goods_match_detail", "商品",
                  "商品展示形态与商详页图片保持一致",
                  SEVERITY_BLOCK, "甩手网"),
    ChecklistItem("goods_first_sec", "商品",
                  "开始录制第 1 秒内即完整展示商品在镜头中（只露一部分会被驳回）",
                  SEVERITY_BLOCK, "甩手网"),

    # ---- 形象 ----
    ChecklistItem("host_dress", "形象",
                  "主播装扮上镜得体不突兀，少配饰少妆容，形象平民化",
                  SEVERITY_WARN, "甩手网"),
    ChecklistItem("host_no_heavy_filter", "形象",
                  "美颜滤镜不开太过，避免影响商品展示真实性",
                  SEVERITY_WARN, "甩手网"),

    # ---- 设备 ----
    ChecklistItem("equip_light", "设备",
                  "光线条件正常，录制画面不失真",
                  SEVERITY_BLOCK, "甩手网"),
    ChecklistItem("equip_stable", "设备",
                  "画面高清稳定，无卡顿、无模糊",
                  SEVERITY_BLOCK, "亿邦动力 / 起点8"),
    ChecklistItem("equip_resolution", "设备",
                  "分辨率 ≥ 720P（建议 1080P）",
                  SEVERITY_BLOCK, "亿邦动力 / 起点8"),
    ChecklistItem("equip_portrait", "设备",
                  "竖屏拍摄（横屏不予通过）",
                  SEVERITY_BLOCK, "U选U品《拼多多商家如何发布带货视频》"),
    ChecklistItem("equip_audio", "设备",
                  "有音轨，人声清晰，无风噪、电流声，音量正常",
                  SEVERITY_BLOCK, "万店精灵"),

    # ---- 内容 ----
    ChecklistItem("content_original", "内容",
                  "原创实拍，未搬运、未拼接他人内容",
                  SEVERITY_BLOCK, "亿邦动力"),
    ChecklistItem("content_no_greeting", "内容",
                  "不含打招呼、自我介绍等无关内容",
                  SEVERITY_BLOCK, "甩手网"),
    ChecklistItem("content_fluent", "内容",
                  "讲解连贯顺畅完整，不重复、不中途笑场或长时间停顿",
                  SEVERITY_BLOCK, "甩手网"),
    ChecklistItem("content_shot_change", "内容",
                  "剪辑有明显镜头切换（不要一镜到底）",
                  SEVERITY_BLOCK, "亿邦动力"),
    ChecklistItem("content_related", "内容",
                  "内容与商品相关（商品介绍/推荐理由），非纯娱乐内容",
                  SEVERITY_BLOCK, "U选U品"),
    ChecklistItem("content_no_black_bars", "内容",
                  "无左右黑边、无大段黑屏、无音画不同步、无画面挤压颠倒",
                  SEVERITY_BLOCK, "U选U品 / 亿邦动力"),
    ChecklistItem("content_purchase_guide", "内容",
                  "结尾有购买引导，且使用官方允许话术（点击下方购物车/下拉详情页）",
                  SEVERITY_BLOCK, "万店精灵"),

    # ---- 时长 ----
    ChecklistItem("duration_range", "时长",
                  "时长落在 15-60 秒区间（带货视频最佳区间）",
                  SEVERITY_BLOCK, "U选U品 / 亿邦动力"),

    # ---- 合规 ----
    ChecklistItem("ad_label", "合规",
                  "已按《互联网广告管理办法》第九条显著标明「广告」",
                  SEVERITY_BLOCK, "gov.cn 市场监管总局令第 72 号"),
    ChecklistItem("no_extreme", "合规",
                  "无极限词、无夸大功效、无过度承诺",
                  SEVERITY_BLOCK, "万店精灵 / 疯狂的美工"),
    ChecklistItem("no_third_party", "合规",
                  "无第三方平台水印/logo/语音/界面，无引导下载或引流话术",
                  SEVERITY_BLOCK, "U选U品 / 亿邦动力"),
]


class ShootChecklist:

    def items(self, category: str = "") -> List[ChecklistItem]:
        return list(_ITEMS)

    def face_required(self, category: str) -> bool:
        return not any(k in category for k in FACE_EXEMPT_KEYWORDS)

    # ------------------------------------------------------------------

    def evaluate(self, checked: Dict[str, bool], category: str = "",
                 face_ratio: Optional[float] = None) -> ChecklistResult:
        items = self.items(category)
        missing_b: List[str] = []
        missing_w: List[str] = []
        done = 0
        for it in items:
            if checked.get(it.key):
                done += 1
            elif it.severity == SEVERITY_BLOCK:
                missing_b.append("[%s] %s" % (it.group, it.text))
            else:
                missing_w.append("[%s] %s" % (it.group, it.text))

        if self.face_required(category):
            if face_ratio is None:
                missing_b.append("[露脸] 未申报真人露脸时长占比。除宠物/居家/部分美食外，"
                                 "平台要求真人出镜且露脸时长占比 > 50%，请人工确认后补录")
            elif face_ratio < FACE_RATIO_MIN:
                missing_b.append("[露脸] 露脸时长占比 %.0f%% 低于 50%% 下限"
                                 % (face_ratio * 100))

        return ChecklistResult(passed=not missing_b,
                               missing_blockers=missing_b,
                               missing_warnings=missing_w,
                               checked_count=done,
                               total_count=len(items))
