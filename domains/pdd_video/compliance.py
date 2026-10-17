# -*- coding: utf-8 -*-
"""多多视频带货 · 合规守卫（高质量过审的核心闸门）

设计原则（对应项目铁律「坑必须变成检查」）：
  1. 每个规则都同时有「拦得住」与「不误伤」两类单测 —— 只测正向会让闸门
     退化成永远放行（规则表为空时正向测试全绿而闸门实际是死的）。
  2. 规则表全部**有来源**，不凭空发明。来源见各常量注释。
  3. 缺失检测能力时**显式报未检测**，绝不静默放行 —— 本模块不复刻
     domains/creator/audio_extractor.py 的「全部不可用时优雅降级」反模式。

已核实的规则冲突（刻意保留为 WARN 而非 BLOCK）：
  - 《互联网广告管理办法》第九条要求显著标明「广告」，但实操中标明可能影响
    推荐量。此处按法律要求设为 BLOCK，需人工显式确认才能关闭（见 check_task）。
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from domains.pdd_video.models import LEGAL_ASSET_SOURCES, ProductItem, PublishTask, VideoAsset

SEVERITY_BLOCK = "block"      # 一票否决，不得发布
SEVERITY_WARN = "warn"        # 提示，由人工判断

# ----------------------------------------------------------------------
# 规则表（含来源）
# ----------------------------------------------------------------------

# 极限词 / 绝对化用语
# 来源：《广告法》绝对化用语禁令；万店精灵列举「第一/最佳/国家级/永久/全网最低价」；
#       疯狂的美工列举「最/第一」及夸大功效
# 说明：「第一」易误伤「第一次/第一时间」，故配豁免上下文
EXTREME_WORDS = [
    "最好", "最佳", "最强", "最优", "最便宜", "最实惠", "最低价",
    "第一", "全网第一", "排名第一", "销量第一",
    "国家级", "国家免检", "独家", "首选", "顶级", "极致", "王牌", "冠军",
    "独一无二", "史无前例", "绝无仅有", "前所未有", "无与伦比", "无可比拟",
    "首屈一指", "独占鳌头", "遥遥领先", "永久", "终身", "无敌", "至尊", "极品",
    "全网最低价",
]
# 豁免上下文：这些组合里的「第一」是正常时间序数用法
EXTREME_EXEMPT_CONTEXT = {
    "第一": ["第一次", "第一时间", "第一天", "第一版", "第一回"],
}

# 夸大功效 / 过度承诺
# 来源：万店精灵「三天祛痘」「终身质保」被限制展现；疯狂的美工「夸大商品功效」
OVERCLAIM_PHRASES = [
    "三天祛痘", "三天见效", "根治", "药到病除", "立刻见效", "瞬间见效",
    "保证有效", "无效退款", "终身质保", "稳赚", "必赚", "无风险", "零风险",
    "包过", "保过", "特效", "奇效",
]

# 第三方平台引流（平台明文禁止）
# 来源：U选U品「不得提及第三方平台引流信息：电商和短视频类app元素（水印/logo/语音/界面）、
#       推广APP或引导APP下载」；亿邦动力「禁止有外站logo以及『来我小黄车直接下单』等引流信息」
THIRD_PARTY_DRAIN = [
    "小黄车", "加微信", "加V", "威信", "VX", "vx", "私聊", "私信我",
    "抖音", "快手", "小红书", "淘宝", "天猫", "京东", "B站", "bilibili",
    "扫码", "二维码", "我的小店", "直播间", "微店", "代购",
]

# 柔性自我推销（降级为 WARN，不阻断）
SOFT_SELF_PROMO = ["关注我", "点赞收藏", "点点关注"]

# 平台允许的购买引导白名单（用于防误伤自检）
ALLOWED_PURCHASE_GUIDE = ["点击下方购物车", "下拉详情页", "点击左下角", "看实拍"]

# 禁发广告类目（法规硬禁）
# 来源：《互联网广告管理办法》第六条「禁止利用互联网发布烟草（含电子烟）广告、
#       禁止利用互联网发布处方药广告」；第十二条未成年人相关禁发品类
BANNED_CATEGORIES = [
    "烟草", "电子烟", "处方药", "医疗", "药品", "医疗器械",
    "保健食品", "特殊医学用途配方食品", "农药", "兽药",
]

# 需前置审查/资质的类目（WARN，由人工确认资质后再发）
# 来源：《互联网广告管理办法》第七条「发布医疗、药品、医疗器械、保健食品等
#       应当进行审查的广告，应当在发布前由广告审查机关审查」
REVIEW_REQUIRED_CATEGORIES = [
    "化妆品", "酒类", "美容", "教育培训", "减肥", "丰胸", "增高", "医美",
]

# 素材规格阈值（平台口径）
# 来源：U选U品「竖屏、时长 15s~60s 最佳」；亿邦动力「15s-5min、分辨率 ≥720P、
#       不能出现黑边、无声」；起点8「时长不低于15秒、画质高清1080P」
MIN_DURATION_SEC = 15.0
MAX_DURATION_SEC = 300.0        # 5 分钟上限
MIN_RESOLUTION_EDGE = 720       # 短边 ≥720 即 720P
FACE_RATIO_MIN = 0.5            # 真人露脸时长占比下限


@dataclass
class Violation:
    rule: str
    severity: str
    detail: str
    evidence: str = ""


class ComplianceGuard:
    """合规守卫：把外部规则变成可执行检查"""

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _scan(text: str, words: List[str],
              exempt: Optional[dict] = None) -> List[Tuple[str, str]]:
        """返回 [(命中词, 上下文), ...]；exempt 命中的组合跳过"""
        hits = []
        for w in words:
            start = 0
            while True:
                i = text.find(w, start)
                if i < 0:
                    break
                ctx = text[max(0, i - 2): i + len(w) + 2]
                skip = False
                if exempt:
                    for e in exempt.get(w, []):
                        if e in ctx:
                            skip = True
                            break
                if not skip:
                    hits.append((w, text[max(0, i - 8): i + len(w) + 8]))
                start = i + 1
        return hits

    # ------------------------------------------------------------------
    # 文本检查
    # ------------------------------------------------------------------

    def check_text(self, text: str, category: str = "") -> List[Violation]:
        """检查标题/口播文案。ad_label 属任务级，不在此检查。"""
        if not text:
            return []
        out: List[Violation] = []

        for w, ctx in self._scan(text, EXTREME_WORDS, EXTREME_EXEMPT_CONTEXT):
            out.append(Violation("extreme_word", SEVERITY_BLOCK,
                                 "含极限词/绝对化用语「%s」" % w, ctx))

        for w, ctx in self._scan(text, OVERCLAIM_PHRASES):
            out.append(Violation("overclaim", SEVERITY_BLOCK,
                                 "含夸大功效/过度承诺「%s」" % w, ctx))

        for w, ctx in self._scan(text, THIRD_PARTY_DRAIN):
            out.append(Violation("third_party_drain", SEVERITY_BLOCK,
                                 "含第三方平台引流信息「%s」" % w, ctx))

        for w, ctx in self._scan(text, SOFT_SELF_PROMO):
            out.append(Violation("soft_self_promo", SEVERITY_WARN,
                                 "含自我推销话术「%s」，可能被判无关内容" % w, ctx))

        if category:
            out.extend(self._check_category(category))
        return out

    def _check_category(self, category: str) -> List[Violation]:
        out = []
        for c in BANNED_CATEGORIES:
            if c in category:
                out.append(Violation("banned_category", SEVERITY_BLOCK,
                                     "类目「%s」属禁发广告品类" % category, category))
                return out
        for c in REVIEW_REQUIRED_CATEGORIES:
            if c in category:
                out.append(Violation("review_required_category", SEVERITY_WARN,
                                     "类目「%s」需前置审查/资质，请人工确认" % category, category))
                break
        return out

    # ------------------------------------------------------------------
    # 素材检查
    # ------------------------------------------------------------------

    def check_asset(self, asset: VideoAsset) -> List[Violation]:
        out: List[Violation] = []

        if asset.source not in LEGAL_ASSET_SOURCES:
            out.append(Violation("illegal_asset_source", SEVERITY_BLOCK,
                                 "素材来源「%s」不在白名单 %s（搬运/下载素材一律拒绝）"
                                 % (asset.source, list(LEGAL_ASSET_SOURCES)),
                                 asset.source))
            return out                      # 来源不合法，后续规格检查无意义

        if asset.source == "licensed" and not asset.license_note.strip():
            out.append(Violation("license_note_missing", SEVERITY_BLOCK,
                                 "授权素材未填授权凭证说明", ""))

        if asset.duration_sec < MIN_DURATION_SEC:
            out.append(Violation("duration_too_short", SEVERITY_BLOCK,
                                 "时长 %.1fs 低于下限 %.0fs" % (asset.duration_sec, MIN_DURATION_SEC)))
        elif asset.duration_sec > MAX_DURATION_SEC:
            out.append(Violation("duration_too_long", SEVERITY_BLOCK,
                                 "时长 %.1fs 超过上限 %.0fs" % (asset.duration_sec, MAX_DURATION_SEC)))

        if asset.width > 0 and asset.height > 0:
            if asset.height <= asset.width:
                out.append(Violation("not_portrait", SEVERITY_BLOCK,
                                     "横屏视频（%dx%d），带货视频须竖屏" % (asset.width, asset.height)))
            if min(asset.width, asset.height) < MIN_RESOLUTION_EDGE:
                out.append(Violation("low_resolution", SEVERITY_BLOCK,
                                     "短边 %d < %dP，画质不足" % (min(asset.width, asset.height),
                                                                MIN_RESOLUTION_EDGE)))

        if not asset.has_audio:
            out.append(Violation("no_audio", SEVERITY_BLOCK, "无音轨/音量过低"))

        if asset.black_bars:
            out.append(Violation("black_bars", SEVERITY_BLOCK, "含左右黑边/大段黑屏"))

        if asset.shot_changes < 1:
            out.append(Violation("no_shot_change", SEVERITY_WARN,
                                 "无镜头切换，平台要求剪辑有明显镜头切换"))

        if asset.ai_generated:
            out.append(Violation("ai_generated_label", SEVERITY_WARN,
                                 "AI 生成内容须按《人工智能生成合成内容标识办法》添加标识"))
        return out

    # ------------------------------------------------------------------
    # 任务级检查
    # ------------------------------------------------------------------

    def check_task(self, task: PublishTask,
                   product: Optional[ProductItem] = None) -> List[Violation]:
        out: List[Violation] = []
        out.extend(self.check_text(task.title, category=task.category or (product.category if product else "")))
        out.extend(self.check_text(task.copy_text))

        if not task.ad_label:
            out.append(Violation("ad_label_missing", SEVERITY_BLOCK,
                                 "未显著标明「广告」。依据《互联网广告管理办法》第九条："
                                 "通过知识介绍、体验分享、消费测评等形式推销商品并附加购物链接的，"
                                 "广告发布者应当显著标明「广告」"))

        if product is not None:
            if task.brand and product.brand and task.brand != product.brand:
                out.append(Violation("brand_mismatch", SEVERITY_BLOCK,
                                     "文案品牌「%s」与商品品牌「%s」不一致（货不对板）"
                                     % (task.brand, product.brand)))
            if task.spec and product.spec and task.spec != product.spec:
                out.append(Violation("spec_mismatch", SEVERITY_BLOCK,
                                     "文案规格「%s」与商品规格「%s」不一致（货不对板）"
                                     % (task.spec, product.spec)))
        return out

    # ------------------------------------------------------------------
    # 可发布性判定
    # ------------------------------------------------------------------

    def is_publishable(self, task: PublishTask, asset: VideoAsset,
                       product: Optional[ProductItem] = None
                       ) -> Tuple[bool, List[Violation]]:
        v: List[Violation] = []
        v.extend(self.check_task(task, product=product))
        v.extend(self.check_asset(asset))

        if asset.face_visible_ratio is None:
            v.append(Violation("face_ratio_undetected", SEVERITY_WARN,
                               "露脸时长占比未检测（环境无人脸检测能力）。"
                               "除宠物/居家/部分美食外，平台要求真人露脸占比 >50%，"
                               "请人工确认后补录"))
        elif asset.face_visible_ratio < FACE_RATIO_MIN:
            v.append(Violation("face_ratio_low", SEVERITY_BLOCK,
                               "露脸时长占比 %.0f%% 低于 %.0f%%"
                               % (asset.face_visible_ratio * 100, FACE_RATIO_MIN * 100)))

        blocks = [x for x in v if x.severity == SEVERITY_BLOCK]
        return (not blocks), v
