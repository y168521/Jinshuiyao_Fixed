# -*- coding: utf-8 -*-
"""金水谣系统 - 位置感知分析引擎 V1.0
核心灵感："数据没有脏，只是没放对位置"

3D/排列三的三个位置（百位/十位/个位）是独立摇奖的，
同一号码在不同位置的出号规律完全不同。
本引擎按位置分别统计遗漏、频次、冷热、奇偶、大小、大中小、跟随号转移概率，
为每个位置的每个号码生成综合权重，供摆位引擎使用。

关键技巧来源：
1. 分位遗漏统计 — 乐彩网定位遗漏走势图
2. 跟随号转移 — 乐彩网单选定位法
3. 摆位置冷热分析 — 搜狐/彩宝贝组选转直选技巧
4. 马尔可夫转移概率 — 乐彩网概率论应用
5. 大中小顺序推理 — 彩宝贝直选技巧
"""
import os
import sys
import logging
from collections import Counter, defaultdict

from utils.number_utils import parse_reds, clean_nums

logger = logging.getLogger(__name__)

# 位置名称映射
_POS_NAMES = {0: "百位", 1: "十位", 2: "个位"}


class PositionAnalyzer:
    """位置感知分析器

    对3D/排列三的三个位置（百位/十位/个位）分别进行：
    1. 冷热频次统计（近N期）
    2. 分位遗漏计算（当前遗漏/平均遗漏/突破分）
    3. 分位形态统计（奇偶比/大小比/大中小比）
    4. 跟随号转移概率（上期该位置出X，下期该位置出Y的概率）
    5. 直连/斜连统计（该位置连续出同号或邻号的周期）
    """

    def __init__(self, lot, history, window=10, miss_window=50, transition_window=100):
        """
        Parameters
        ----------
        lot : str
            彩种名称（仅支持 福彩3D/排列三）
        history : list[dict]
            历史数据，按时间 新→旧 排列（index 0 = 最新）
        window : int
            冷热频次统计窗口（默认近10期）
        miss_window : int
            遗漏计算使用的最大历史期数（默认近50期）
        transition_window : int
            转移概率统计窗口（默认近100期）
        """
        self.lot = lot
        self.history = history
        self.window = window
        self.miss_window = miss_window
        self.transition_window = transition_window
        self.result = {}  # 最终结果: {pos: {num: weight}}

        # ===== V4.1 知识库集成 =====
        self._knowledge = None
        self._load_knowledge()

    def _load_knowledge(self):
        """加载MiroFish知识库，失败时静默降级"""
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base_dir, "knowledge", "mirofish_db.json")
            if os.path.exists(db_path):
                # 确保base_dir在sys.path中，以便import knowledge包
                if base_dir not in sys.path:
                    sys.path.insert(0, base_dir)
                from knowledge.mirofish_db import MiroFishDB
                self._knowledge = MiroFishDB(db_path)
                logger.info("[%s] MiroFish知识库已加载", self.lot)
            else:
                logger.debug("知识库文件不存在，跳过加载")
        except Exception as e:
            logger.debug("知识库加载失败(不影响分析): %s", e)
            self._knowledge = None

    def analyze(self):
        """执行完整的位置感知分析，返回每个位置每个号码的综合权重。

        Returns
        -------
        dict
            {
                0: {num: weight, ...},  # 百位权重
                1: {num: weight, ...},  # 十位权重
                2: {num: weight, ...},  # 个位权重
                "meta": {
                    "big_small_order": [(0:"B",1:"S",2:"M"), ...],  # 近期大中小顺序频率
                    "pos_relation": {"bai_vs_ge": "gt"|"lt"|"eq", ...},  # 位置大小关系
                    "position_heat": {0: {"hot": [2,5], "cold": [0,8]}, ...},  # 每位冷热号
                }
            }
        """
        # 提取每位的历史号码序列
        pos_seqs = self._extract_position_sequences()

        # 1. 按位置分别计算遗漏
        pos_miss = {}
        for pos in range(3):
            pos_miss[pos] = self._calc_position_miss(pos, pos_seqs[pos])

        # 2. 按位置分别统计频次
        pos_freq = {}
        for pos in range(3):
            pos_freq[pos] = self._calc_position_freq(pos, pos_seqs[pos])

        # 3. 按位置分别统计形态（奇偶/大小/大中小）
        pos_morph = {}
        for pos in range(3):
            pos_morph[pos] = self._calc_position_morph(pos, pos_seqs[pos])

        # 4. 按位置分别构建转移概率矩阵
        pos_transition = {}
        for pos in range(3):
            pos_transition[pos] = self._build_position_transition(pos, pos_seqs[pos])

        # 5. 综合权重计算
        result = {}
        for pos in range(3):
            result[pos] = self._compute_position_weights(
                pos, pos_miss[pos], pos_freq[pos],
                pos_morph[pos], pos_transition[pos]
            )

        # 6. 元数据（大中小顺序、位置关系等）
        result["meta"] = self._compute_meta(pos_seqs, pos_morph)

        self.result = result
        logger.info("[%s] 位置感知分析完成: 百位Top3=%s, 十位Top3=%s, 个位Top3=%s",
                     self.lot,
                     self._top_n(result[0], 3),
                     self._top_n(result[1], 3),
                     self._top_n(result[2], 3))

        # 7. 应用知识库调整（V4.1）
        result = self._apply_knowledge(result)
        self.result = result

        return result

    # ------------------------------------------------------------------
    # 数据提取
    # ------------------------------------------------------------------

    def _extract_position_sequences(self):
        """从历史数据中提取每个位置(百/十/个)的号码序列。

        Returns
        -------
        dict
            {0: [num, num, ...], 1: [...], 2: [...]}
            每个列表按 新→旧 排列（index 0 = 最新一期该位置的号码）
        """
        seqs = {0: [], 1: [], 2: []}
        for record in self.history:
            nums_str = str(record.get("nums", ""))
            nums = [x for x in parse_reds(clean_nums(nums_str)) if 0 <= x <= 9]
            for pos in range(3):
                if pos < len(nums):
                    seqs[pos].append(nums[pos])
                else:
                    seqs[pos].append(None)  # 数据缺失
        return seqs

    # ------------------------------------------------------------------
    # 分位遗漏计算
    # ------------------------------------------------------------------

    def _calc_position_miss(self, pos, seq):
        """计算指定位置上每个号码(0-9)的遗漏统计。

        Parameters
        ----------
        pos : int
            位置索引（0=百位, 1=十位, 2=个位）
        seq : list[int|None]
            该位置的历史号码序列（新→旧）

        Returns
        -------
        dict
            {num: {"current_miss": int, "avg_miss": float, "max_miss": int,
                   "breakthrough_score": float}}
        """
        result = {}
        # 限制分析窗口
        effective_seq = seq[:self.miss_window]

        for num in range(10):
            appear_indices = []
            for i, n in enumerate(effective_seq):
                if n == num:
                    appear_indices.append(i)

            if not appear_indices:
                result[num] = {
                    "current_miss": len(effective_seq),
                    "avg_miss": 0.0,
                    "max_miss": len(effective_seq),
                    "breakthrough_score": 0.0,
                }
                continue

            current_miss = appear_indices[0]

            gaps = []
            for j in range(1, len(appear_indices)):
                gaps.append(appear_indices[j] - appear_indices[j - 1])

            avg_miss = sum(gaps) / len(gaps) if gaps else 0.0
            max_miss = max(gaps) if gaps else 0
            if current_miss > max_miss:
                max_miss = current_miss

            bt_score = current_miss / avg_miss if avg_miss > 0 else 0.0

            result[num] = {
                "current_miss": current_miss,
                "avg_miss": round(avg_miss, 2),
                "max_miss": max_miss,
                "breakthrough_score": round(bt_score, 2),
            }

        return result

    # ------------------------------------------------------------------
    # 分位频次统计
    # ------------------------------------------------------------------

    def _calc_position_freq(self, pos, seq):
        """统计指定位置上每个号码在近N期的出现频次。

        Returns
        -------
        dict
            {num: {"freq": int, "ratio": float, "heat_level": str}}
            heat_level: "hot" | "warm" | "cold"
        """
        effective = seq[:self.window]
        valid = [n for n in effective if n is not None]
        total = max(len(valid), 1)
        freq = Counter(valid)

        result = {}
        for num in range(10):
            f = freq.get(num, 0)
            ratio = f / total
            # 热号阈值：频次占比 > 0.15 (理论均匀分布为0.1)
            # 冷号阈值：频次占比 < 0.05
            if ratio > 0.15:
                heat = "hot"
            elif ratio < 0.05:
                heat = "cold"
            else:
                heat = "warm"
            result[num] = {
                "freq": f,
                "ratio": round(ratio, 4),
                "heat_level": heat,
            }
        return result

    # ------------------------------------------------------------------
    # 分位形态统计
    # ------------------------------------------------------------------

    def _calc_position_morph(self, pos, seq):
        """统计指定位置上奇偶、大小、大中小的分布比例。

        Returns
        -------
        dict
            {
                "odd_ratio": float,   # 近N期奇数占比
                "even_ratio": float,
                "big_ratio": float,   # 大数(5-9)占比
                "small_ratio": float,  # 小数(0-4)占比
                "large_ratio": float, # 大(7-9)占比
                "medium_ratio": float, # 中(4-6)占比
                "tiny_ratio": float,  # 小(0-3)占比
                "recent_trend": str,  # 最近3期的大小趋势 "rising"|"falling"|"stable"
            }
        """
        effective = seq[:self.window]
        valid = [n for n in effective if n is not None]
        if not valid:
            return {
                "odd_ratio": 0.5, "even_ratio": 0.5,
                "big_ratio": 0.5, "small_ratio": 0.5,
                "large_ratio": 0.33, "medium_ratio": 0.34, "tiny_ratio": 0.33,
                "recent_trend": "stable",
            }

        total = len(valid)
        odd_count = sum(1 for n in valid if n % 2 == 1)
        big_count = sum(1 for n in valid if n >= 5)
        large_count = sum(1 for n in valid if n >= 7)
        medium_count = sum(1 for n in valid if 4 <= n <= 6)
        tiny_count = sum(1 for n in valid if n <= 3)

        # 最近3期趋势
        recent3 = valid[:3]
        trend = "stable"
        if len(recent3) >= 3:
            # 用简单线性趋势判断
            if recent3[0] > recent3[1] > recent3[2]:
                trend = "rising"  # 数字在增大（最新→旧递减 = 新的在变大）
            elif recent3[0] < recent3[1] < recent3[2]:
                trend = "falling"

        return {
            "odd_ratio": round(odd_count / total, 4),
            "even_ratio": round(1 - odd_count / total, 4),
            "big_ratio": round(big_count / total, 4),
            "small_ratio": round(1 - big_count / total, 4),
            "large_ratio": round(large_count / total, 4),
            "medium_ratio": round(medium_count / total, 4),
            "tiny_ratio": round(tiny_count / total, 4),
            "recent_trend": trend,
        }

    # ------------------------------------------------------------------
    # 分位转移概率矩阵
    # ------------------------------------------------------------------

    def _build_position_transition(self, pos, seq):
        """构建指定位置的跟随号转移概率矩阵。

        P(本期该位置=Y | 上期该位置=X)

        Returns
        -------
        dict
            {prev_num: {next_num: probability, ...}, ...}
        """
        effective = seq[:self.transition_window]
        valid = [n for n in effective if n is not None]
        if len(valid) < 2:
            return {}

        prev_count = Counter()
        trans_count = defaultdict(lambda: defaultdict(int))

        for i in range(len(valid) - 1):
            a = valid[i]       # 本期（更新）
            b = valid[i + 1]   # 上期（更旧）
            prev_count[b] += 1
            trans_count[b][a] += 1

        transition = {}
        for a, targets in trans_count.items():
            denom = max(1, prev_count[a])
            transition[a] = {}
            for b, cnt in targets.items():
                transition[a][b] = round(cnt / denom, 4)

        return transition

    # ------------------------------------------------------------------
    # 综合权重计算
    # ------------------------------------------------------------------

    def _compute_position_weights(self, pos, miss_data, freq_data, morph_data, transition_data):
        """综合各维度数据，计算指定位置上每个号码的最终权重。

        权重组成（V4.1调优版）：
        1. 频次权重 (30%): 热号得分高，但过度追热会导致忽略回补
        2. 遗漏突破权重 (35%): 遗漏突破分越高，越可能回补（3D最强信号）
        3. 转移概率权重 (20%): 上期该位置号码→本期的跟随概率
        4. 形态逆偏态权重 (15%): 逆偏态加分（增加权重以强化位置差异化）

        Returns
        -------
        dict
            {num: weight, ...} 权重范围 0~1
        """
        import math

        # 上期该位置的号码
        last_num = None
        if self.history:
            nums = [x for x in parse_reds(clean_nums(self.history[0]["nums"])) if 0 <= x <= 9]
            if pos < len(nums):
                last_num = nums[pos]

        weights = {}
        for num in range(10):
            # --- 1. 频次权重 (30%) ---
            freq_info = freq_data.get(num, {"freq": 0, "ratio": 0})
            freq_score = min(freq_info["ratio"] / 0.2, 1.0)  # 归一化到0-1
            # 冷号也不给0分——用0.15保底分，避免完全忽略冷号
            freq_score = max(freq_score, 0.15)

            # --- 2. 遗漏突破权重 (35%) ---
            miss_info = miss_data.get(num, {"breakthrough_score": 0, "current_miss": 0})
            bt = miss_info["breakthrough_score"]
            bt_score = min(bt / 2.0, 1.0)  # 封顶到1.0
            # V4.1增强：遗漏=0时给更高回补分（直连可能）
            if miss_info["current_miss"] == 0:
                bt_score = max(bt_score, 0.4)
            # V4.1增强：遗漏在avg_miss附近（温水区）给适度加分
            avg_miss = miss_info.get("avg_miss", 5)
            current = miss_info.get("current_miss", 0)
            if 0 < current <= avg_miss * 0.8:
                bt_score = max(bt_score, 0.35)

            # --- 3. 转移概率权重 (20%) ---
            trans_score = 0.0
            if last_num is not None and transition_data:
                trans = transition_data.get(last_num, {})
                trans_prob = trans.get(num, 0)
                # V4.1：降低归一化阈值（0.15而非0.2），更敏感
                trans_score = min(trans_prob / 0.15, 1.0)
                # 如果转移概率为0（历史从未跟随过），给一个低基础分
                if trans_prob == 0:
                    trans_score = 0.1
                # V4.1增强：邻号(±1)也给适度加分（斜连可能）
                if last_num is not None and abs(num - last_num) == 1:
                    trans_score = max(trans_score, 0.35)

            # --- 4. 形态逆偏态权重 (15%) ---
            morph_score = self._calc_morph_score(num, morph_data)

            # --- 综合加权 ---
            w = (freq_score * 0.30 +
                 bt_score * 0.35 +
                 trans_score * 0.20 +
                 morph_score * 0.15)
            weights[num] = round(max(w, 0.01), 4)  # 下限0.01

        return weights

    def _calc_morph_score(self, num, morph_data):
        """计算号码在当前位置的形态逆偏态得分。

        如果某位置的奇偶/大小已经严重偏态，
        则与偏态方向相反的号码获得加分。

        例如：百位近10期80%都是奇数（偏态），
        则偶数号码获得加分（逆偏态）。
        """
        is_odd = num % 2 == 1
        is_big = num >= 5
        is_large = num >= 7  # 大
        is_medium = 4 <= num <= 6  # 中
        is_tiny = num <= 3  # 小

        score = 0.5  # 基础分

        # 奇偶逆偏态：如果该位置奇数偏多，偶数加分
        odd_ratio = morph_data.get("odd_ratio", 0.5)
        if abs(odd_ratio - 0.5) > 0.2:  # 偏态超过20%
            if not is_odd and odd_ratio > 0.5:
                score += 0.3  # 偶数逆奇数偏态
            elif is_odd and odd_ratio < 0.5:
                score += 0.3  # 奇数逆偶数偏态

        # 大小逆偏态
        big_ratio = morph_data.get("big_ratio", 0.5)
        if abs(big_ratio - 0.5) > 0.2:
            if not is_big and big_ratio > 0.5:
                score += 0.3
            elif is_big and big_ratio < 0.5:
                score += 0.3

        # 大中小逆偏态
        large_ratio = morph_data.get("large_ratio", 0.33)
        tiny_ratio = morph_data.get("tiny_ratio", 0.33)
        medium_ratio = morph_data.get("medium_ratio", 0.34)

        # 检查大中小偏态
        max_ratio = max(large_ratio, medium_ratio, tiny_ratio)
        if max_ratio > 0.5:
            if max_ratio == large_ratio and is_tiny:
                score += 0.2  # 大偏态，小号加分
            elif max_ratio == tiny_ratio and is_large:
                score += 0.2  # 小偏态，大号加分
            elif max_ratio == medium_ratio and (is_tiny or is_large):
                score += 0.15  # 中偏态，两端加分

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # 元数据计算
    # ------------------------------------------------------------------

    def _compute_meta(self, pos_seqs, pos_morph):
        """计算大中小顺序频率和位置关系等元数据。

        Parameters
        ----------
        pos_seqs : dict
            {0: [num,...], 1: [...], 2: [...]}
        pos_morph : dict
            {pos: morph_data}
        """
        meta = {}

        # 1. 大中小顺序分析（近10期）
        # 大中小定义：0-3=小(S), 4-6=中(M), 7-9=大(L)
        bsz_order_freq = Counter()
        recent_n = min(10, len(pos_seqs[0]))
        for i in range(recent_n):
            b = self._classify_bsz(pos_seqs[0][i])
            s = self._classify_bsz(pos_seqs[1][i])
            g = self._classify_bsz(pos_seqs[2][i])
            order = f"{b}{s}{g}"
            bsz_order_freq[order] += 1

        # 转为有序列表（按频率降序）
        meta["bsz_order_rank"] = bsz_order_freq.most_common()

        # 最热的大中小顺序
        if bsz_order_freq:
            meta["hot_bsz_order"] = bsz_order_freq.most_common(1)[0][0]
        else:
            meta["hot_bsz_order"] = "SMS"

        # 2. 位置大小关系统计（百位 vs 个位）
        # 百>个, 百<个, 百=个
        relation_counter = Counter()
        for i in range(recent_n):
            b = pos_seqs[0][i]
            g = pos_seqs[2][i]
            if b is not None and g is not None:
                if b > g:
                    relation_counter["gt"] += 1
                elif b < g:
                    relation_counter["lt"] += 1
                else:
                    relation_counter["eq"] += 1

        if relation_counter:
            meta["pos_relation_bai_ge"] = relation_counter.most_common(1)[0][0]
        else:
            meta["pos_relation_bai_ge"] = "gt"

        # 3. 每个位置的冷热号
        meta["position_heat"] = {}
        for pos in range(3):
            # 使用freq_data的heat_level
            # 先计算freq
            effective = pos_seqs[pos][:self.window]
            valid = [n for n in effective if n is not None]
            total = max(len(valid), 1)
            freq = Counter(valid)

            hot_nums = []
            cold_nums = []
            for num in range(10):
                ratio = freq.get(num, 0) / total
                if ratio > 0.15:
                    hot_nums.append(num)
                elif ratio < 0.05:
                    cold_nums.append(num)
            meta["position_heat"][pos] = {
                "hot": sorted(hot_nums),
                "cold": sorted(cold_nums),
            }

        # 4. 直连统计：该位置上期号码与本期相同的次数（近20期）
        for pos in range(3):
            seq = [n for n in pos_seqs[pos][:20] if n is not None]
            direct_link = 0
            for i in range(len(seq) - 1):
                if seq[i] == seq[i + 1]:
                    direct_link += 1
            meta.setdefault("direct_link", {})[pos] = direct_link

        # 5. 斜连统计：该位置上期号码与本期相邻(±1)的次数（近20期）
        for pos in range(3):
            seq = [n for n in pos_seqs[pos][:20] if n is not None]
            oblique_link = 0
            for i in range(len(seq) - 1):
                if abs(seq[i] - seq[i + 1]) == 1:
                    oblique_link += 1
            meta.setdefault("oblique_link", {})[pos] = oblique_link

        return meta

    def _apply_knowledge(self, weights):
        """根据知识库中的经验调整权重（V4.1）。

        引擎分析时自动调用知识库，查找与当前场景相关的知识，
        根据知识的effectiveness评分微调权重。

        Parameters
        ----------
        weights : dict
            {pos: {num: weight}}

        Returns
        -------
        dict
            调整后的权重
        """
        if not self._knowledge:
            return weights

        # 查询位置分析相关知识
        knowledge_cards = self._knowledge.get_for_engine("position_analysis", domain="3d")
        if not knowledge_cards:
            return weights

        # 根据知识有效性微调
        total_boost = 0
        applied_count = 0
        for card in knowledge_cards[:3]:  # 最多参考3条
            eff = card.get("effectiveness", 50)
            # 高有效性(>70)的知识给予微调加成
            if eff > 70:
                total_boost += 0.02  # 每条+2%权重
                applied_count += 1
            elif eff < 30:
                total_boost -= 0.01  # 低有效性知识减权
                applied_count += 1

        if applied_count > 0 and total_boost != 0:
            # 将boost应用到每个位置的Top权重号码上
            for pos in range(3):
                if pos in weights:
                    sorted_nums = sorted(weights[pos].items(), key=lambda x: x[1], reverse=True)
                    # 对Top3号码加成
                    for i, (num, w) in enumerate(sorted_nums[:3]):
                        weights[pos][num] = round(max(0.01, w + total_boost * (1 - i * 0.3)), 4)

            logger.info("[%s] 知识库调整: 应用了%d条知识, boost=%.3f", self.lot, applied_count, total_boost)

        return weights

    @staticmethod
    def _classify_bsz(num):
        """大中小分类：0-3=S(小), 4-6=M(中), 7-9=L(大)"""
        if num is None:
            return "M"  # 缺失默认中
        if num <= 3:
            return "S"
        elif num <= 6:
            return "M"
        else:
            return "L"

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def get_top_n(self, pos, n=3, kill_set=None):
        """获取指定位置权重最高的n个号码。

        Parameters
        ----------
        pos : int
            位置索引 (0/1/2)
        n : int
            返回数量
        kill_set : set[int] | None
            要排除的杀号集合

        Returns
        -------
        list[int]
            按权重降序排列的号码列表
        """
        if pos not in self.result or not isinstance(self.result[pos], dict):
            return list(range(n)) if n <= 10 else list(range(10))

        sorted_nums = sorted(
            self.result[pos].items(),
            key=lambda x: x[1],
            reverse=True
        )

        result = []
        for num, w in sorted_nums:
            if kill_set and num in kill_set:
                continue
            result.append(num)
            if len(result) >= n:
                break

        # 如果杀号后排除了太多，回补
        if len(result) < n:
            for num, w in sorted_nums:
                if num not in result:
                    result.append(num)
                    if len(result) >= n:
                        break

        return result

    def get_position_weights(self, pos):
        """获取指定位置的所有号码权重。

        Returns
        -------
        dict
            {num: weight}
        """
        if pos in self.result and isinstance(self.result[pos], dict):
            return dict(self.result[pos])
        return {n: 0.1 for n in range(10)}

    @staticmethod
    def _top_n(weight_dict, n):
        """返回权重最高的n个号码"""
        if not weight_dict:
            return []
        sorted_items = sorted(weight_dict.items(), key=lambda x: x[1], reverse=True)
        return [num for num, _ in sorted_items[:n]]
