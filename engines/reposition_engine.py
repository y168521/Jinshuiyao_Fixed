# -*- coding: utf-8 -*-
"""金水谣系统 - 摆位引擎 V1.0
核心灵感："数据没有脏，只是没放对位置"

将组选号码池中的号码，按照每个位置的冷热/奇偶/大小/大中小趋势，
智能地"安家"到百位/十位/个位，生成定位直选推荐。

摆位策略（来源：搜狐/彩宝贝 组选转直选技巧）：
1. 冷热安家：号码在该位置走势过冷则不放，走势温和优先
2. 奇偶逆偏态：位置奇偶偏态严重时，不放同方向号码
3. 大小趋势：分析位置大小走势方向，匹配号码大小
4. 大中小顺序推理：匹配近期最热的大中小排列顺序
5. 位置关联：百位vs个位的大小关系过滤
"""
import logging
from itertools import product

from utils.number_utils import parse_reds, clean_nums

logger = logging.getLogger(__name__)

# 大中小分类
def _classify_bsz(num):
    """大中小分类：0-3=S(小), 4-6=M(中), 7-9=L(大)"""
    if num is None:
        return "M"
    if num <= 3:
        return "S"
    elif num <= 6:
        return "M"
    else:
        return "L"


class RepositionEngine:
    """摆位引擎：将号码池智能安家到百/十/个位

    输入：号码池(pool) + PositionAnalyzer分析结果
    输出：定位直选推荐列表（按综合得分降序）
    """

    def __init__(self, pos_analyzer_result, pool):
        """
        Parameters
        ----------
        pos_analyzer_result : dict
            PositionAnalyzer.analyze() 的返回值
        pool : list[int]
            号码池（如 [2, 3, 5, 7, 8, 9]）
        """
        self.pa_result = pos_analyzer_result
        self.pool = pool
        self.meta = pos_analyzer_result.get("meta", {})

    def reposition(self, top_n=5):
        """生成定位直选推荐。

        对号码池中的号码进行全排列（最多3^3=27种），
        按摆位得分降序返回Top N。

        Parameters
        ----------
        top_n : int
            返回推荐数量（默认5注）

        Returns
        -------
        list[dict]
            [{"nums": (b, s, g), "score": float, "reason": str}, ...]
            nums为三元组(百位,十位,个位)，score为摆位得分(0-100)
        """
        if not self.pool or len(self.pool) < 3:
            logger.warning("摆位引擎：号码池不足3个号码，无法摆位")
            return []

        # 获取每个位置的权重
        pos_weights = {}
        for pos in range(3):
            pos_weights[pos] = self.pa_result.get(pos, {n: 0.1 for n in range(10)})

        # 热门大中小顺序
        hot_bsz = self.meta.get("hot_bsz_order", "SMS")
        bsz_rank = self.meta.get("bsz_order_rank", [])

        # 生成所有排列并打分
        candidates = []
        seen = set()

        # 用笛卡尔积生成所有可能的位置组合
        for b in self.pool:
            for s in self.pool:
                for g in self.pool:
                    key = (b, s, g)
                    if key in seen:
                        continue
                    seen.add(key)

                    score, reasons = self._score_position(b, s, g, pos_weights, hot_bsz, bsz_rank)
                    if score > 0:
                        candidates.append({
                            "nums": key,
                            "score": round(score, 2),
                            "reason": reasons,
                        })

        # 按得分降序
        candidates.sort(key=lambda x: x["score"], reverse=True)

        # 去重：确保百十个不形成豹子(如000)的概率低
        # 豹子虽然理论可能，但实际极少出现，适当降低豹子得分
        for c in candidates:
            b, s, g = c["nums"]
            if b == s == g:
                c["score"] *= 0.3  # 豹子大幅降权

        # 重新排序
        candidates.sort(key=lambda x: x["score"], reverse=True)

        result = candidates[:top_n]
        logger.info("摆位引擎：生成%d注推荐，Top1=%s(得分%.1f)",
                     len(result),
                     result[0]["nums"] if result else "N/A",
                     result[0]["score"] if result else 0)
        return result

    def _score_position(self, b, s, g, pos_weights, hot_bsz, bsz_rank):
        """对一组定位号码(百位b, 十位s, 个位g)进行摆位评分。

        评分维度：
        1. 位置权重得分 (40分): 每个号码在其位置上的PositionAnalyzer权重
        2. 大中小顺序匹配 (20分): 是否匹配近期最热的大中小顺序
        3. 位置关系匹配 (10分): 百位vs个位大小关系是否匹配
        4. 奇偶分散度 (15分): 三个位置奇偶分布是否合理
        5. 大小分散度 (15分): 三个位置大小分布是否合理

        Returns
        -------
        (float, str)
            得分(0-100) + 得分原因描述
        """
        score = 0.0
        reasons = []

        # ===== 1. 位置权重得分 (40分) =====
        w_b = pos_weights[0].get(b, 0.01)
        w_s = pos_weights[1].get(s, 0.01)
        w_g = pos_weights[2].get(g, 0.01)
        # 归一化：3个权重之和的理论最大值约3.0
        weight_score = (w_b + w_s + w_g) / 3.0
        pos_score = min(weight_score * 40, 40)
        score += pos_score
        reasons.append(f"位置权重{pos_score:.0f}分")

        # ===== 2. 大中小顺序匹配 (20分) =====
        current_bsz = f"{_classify_bsz(b)}{_classify_bsz(s)}{_classify_bsz(g)}"
        bsz_score = 0
        if current_bsz == hot_bsz:
            bsz_score = 20  # 完美匹配最热顺序
            reasons.append(f"大中小{current_bsz}完美匹配")
        else:
            # 检查是否在排名前3的大中小顺序中
            for i, (order, cnt) in enumerate(bsz_rank[:3]):
                if current_bsz == order:
                    bsz_score = 15 - i * 3  # 前三名递减
                    break
            if bsz_score == 0:
                bsz_score = 3  # 未匹配但给基础分
        score += bsz_score

        # ===== 3. 位置关系匹配 (10分) =====
        relation_score = 5  # 基础分
        pos_relation = self.meta.get("pos_relation_bai_ge", "gt")
        if pos_relation == "gt" and b > g:
            relation_score = 10
        elif pos_relation == "lt" and b < g:
            relation_score = 10
        elif pos_relation == "eq" and b == g:
            relation_score = 8
        score += relation_score

        # ===== 4. 奇偶分散度 (15分) =====
        odd_count = sum(1 for x in [b, s, g] if x % 2 == 1)
        if odd_count in (1, 2):
            odd_score = 15  # 1奇2偶 或 2奇1偶 最合理
        elif odd_count == 0 or odd_count == 3:
            odd_score = 5  # 全奇或全偶给低分
        else:
            odd_score = 10
        score += odd_score

        # ===== 5. 大小分散度 (15分) =====
        big_count = sum(1 for x in [b, s, g] if x >= 5)
        if big_count in (1, 2):
            big_score = 15
        elif big_count == 0 or big_count == 3:
            big_score = 5
        else:
            big_score = 10
        score += big_score

        # ===== 6. 直连/斜连加分 (奖励项，最高5分) =====
        bonus = 0
        # 如果上期某位置出X，本位置也放X（直连），且有直连趋势
        last_nums = self._get_last_nums()
        if last_nums:
            for pos, num in enumerate([b, s, g]):
                direct_count = self.meta.get("direct_link", {}).get(pos, 0)
                if num == last_nums[pos] and direct_count >= 2:
                    bonus += 1.5  # 直连趋势加分
                oblique_count = self.meta.get("oblique_link", {}).get(pos, 0)
                if last_nums[pos] is not None and abs(num - last_nums[pos]) == 1 and oblique_count >= 3:
                    bonus += 1.0  # 斜连趋势加分
        bonus = min(bonus, 5)
        score += bonus

        return score, ", ".join(reasons)

    def _get_last_nums(self):
        """获取上期开奖号码的百/十/个位"""
        last = self.meta.get("last_draw")
        if last and len(last) >= 3:
            return {pos: last[i] for i, pos in enumerate(['hundred', 'ten', 'unit'])}
        return None

    @staticmethod
    def generate_group6_from_pool(pool):
        """从号码池生成组六复式字符串（向后兼容V3）。

        Parameters
        ----------
        pool : list[int]
            号码池

        Returns
        -------
        str
            如 "02,03,05,07,08,09"
        """
        sorted_pool = sorted(set(pool))
        return ",".join(f"{x:02d}" for x in sorted_pool)

    @staticmethod
    def format_direct_ticket(nums_tuple):
        """将定位三元组格式化为直选号码字符串。

        Parameters
        ----------
        nums_tuple : tuple(int, int, int)
            (百位, 十位, 个位)

        Returns
        -------
        str
            如 "235"
        """
        return "".join(str(x) for x in nums_tuple)
