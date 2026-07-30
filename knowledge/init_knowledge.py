# -*- coding: utf-8 -*-
"""初始化MiroFish知识库 - 导入已知知识
运行一次即可，将已搜索整理的所有知识导入知识库"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge.mirofish_db import MiroFishDB

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirofish_db.json")
db = MiroFishDB(DB_PATH)

print("=" * 60)
print("MiroFish 万物知识库 - 初始化")
print("=" * 60)

# ===== 灵感库 (inspiration) =====
print("\n━━ 导入灵感库 ━━")

db.add_card(
    title="核心洞察: 数据没有脏，只是没放对位置",
    content="同一号码在百位/十位/个位的出号规律完全不同。号码2在百位可能是热号(33%命中率)，在个位可能是冷号(15%)。不能把号码当作无差别的集合处理，必须按位置分别分析。这是位置感知预测的核心理念。来源：红果短剧《重生后我换了专业》的启发。",
    category="inspiration",
    domain="3d",
    tags=["位置感知", "核心理念", "摆位置", "短剧启发"],
    source="红果短剧 + 用户灵感",
    engine_hook="position_analysis",
    priority=10,
)

db.add_card(
    title="摆位置技巧: 冷热安家法",
    content="把组选号码摆到正确位置的三个步骤：1)分析号码在各位置的冷热走势，走势过冷的位置不放该号码；2)观察各位置的奇偶偏态，逆偏态放置(某位置奇数过多就放偶数)；3)分析各位置的大小走势方向，匹配号码大小属性。来源：搜狐/彩宝贝 组选转直选技巧。",
    category="inspiration",
    domain="3d",
    tags=["摆位置", "冷热分析", "奇偶偏态", "大小走势", "组选转直选"],
    source="搜狐/彩宝贝",
    engine_hook="reposition",
    priority=9,
)

db.add_card(
    title="大中小顺序推理法",
    content="将号码按大中小分类(0-3小,4-6中,7-9大)，分析近期开奖号码三个位置的大中小排列顺序频率。出现频率最高的顺序为热态，优先按热态顺序摆位置。例如近5期'小中大'出现3次，则下期优先按小中大顺序安排号码。来源：彩宝贝直选技巧。",
    category="inspiration",
    domain="3d",
    tags=["大中小", "顺序推理", "摆位置", "位置预测"],
    source="彩宝贝",
    engine_hook="reposition",
    priority=8,
)

db.add_card(
    title="马尔可夫转移概率应用",
    content="当前状态只依赖于前一个状态。对3D每个位置，统计上期出X后下期出Y的概率，构建转移矩阵。例如上期百位出5，统计历史中百位出5后下期各数字的出现频率，作为本期的权重参考。来源：乐彩网概率论应用系列。",
    category="inspiration",
    domain="3d",
    tags=["马尔可夫", "转移概率", "跟随号", "分位分析"],
    source="乐彩网",
    engine_hook="position_analysis",
    priority=9,
)

db.add_card(
    title="跟随号(直连/斜连)周期规律",
    content="直连(某位置连续出同号)平均约10期出现一次。斜连(某位置连续出邻号±1)约几天出现一次。当某位置长时间没有直连或斜连时，应重点关注。还可以关注跳连(等间隔连号如024、135、246)。来源：乐彩网单选定位法。",
    category="inspiration",
    domain="3d",
    tags=["直连", "斜连", "跟随号", "位置分析", "周期"],
    source="乐彩网",
    engine_hook="position_analysis",
    priority=7,
)

db.add_card(
    title="位置关联: 百位vs个位大小关系",
    content="百位与个位的大小关系有三种：百>个(450注)、百<个(450注)、百=个(100注)。理论周期约2.2期，连续出现2-3次后应考虑反转。百位=个多出现于组三/豹子形态。百位vs十位、十位vs个位类似。来源：乐彩网位置关联技巧。",
    category="inspiration",
    domain="3d",
    tags=["位置关联", "大小关系", "百位个位"],
    source="乐彩网",
    engine_hook="reposition",
    priority=7,
)

db.add_card(
    title="PARA知识管理法: 打造第二大脑",
    content="PARA分类法来自Tiago Forte《打造第二大脑》：Projects(有目标有截止日的项目)、Areas(长期维护的领域)、Resources(参考资料和素材)、Archive(已完成或不再活跃的内容)。灵感→AI自动整理→知识卡片→自动分类存储。穷人赚钱靠时间，富人赚钱靠系统。",
    category="inspiration",
    domain="general",
    tags=["PARA", "知识管理", "第二大脑", "Obsidian", "AI"],
    source="抖音视频 + 《打造第二大脑》",
    engine_hook="",
    priority=8,
)

# ===== Resources (参考资料) =====
print("\n━━ 导入参考资料 ━━")

db.add_card(
    title="差值分析法: 绝对差值恒为10或20",
    content="上期开奖号为ABC(A=百位,B=十位,C=个位)，计算A-B、B-C、C-A的绝对差值，三个差值之和恒为10或20(豹子为0)。差值10的排列顺序有：小大中、大中小、中小大。差值20的排列顺序有：小中大、中大小、大小中。可用于判断本期大中小顺序。",
    category="resource",
    domain="3d",
    tags=["差值分析", "大中小", "定位选号"],
    source="彩宝贝",
    engine_hook="reposition",
    priority=6,
)

db.add_card(
    title="加减法: 位置间加减关系",
    content="某位置的数字可能等于上期与上上期同位置数字的和或差。例如百位本期数字=上期百位+上上期百位(取个位)。纵向(同一位置不同期)和横向(同一期不同位置)的加减关系都可以利用。来源：乐彩网排列三定位法。",
    category="resource",
    domain="3d",
    tags=["加减法", "位置关系", "纵向横向"],
    source="乐彩网",
    engine_hook="position_analysis",
    priority=5,
)

db.add_card(
    title="音频工具箱技术规格",
    content="音频工具箱V2.0功能：视频转音频(MP3 320kbps libmp3lame)、格式转换(MP3/WAV/FLAC/AAC/OGG)、ID3元数据读写(mutagen)、EBU R128标准化(-14LUFS FFmpeg loudnorm)、裁剪拼接(pydub)、智能优化(自动检测+一键修复采样率/声道/比特率/音量)。FFmpeg路径: TRAE SOLO CN自带完整版8.1。",
    category="resource",
    domain="music",
    tags=["音频", "FFmpeg", "MP3", "标准化", "工具"],
    source="自开发",
    engine_hook="",
    priority=5,
)

# ===== Skills (技能模板) =====
print("\n━━ 导入技能模板 ━━")

db.add_card(
    title="SOP: 位置感知分析流程",
    content="Step1: 提取每个位置的历史号码序列(百/十/个分别提取)。Step2: 按位置分别统计遗漏值(当前遗漏/平均遗漏/突破分)。Step3: 按位置统计冷热频次(近10期)。Step4: 按位置构建转移概率矩阵(上期X→本期Y)。Step5: 按位置统计形态(奇偶比/大小比/大中小比)。Step6: 综合加权计算(频次40%+遗漏30%+转移20%+形态10%)。Step7: 摆位评分输出直选推荐。",
    category="skill",
    domain="3d",
    tags=["SOP", "位置感知", "分析流程", "权重系数"],
    source="自开发",
    engine_hook="position_analysis",
    priority=10,
)

db.add_card(
    title="SOP: 摆位评分标准",
    content="摆位评分维度(满分100): 位置权重40分(各号码在其位置上的权重之和) + 大中小顺序匹配20分(匹配热门顺序得满分) + 位置关系匹配10分(百vs个大小关系) + 奇偶分散度15分(1奇2偶或2奇1偶最优) + 大小分散度15分(不全大不全小) + 直连/斜连奖励5分。豹子大幅降权(×0.3)。",
    category="skill",
    domain="3d",
    tags=["SOP", "摆位", "评分标准", "权重系数"],
    source="自开发",
    engine_hook="reposition",
    priority=9,
)

db.add_card(
    title="SOP: 漏斗选号4步法(V3.0)",
    content="Step1-重号(1枚): 上期号码中频次最高者。Step2-邻号(2枚): 上期号码±1的并集。Step3-温冷号(2-3枚): 遗漏2-10期的号码按突破分排序。Step4-去重补位到6码。杀号排除贯穿始终。组三防守: L14规则根据近期组三频率决定防几注。",
    category="skill",
    domain="lottery",
    tags=["SOP", "漏斗选号", "V3.0", "3D"],
    source="自开发",
    engine_hook="",
    priority=8,
)

db.add_card(
    title="权重校准经验: 当前系数待优化",
    content="回测结果(2026-07-12): 百位Top3命中率43.3%(很好), 十位Top3命中率20%(偏低), 个位Top3命中率30%(中等)。直选Top1命中率为0(正常，样本量30期太小)。待优化: 1)可适当增加十位转移概率权重占比; 2)可考虑扩大每位TopN到4-5个提高覆盖率; 3)十位的遗漏突破权重可能需要调高。",
    category="skill",
    domain="3d",
    tags=["权重校准", "回测结果", "待优化", "调优"],
    source="自动复盘",
    engine_hook="weight_calibration",
    priority=8,
)

# ===== Areas (领域知识) =====
print("\n━━ 导入领域知识 ━━")

db.add_card(
    title="3D/排列三: 位置独立摇奖机制",
    content="3D和排列三的百位/十位/个位是独立摇奖的，每个位置从0-9中各取一个数字。这意味着三个位置的号码出现规律是独立的，可以分别统计分析。同一号码在不同位置的出现概率理论上都是10%，但实际中因为摇奖机物理特性，各位置会有不同的冷热分布。",
    category="area",
    domain="3d",
    tags=["独立摇奖", "位置机制", "理论基础"],
    source="常识 + 分析确认",
    engine_hook="position_analysis",
    priority=8,
)

db.add_card(
    title="3D热号冷号判定标准",
    content="热号阈值: 近10期频次占比>15%(理论均匀为10%)。冷号阈值: 近10期频次占比<5%。温号: 5%-15%之间。大乐透热号阈值0.08，冷号阈值3(不同彩种标准不同)。这些阈值可根据回测效果动态调整。",
    category="area",
    domain="lottery",
    tags=["热号", "冷号", "阈值", "标准"],
    source="自开发",
    engine_hook="",
    priority=7,
)

# ===== Archive (已验证/历史) =====
print("\n━━ 导入归档知识 ━━")

db.add_card(
    title="V3.0引擎测试: 40/40全通过",
    content="2026-07-12: 金水谣V3.0全部40项E2E测试通过，3次连续稳定性运行。覆盖8大部分: 各引擎单元测试、FormatGen集成、杀号链、权重融合、走势数据、gen_one逻辑、工具函数、引擎协作链。FormatGen关键发现: 3D/排列三用_gen_3d_hot_freq()直接调用，不经过gen()。",
    category="archive",
    domain="lottery",
    tags=["测试", "V3.0", "E2E", "稳定性"],
    source="自动复盘",
    engine_hook="",
    priority=5,
)

db.add_card(
    title="经验教训: Pailie5数据无预测价值",
    content="排列五数据对排列三号码选择没有预测价值，加入后命中率反而降到随机水平以下。教训: 不同彩种的数据不能混用，即使号码范围相似。原因: 摇奖机制、号码池大小、出现频率分布都不同。",
    category="archive",
    domain="lottery",
    tags=["经验教训", "数据混用", "排列五"],
    source="历史复盘",
    engine_hook="",
    priority=6,
)

# ===== 汇总 =====
stats = db.stats()
print(f"\n{'='*60}")
print(f"初始化完成!")
print(f"  总卡片数: {stats['total_cards']}")
print(f"  按分类: {stats['by_category']}")
print(f"  按领域: {stats['by_domain']}")
print(f"  热门标签: {list(stats['by_tag'].items())[:10]}")
print(f"{'='*60}")
