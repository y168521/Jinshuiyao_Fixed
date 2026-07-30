# -*- coding: utf-8 -*-
"""金水谣系统 - 形态分析约束引擎 V2.0
形态统计 + 约束过滤：奇偶比/大小比/三区分布/和值范围
在号码池生成后增加形态合理性检查"""
import logging
import random
from collections import Counter

from utils.number_utils import parse_reds
from config import LOTTERY_RULES

logger = logging.getLogger(__name__)

# 各彩种默认保留数量
_DEFAULT_KEEP = {
    "福彩3D": 6,
    "排列三": 6,
    "双色球": 12,
    "大乐透": 12,
    "七乐彩": 12,
    "快乐8": 15,
    "七星彩": 10,
}


class MorphPredictor:
    """形态分析约束引擎

    V2.0 升级：
    - analyze() 返回更丰富的统计信息（分布、和值范围、三区分布）
    - check_pattern() 形态合理性检查与评分
    - filter_pool() 号码池过滤，移除形态极端号码
    - 同时支持 3D 类彩种（3位形态 OOO/OOE 等）和非3D彩种（奇偶比/大小比/三区）
    """

    def __init__(self, lot):
        self.lot = lot
        self.rule = LOTTERY_RULES.get(lot, {})
        self._is_digit = self.rule.get("digit", False) or self.rule.get("special_code") is not None

    # ------------------------------------------------------------------
    # 公共接口：形态统计
    # ------------------------------------------------------------------

    def analyze(self, history):
        """分析近50期历史数据，返回形态统计。

        返回值向后兼容 V1（保留 odd_even / big_small 键），
        同时新增 odd_even_dist / big_small_dist / sum_range / zone_dist。

        3D/排列三:
            odd_even   = "OOO" | "OOE" | ...  (最常见形态)
            big_small  = "BBB" | "BBS" | ...  (最常见形态)
            odd_even_dist = {"OOO": 12, "OOE": 8, ...}
            big_small_dist = {"BBB": 10, "BBS": 9, ...}
            sum_range   = (min_sum, max_sum)
            zone_dist   = {"1": 15, "2": 18, "3": 17}   # 三位各号所属区间的统计

        非3D（双色球/大乐透/七乐彩/快乐8）:
            odd_even   = "3:3" | "4:2" | ...  (最常见奇偶比)
            big_small  = "3:3" | "4:2" | ...  (最常见大小比)
            odd_even_dist = {"3:3": 12, "4:2": 8, ...}
            big_small_dist = {"3:3": 10, "4:2": 9, ...}
            sum_range   = (min_sum, max_sum)
            zone_dist   = {"1": 15, "2": 18, "3": 17}   # 号码范围三等分统计
        """
        if not history:
            return None

        recent = history[-50:]

        if self._is_digit:
            return self._analyze_digit(recent)
        else:
            return self._analyze_non_digit(recent)

    # ------------------------------------------------------------------
    # 公共接口：形态检查与评分
    # ------------------------------------------------------------------

    def check_pattern(self, nums, history=None):
        """检查一组号码的形态合理性，返回评分和警告。

        Args:
            nums:    已解析的整数列表（如 [3, 5, 8] 或 [1, 7, 15, 22, 28, 33]）
            history: 历史数据列表（可选，用于动态分析；为 None 时使用默认阈值）

        Returns:
            {"valid": True/False, "score": 0-100, "warnings": []}
        """
        if not nums:
            return {"valid": False, "score": 0, "warnings": ["号码列表为空"]}

        score = 100
        warnings = []

        # 如果有历史数据，使用统计分布做检查
        stats = self.analyze(history) if history else None

        if self._is_digit:
            score, warnings = self._check_digit_pattern(nums, stats, score, warnings)
        else:
            score, warnings = self._check_non_digit_pattern(nums, stats, score, warnings)

        # 通用和值检查
        if stats and "sum_range" in stats:
            smin, smax = stats["sum_range"]
            total = sum(nums)
            if total < smin or total > smax:
                score -= 30
                warnings.append(f"和值{total}超出近50期范围[{smin},{smax}]")

        score = max(0, min(100, score))
        valid = score >= 30  # 低于30分视为形态不合格

        return {"valid": valid, "score": score, "warnings": warnings}

    # ------------------------------------------------------------------
    # 公共接口：号码池过滤
    # ------------------------------------------------------------------

    def filter_pool(self, pool, history, keep_count=None):
        """过滤号码池，保留形态评分较高的号码。

        Args:
            pool:        候选号码池（整数列表，如 [358, 472, ...] 或 [030508, ...]）
            history:     历史数据列表
            keep_count:  保留数量，None 时自动根据彩种确定

        Returns:
            过滤后的号码池列表
        """
        if keep_count is None:
            keep_count = _DEFAULT_KEEP.get(self.lot, 10)

        if not pool or len(pool) <= keep_count:
            logger.debug("[%s] 号码池大小 %d <= keep_count %d，无需过滤",
                         self.lot, len(pool) if pool else 0, keep_count)
            return pool

        # 拆分号码为独立数字
        parsed_pool = []
        for item in pool:
            if self._is_digit:
                digits = self._split_digits(item)
            else:
                digits = self._split_non_digit_nums(item)
            if digits:
                parsed_pool.append((item, digits))

        if not parsed_pool:
            logger.warning("[%s] 号码池解析后为空，返回原始池", self.lot)
            return pool

        # 对所有号码评分
        scored = []
        for original, nums in parsed_pool:
            result = self.check_pattern(nums, history)
            scored.append((original, result["score"], result["warnings"]))

        # 按评分降序排列，同分随机打散
        random.shuffle(scored)
        scored.sort(key=lambda x: x[1], reverse=True)

        kept = [item[0] for item in scored[:keep_count]]
        removed_count = len(scored) - keep_count

        if removed_count > 0:
            removed_scores = [item[1] for item in scored[keep_count:]]
            avg_removed = sum(removed_scores) / len(removed_scores) if removed_scores else 0
            logger.info("[%s] 形态过滤：保留 %d/%d，移除 %d（平均分 %.1f）",
                        self.lot, keep_count, len(scored), removed_count, avg_removed)

        return kept

    # ==================================================================
    # 内部方法：3D/排列三分析
    # ==================================================================

    def _analyze_digit(self, recent):
        """分析3D类彩种的形态统计"""
        odd_even = Counter()
        big_small = Counter()
        zone_counter = Counter()
        sums = []

        for d in recent:
            raw_str = d.get("nums", "")
            # 取红球部分（+之前）
            red_part = raw_str.split("+")[0]
            digits = [x for x in parse_reds(red_part) if 0 <= x <= 9]
            if len(digits) != 3:
                continue

            # 奇偶形态
            oe = "".join("O" if x % 2 else "E" for x in digits)
            odd_even[oe] += 1

            # 大小形态（>=5为大，<5为小）
            bs = "".join("B" if x >= 5 else "S" for x in digits)
            big_small[bs] += 1

            # 三区分布：0-3为区1，4-6为区2，7-9为区3
            for x in digits:
                if x <= 3:
                    zone_counter["1"] += 1
                elif x <= 6:
                    zone_counter["2"] += 1
                else:
                    zone_counter["3"] += 1

            sums.append(sum(digits))

        # 确保所有常见形态键都存在
        for pattern in ["OOO", "OOE", "OEO", "EOO", "OEE", "EOE", "EEO", "EEE"]:
            if pattern not in odd_even:
                odd_even[pattern] = 0
            if pattern not in big_small:
                big_small[pattern] = 0

        moe = odd_even.most_common(1)[0][0] if odd_even else "OOO"
        mbs = big_small.most_common(1)[0][0] if big_small else "BBB"

        sum_range = (min(sums), max(sums)) if sums else (0, 27)

        zone_dist = {
            "1": zone_counter.get("1", 0),
            "2": zone_counter.get("2", 0),
            "3": zone_counter.get("3", 0),
        }

        return {
            "odd_even": moe,
            "big_small": mbs,
            "odd_even_dist": dict(odd_even),
            "big_small_dist": dict(big_small),
            "sum_range": sum_range,
            "zone_dist": zone_dist,
        }

    # ==================================================================
    # 内部方法：非3D彩种分析
    # ==================================================================

    def _analyze_non_digit(self, recent):
        """分析非3D彩种（双色球/大乐透/七乐彩/快乐8/七星彩）的形态统计"""
        odd_even = Counter()
        big_small = Counter()
        zone_counter = Counter()
        sums = []

        red_rule = self.rule.get("red", (1, 33, 6))
        if isinstance(red_rule, tuple) and len(red_rule) == 3 and isinstance(red_rule[0], int):
            rmin, rmax = red_rule[0], red_rule[1]
        else:
            rmin, rmax = 1, 33

        # 大小中值
        midpoint = (rmin + rmax) / 2.0
        # 三区分界
        span = rmax - rmin + 1
        zone1_end = rmin + span // 3 - 1
        zone2_end = rmin + 2 * span // 3 - 1

        for d in recent:
            raw_str = d.get("nums", "")
            red_part = raw_str.split("+")[0]
            nums = parse_reds(red_part)
            # 过滤有效范围内的号码
            nums = [x for x in nums if rmin <= x <= rmax]
            if not nums:
                continue

            # 奇偶比
            odd_count = sum(1 for x in nums if x % 2 == 1)
            even_count = len(nums) - odd_count
            oe_key = "{}:{}".format(odd_count, even_count)
            odd_even[oe_key] += 1

            # 大小比
            big_count = sum(1 for x in nums if x > midpoint)
            small_count = len(nums) - big_count
            bs_key = "{}:{}".format(big_count, small_count)
            big_small[bs_key] += 1

            # 三区分布
            for x in nums:
                if x <= zone1_end:
                    zone_counter["1"] += 1
                elif x <= zone2_end:
                    zone_counter["2"] += 1
                else:
                    zone_counter["3"] += 1

            sums.append(sum(nums))

        moe = odd_even.most_common(1)[0][0] if odd_even else "3:3"
        mbs = big_small.most_common(1)[0][0] if big_small else "3:3"

        sum_range = (min(sums), max(sums)) if sums else (0, 100)

        zone_dist = {
            "1": zone_counter.get("1", 0),
            "2": zone_counter.get("2", 0),
            "3": zone_counter.get("3", 0),
        }

        return {
            "odd_even": moe,
            "big_small": mbs,
            "odd_even_dist": dict(odd_even),
            "big_small_dist": dict(big_small),
            "sum_range": sum_range,
            "zone_dist": zone_dist,
        }

    # ==================================================================
    # 内部方法：3D/排列三形态检查
    # ==================================================================

    def _check_digit_pattern(self, nums, stats, score, warnings):
        """检查3D类号码的形态合理性"""
        if len(nums) != 3:
            warnings.append("号码长度不为3位")
            score -= 10
            return score, warnings

        # 奇偶形态
        oe = "".join("O" if x % 2 else "E" for x in nums)

        # 大小形态
        bs = "".join("B" if x >= 5 else "S" for x in nums)

        if stats:
            oe_dist = stats.get("odd_even_dist", {})
            bs_dist = stats.get("big_small_dist", {})

            # 极端形态检查：形态在近50期从未出现
            if oe_dist.get(oe, 0) == 0:
                score -= 25
                warnings.append(f"奇偶形态{oe}近50期未出现")

            if bs_dist.get(bs, 0) == 0:
                score -= 25
                warnings.append(f"大小形态{bs}近50期未出现")

            # 全奇/全偶扣分
            if oe in ("OOO", "EEE"):
                score -= 10
                warnings.append(f"极端奇偶形态{oe}，扣分")
        else:
            # 无历史数据时的默认检查
            if oe in ("OOO", "EEE"):
                score -= 15
                warnings.append(f"极端奇偶形态{oe}")

        return score, warnings

    # ==================================================================
    # 内部方法：非3D彩种形态检查
    # ==================================================================

    def _check_non_digit_pattern(self, nums, stats, score, warnings):
        """检查非3D彩种号码的形态合理性"""
        if not nums:
            return score, warnings

        red_rule = self.rule.get("red", (1, 33, 6))
        if isinstance(red_rule, tuple) and len(red_rule) == 3 and isinstance(red_rule[0], int):
            rmin, rmax = red_rule[0], red_rule[1]
        else:
            rmin, rmax = 1, 33

        midpoint = (rmin + rmax) / 2.0

        # 奇偶比
        odd_count = sum(1 for x in nums if x % 2 == 1)
        even_count = len(nums) - odd_count
        oe_key = "{}:{}".format(odd_count, even_count)

        # 大小比
        big_count = sum(1 for x in nums if x > midpoint)
        small_count = len(nums) - big_count
        bs_key = "{}:{}".format(big_count, small_count)

        if stats:
            oe_dist = stats.get("odd_even_dist", {})
            bs_dist = stats.get("big_small_dist", {})

            # 奇偶比在近50期从未出现
            if oe_dist.get(oe_key, 0) == 0:
                score -= 25
                warnings.append(f"奇偶比{oe_key}近50期未出现")

            # 大小比在近50期从未出现
            if bs_dist.get(bs_key, 0) == 0:
                score -= 25
                warnings.append(f"大小比{bs_key}近50期未出现")

            # 全大/全小扣分
            if small_count == 0 or big_count == 0:
                score -= 10
                label = "全大" if small_count == 0 else "全小"
                warnings.append(f"极端大小比{label}({bs_key})，扣分")
        else:
            # 无历史数据时的默认检查
            if small_count == 0 or big_count == 0:
                score -= 15
                label = "全大" if small_count == 0 else "全小"
                warnings.append(f"极端大小比{label}")

        return score, warnings

    # ==================================================================
    # 内部方法：号码拆分
    # ==================================================================

    def _split_digits(self, item):
        """将3D类号码拆分为3个独立数字。

        支持整数（如 358 -> [3, 5, 8]）和字符串（如 "035" -> [0, 3, 5]）。
        """
        if isinstance(item, int):
            # 三位数：百十个
            if item == 0:
                return [0, 0, 0]
            digits = []
            tmp = item
            for _ in range(3):
                digits.append(tmp % 10)
                tmp //= 10
            digits.reverse()
            # 补齐不足3位
            while len(digits) < 3:
                digits.insert(0, 0)
            return digits[:3]
        elif isinstance(item, str):
            cleaned = item.strip().replace(",", "")
            nums = parse_reds(cleaned)
            if len(nums) >= 3:
                return nums[:3]
            return None
        else:
            return None

    def _split_non_digit_nums(self, item):
        """将非3D号码拆分为数字列表。

        支持整数列表、逗号分隔字符串、单整数等格式。
        """
        if isinstance(item, (list, tuple)):
            return [int(x) for x in item if isinstance(x, (int, float)) and 0 < int(x)]
        elif isinstance(item, str):
            nums = parse_reds(item)
            return nums if nums else None
        elif isinstance(item, int):
            # 尝试解析：如果是3D号码格式（如358），此方法不应被调用
            return None
        return None
