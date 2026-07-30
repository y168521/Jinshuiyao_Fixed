# -*- coding: utf-8 -*-
"""金水谣系统 - 遗漏值分析引擎 V1.0
统计每个号码的遗漏期数、历史平均遗漏、突破概率指数
为选号权重提供遗漏维度参考"""

import logging

from utils.number_utils import parse_reds, clean_nums

logger = logging.getLogger(__name__)


class MissAnalyzer:
    """遗漏值分析器：统计每个号码的遗漏期数、历史平均遗漏、突破概率指数"""

    # 彩种 -> (起始, 结束) 号码范围映射
    _RANGE_MAP = {
        "福彩3D": (0, 10),
        "排列三": (0, 10),
        "双色球": (1, 36),
        "大乐透": (1, 36),
        "七乐彩": (1, 31),
        "快乐8": (1, 81),
        "七星彩前区": (0, 10),
        "七星彩后区": (0, 15),
    }

    def __init__(self, lot):
        """
        初始化遗漏分析器。

        Args:
            lot: 彩种名，如 "福彩3D", "双色球", "七星彩前区" 等
        """
        self.lot = lot
        self._result = {}

    def _get_range(self):
        """根据彩种名自动确定号码范围，返回 range 对象"""
        if self.lot in self._RANGE_MAP:
            start, end = self._RANGE_MAP[self.lot]
            return range(start, end)
        # 模糊匹配兜底
        if "七星彩" in self.lot:
            if "后区" in self.lot:
                return range(0, 15)
            return range(0, 10)
        if "3D" in self.lot or "排列三" in self.lot:
            return range(0, 10)
        if "快乐8" in self.lot:
            return range(1, 81)
        if "七乐彩" in self.lot:
            return range(1, 31)
        # 默认按大盘处理
        return range(1, 36)

    def _extract_nums(self, record):
        """从历史记录中提取对应区域的号码列表"""
        nums_str = str(record.get("nums", ""))
        if not nums_str:
            return []
        # 七星彩后区：取 + 号后面的部分
        if "七星彩" in self.lot and "后区" in self.lot and "+" in nums_str:
            parts = nums_str.split("+", 1)
            return parse_reds(clean_nums(parts[1])) if len(parts) > 1 else []
        # 七星彩前区：取 + 号前面的部分
        if "七星彩" in self.lot and "+" in nums_str:
            parts = nums_str.split("+", 1)
            return parse_reds(clean_nums(parts[0]))
        # 其他彩种：直接解析全部号码
        return parse_reds(clean_nums(nums_str))

    def analyze(self, history):
        """
        对历史数据中每个号码计算遗漏统计。

        Args:
            history: 历史数据列表，每个元素有 "nums" 和 "period" 字段，
                     按时间从近到远排列（index 0 为最新一期）

        Returns:
            dict: {num: {"current_miss": int, "avg_miss": float,
                         "max_miss": int, "breakthrough_score": float}}
        """
        num_range = self._get_range()
        result = {}
        for num in num_range:
            current, avg, max_m = self._calc_miss(num, history)
            bt_score = current / avg if avg > 0 else 0.0
            result[num] = {
                "current_miss": current,
                "avg_miss": round(avg, 2),
                "max_miss": max_m,
                "breakthrough_score": round(bt_score, 2),
            }
        self._result = result
        logger.info("[%s] 遗漏分析完成，共 %d 个号码", self.lot, len(result))
        return result

    def _calc_miss(self, num, history):
        """
        计算单个号码的遗漏统计。

        Returns:
            (current_miss, avg_miss, max_miss)
        """
        appear_indices = []
        for i, record in enumerate(history):
            nums = self._extract_nums(record)
            if num in nums:
                appear_indices.append(i)

        if not appear_indices:
            # 号码从未出现过
            return len(history), 0.0, len(history)

        # 当前遗漏：从最新一期（索引 0）到最近一次出现的距离
        current_miss = appear_indices[0]

        # 计算连续出现之间的间隔（已完成的历史间隔）
        gaps = []
        for j in range(1, len(appear_indices)):
            gaps.append(appear_indices[j] - appear_indices[j - 1])

        # 历史平均遗漏周期
        avg_miss = sum(gaps) / len(gaps) if gaps else 0.0

        # 历史最大遗漏 = max(已完成间隔, 当前遗漏)
        max_miss = max(gaps) if gaps else 0
        if current_miss > max_miss:
            max_miss = current_miss

        return current_miss, avg_miss, max_miss

    def get_hot_miss_nums(self, n):
        """
        返回突破概率最高的 n 个号码（即最可能"回补"的冷号）。

        Args:
            n: 返回数量

        Returns:
            list: 按 breakthrough_score 降序排列的 [(num, info), ...]
        """
        if not self._result:
            logger.warning("get_hot_miss_nums 调用前未执行 analyze()")
            return []
        sorted_items = sorted(
            self._result.items(),
            key=lambda x: x[1]["breakthrough_score"],
            reverse=True,
        )
        return sorted_items[:n]

    def get_cold_alerts(self, threshold=1.5):
        """
        返回遗漏突破预警号码列表。

        breakthrough_score > threshold 的号码被视为遗漏超期预警，
        表示该号码遗漏期数已超过历史平均的 threshold 倍，可能即将回补。

        Args:
            threshold: breakthrough_score 阈值，默认 1.5

        Returns:
            list: breakthrough_score > threshold 的 [(num, info), ...]，
                  按 breakthrough_score 降序排列
        """
        if not self._result:
            logger.warning("get_cold_alerts 调用前未执行 analyze()")
            return []
        alerts = [
            (num, info)
            for num, info in self._result.items()
            if info["breakthrough_score"] > threshold
        ]
        alerts.sort(key=lambda x: x[1]["breakthrough_score"], reverse=True)
        return alerts

    def adjust_weights(self, base_weights):
        """
        将遗漏突破指数融入基础热号权重。

        公式：adjusted = base * (1 + 0.3 * breakthrough_score)
        breakthrough_score 上限封顶为 2.0，防止过度放大。

        Args:
            base_weights: dict {num: weight}，基础热号权重

        Returns:
            dict: {num: adjusted_weight}，调整后的权重
        """
        if not self._result:
            logger.warning("adjust_weights 调用前未执行 analyze()")
            return dict(base_weights)
        adjusted = {}
        for num, base_w in base_weights.items():
            info = self._result.get(num)
            if info:
                bt = min(info["breakthrough_score"], 2.0)
                adjusted[num] = round(base_w * (1 + 0.3 * bt), 4)
            else:
                adjusted[num] = base_w
        logger.info("[%s] 权重调整完成，共 %d 个号码", self.lot, len(adjusted))
        return adjusted

    @staticmethod
    def get_missing(num, history):
        """
        计算单个号码的当前遗漏期数（静态方法，不依赖实例状态）。

        遍历历史数据，找到号码最近一次出现的位置索引即为遗漏期数。
        若号码从未出现，返回历史数据总长度。

        Args:
            num: 要查询的号码（int）
            history: 历史数据列表，每个元素有 "nums" 字段

        Returns:
            int: 当前遗漏期数
        """
        for i, record in enumerate(history):
            nums_str = str(record.get("nums", ""))
            nums = parse_reds(clean_nums(nums_str))
            if num in nums:
                return i
        return len(history)
