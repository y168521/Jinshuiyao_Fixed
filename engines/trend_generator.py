# -*- coding: utf-8 -*-
"""金水谣系统 - 走势图数据生成器 V1.0
从历史开奖数据提取走势指标供ECharts可视化"""

import json
import os
import time
import logging
from datetime import datetime
from collections import Counter

from utils.number_utils import parse_reds, clean_nums

logger = logging.getLogger(__name__)

# 3D类型彩种（号码范围0-9，按百十个位）
_DIGIT_LOTS = {"福彩3D", "排列三"}

# 彩种号码范围映射（非3D彩种，红球号码范围）
_NUM_RANGE_MAP = {
    "双色球": range(1, 34),
    "大乐透": range(1, 36),
    "七乐彩": range(1, 31),
    "快乐8": range(1, 81),
    "七星彩": range(0, 10),
}

# 彩种三区划分（仅对非3D大盘彩种有意义）
_ZONE_MAP = {
    "双色球": (1, 12, 23, 34),   # zone1: 1-11, zone2: 12-22, zone3: 23-33
    "大乐透": (1, 13, 25, 36),   # zone1: 1-12, zone2: 13-24, zone3: 25-35
    "七乐彩": (1, 11, 21, 31),   # zone1: 1-10, zone2: 11-20, zone3: 21-30
    "快乐8": (1, 27, 54, 81),    # zone1: 1-26, zone2: 27-53, zone3: 54-80
    "七星彩": (0, 4, 7, 10),     # zone1: 0-3, zone2: 4-6, zone3: 7-9
}


class TrendGenerator:
    """走势图数据生成器：从历史开奖数据提取走势指标供ECharts可视化"""

    def __init__(self, data_dir):
        """
        初始化走势生成器。

        Args:
            data_dir: 数据目录路径（金水谣数据的上级目录，包含 lot_data/ 子目录）
        """
        self.data_dir = data_dir
        self.lot_data_dir = os.path.join(data_dir, "lot_data")

    def generate_all(self, output_dir):
        """
        生成所有彩种的走势数据，输出为 JS 文件供 HTML 直接引用。

        扫描 data_dir/lot_data/ 下所有 JSON 文件，对每个彩种调用 generate_lottery()，
        最终将所有数据合并写入 output_dir/trend-data.js。

        Args:
            output_dir: JS 输出目录

        Returns:
            str: 生成的 trend-data.js 文件的绝对路径
        """
        if not os.path.isdir(self.lot_data_dir):
            logger.error("数据目录不存在: %s", self.lot_data_dir)
            return ""

        os.makedirs(output_dir, exist_ok=True)
        all_data = {}

        for filename in sorted(os.listdir(self.lot_data_dir)):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(self.lot_data_dir, filename)
            lot_name = filename.replace(".json", "")

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("读取 %s 失败: %s", filepath, e)
                continue

            if not isinstance(history, list) or len(history) == 0:
                logger.warning("数据为空或格式错误: %s", lot_name)
                continue

            try:
                trend = self.generate_lottery(lot_name, history)
                if trend:
                    all_data[lot_name] = trend
                    logger.info("[%s] 走势数据生成完成", lot_name)
            except Exception as e:
                logger.error("[%s] 走势生成异常: %s", lot_name, e)

        # 写入 JS 文件
        out_path = os.path.join(output_dir, "trend-data.js")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("window.TREND_DATA = ")
            json.dump(all_data, f, ensure_ascii=False, indent=2)
            f.write(";")

        logger.info("走势数据已写入 %s，共 %d 个彩种", out_path, len(all_data))
        return os.path.abspath(out_path)

    def generate_lottery(self, lot_name, history):
        """
        对单个彩种生成走势数据。

        3D/排列三生成: digit_trend, frequency_heatmap, miss_chart, hot_cold_trend
        其他彩种生成: red_trend, miss_chart, zone_distribution

        Args:
            lot_name: 彩种名称，如 "福彩3D", "双色球" 等
            history: 历史开奖数据列表，每项含 period/nums 字段，按时间从早到晚排列

        Returns:
            dict: 该彩种的走势数据字典
        """
        # 确保历史按期号从新到旧排列（索引0最新）
        history = list(reversed(history))

        if lot_name in _DIGIT_LOTS:
            return self._generate_digit_trend(lot_name, history)
        else:
            return self._generate_big_trend(lot_name, history)

    # ------------------------------------------------------------------
    # 3D / 排列三 走势
    # ------------------------------------------------------------------

    def _generate_digit_trend(self, lot_name, history):
        """3D/排列三走势：digit_trend, frequency_heatmap, miss_chart, hot_cold_trend"""
        recent = history[:50]
        result = {}
        result["digit_trend"] = self._digit_trend(recent)
        result["frequency_heatmap"] = self._frequency_heatmap(recent)
        result["miss_chart"] = self._miss_chart_digit(recent)
        result["hot_cold_trend"] = self._hot_cold_trend(recent)
        return result

    def _digit_trend(self, recent):
        """
        按位走势：提取最近50期的百位、十位、个位号码。

        Returns:
            dict: {"百位": [{period, num}, ...], "十位": [...], "个位": [...]}
        """
        pos_names = ["百位", "十位", "个位"]
        result = {name: [] for name in pos_names}

        for record in reversed(recent):  # 从旧到新排列，ECharts X轴时间递增
            period_str = str(record.get("period", ""))
            nums = parse_reds(clean_nums(str(record.get("nums", ""))))
            for idx, name in enumerate(pos_names):
                if idx < len(nums):
                    result[name].append({"period": period_str, "num": nums[idx]})
                else:
                    result[name].append({"period": period_str, "num": 0})

        return result

    def _frequency_heatmap(self, recent):
        """
        号码频率热力图：统计最近50期中0-9在每个位置出现的次数。

        Returns:
            list: 3行10列，data[i][j] = 号码j在第i位出现的次数
        """
        # 3行(百位/十位/个位) x 10列(号码0-9)
        counts = [[0] * 10 for _ in range(3)]

        for record in recent:
            nums = parse_reds(clean_nums(str(record.get("nums", ""))))
            for pos in range(3):
                if pos < len(nums):
                    num = nums[pos]
                    if 0 <= num <= 9:
                        counts[pos][num] += 1

        return counts

    def _miss_chart_digit(self, recent):
        """
        遗漏值折线图：对0-9每个号码，生成最近30期的遗漏期数序列。

        Returns:
            dict: {"dates": [...], "series": [{name, data}, ...]}
        """
        window = min(30, len(recent))
        # 取最近30期（从旧到新排列），dates 为这30期的期号
        period_slice = list(reversed(recent[-window:]))
        dates = [str(r.get("period", "")) for r in period_slice]

        series = []
        for num in range(10):
            miss_data = []
            # 对每一期，计算从该期往回看，该号码连续未出现的期数
            for i, record in enumerate(period_slice):
                miss = 0
                for j in range(i, -1, -1):
                    nums_j = parse_reds(clean_nums(str(period_slice[j].get("nums", ""))))
                    if num in nums_j:
                        break
                    miss += 1
                else:
                    # i=0 且未出现，向前追溯到 period_slice 之前的数据
                    # 需要从 recent 中 period_slice[0] 之前的数据继续追溯
                    base_idx = len(recent) - window
                    for k in range(base_idx - 1, -1, -1):
                        nums_k = parse_reds(clean_nums(str(recent[k].get("nums", ""))))
                        if num in nums_k:
                            break
                        miss += 1
                    else:
                        miss = window  # 整个 recent 都没出现过
                miss_data.append(miss)
            series.append({"name": f"{num}号", "data": miss_data})

        return {"dates": dates, "series": series}

    def _hot_cold_trend(self, recent):
        """
        冷热号趋势：统计最近50期，每期的热号数、温号数、冷号数。

        热号：最近10期出现>=3次；温号：出现1-2次；冷号：出现0次。

        Returns:
            dict: {"dates": [...], "hot": [...], "warm": [...], "cold": [...]}
        """
        dates = []
        hot_list = []
        warm_list = []
        cold_list = []

        # 从旧到新遍历最近50期
        for i in range(len(recent) - 1, -1, -1):
            record = recent[i]
            dates.append(str(record.get("period", "")))

            # 最近10期窗口（含当前期，索引 i 到 i+9）
            window_end = min(i + 10, len(recent))
            window_records = recent[i:window_end]

            # 统计0-9每个号码在窗口内出现的次数
            freq = Counter()
            for wr in window_records:
                nums = parse_reds(clean_nums(str(wr.get("nums", ""))))
                for n in nums:
                    if 0 <= n <= 9:
                        freq[n] += 1

            hot = sum(1 for n in range(10) if freq[n] >= 3)
            warm = sum(1 for n in range(10) if 1 <= freq[n] <= 2)
            cold = sum(1 for n in range(10) if freq[n] == 0)

            hot_list.append(hot)
            warm_list.append(warm)
            cold_list.append(cold)

        return {"dates": dates, "hot": hot_list, "warm": warm_list, "cold": cold_list}

    # ------------------------------------------------------------------
    # 非3D彩种走势（双色球/大乐透/七乐彩等）
    # ------------------------------------------------------------------

    def _generate_big_trend(self, lot_name, history):
        """大盘彩种走势：red_trend, miss_chart, zone_distribution, blue_ball, sum_value, oddeven"""
        recent = history[:50]
        result = {}
        result["red_trend"] = self._red_trend(recent, lot_name)
        result["miss_chart"] = self._miss_chart_big(recent, lot_name)
        result["zone_distribution"] = self._zone_distribution(recent, lot_name)
        # 有蓝球的彩种额外生成蓝球走势 + 和值 + 奇偶比
        if lot_name in ("双色球", "大乐透"):
            result["blue_ball_trend"] = self._blue_ball_trend(recent, lot_name)
            result["sum_value"] = self._sum_value_chart(recent, lot_name)
            result["oddeven_ratio"] = self._oddeven_ratio(recent, lot_name)
        return result

    def _red_trend(self, recent, lot_name):
        """
        红球号码散点图：最近50期，每期所有红球号码。

        Args:
            recent: 最近50期历史数据（索引0最新）
            lot_name: 彩种名称

        Returns:
            list: [{period: "2026001", nums: [3,8,15,...]}, ...]
        """
        result = []
        for record in reversed(recent):  # 从旧到新
            period_str = str(record.get("period", ""))
            nums_str = str(record.get("nums", ""))

            # 只取红球部分（+号之前）
            red_str = nums_str.split("+")[0] if "+" in nums_str else nums_str
            reds = parse_reds(clean_nums(red_str))

            result.append({"period": period_str, "nums": reds})

        return result

    def _miss_chart_big(self, recent, lot_name):
        """
        遗漏折线图（大盘彩种）：对号码范围内每个号码，生成最近30期的遗漏期数序列。

        Args:
            recent: 最近50期历史数据
            lot_name: 彩种名称

        Returns:
            dict: {"dates": [...], "series": [{name, data}, ...]}
        """
        num_range = _NUM_RANGE_MAP.get(lot_name, range(1, 34))
        window = min(30, len(recent))
        period_slice = list(reversed(recent[-window:]))
        dates = [str(r.get("period", "")) for r in period_slice]

        series = []
        for num in num_range:
            miss_data = []
            for i in range(len(period_slice)):
                miss = 0
                found = False
                # 从当前期往回找
                for j in range(i, -1, -1):
                    nums_j = self._extract_reds(period_slice[j], lot_name)
                    if num in nums_j:
                        found = True
                        break
                    miss += 1

                if not found:
                    # 继续追溯到 period_slice 之前的数据
                    base_idx = len(recent) - window
                    for k in range(base_idx - 1, -1, -1):
                        nums_k = self._extract_reds(recent[k], lot_name)
                        if num in nums_k:
                            break
                        miss += 1
                    else:
                        miss = window

                miss_data.append(miss)
            series.append({"name": f"{num}号", "data": miss_data})

        return {"dates": dates, "series": series}

    def _zone_distribution(self, recent, lot_name):
        """
        三区分布：最近50期每期号码在三区的分布。

        Args:
            recent: 最近50期历史数据
            lot_name: 彩种名称

        Returns:
            dict: {"dates": [...], "zone1": [...], "zone2": [...], "zone3": [...]}
        """
        dates = []
        zone1_list = []
        zone2_list = []
        zone3_list = []

        zones = _ZONE_MAP.get(lot_name)
        if not zones:
            return {"dates": [], "zone1": [], "zone2": [], "zone3": []}

        z1_start, z2_start, z3_start, z3_end = zones

        for record in reversed(recent):  # 从旧到新
            dates.append(str(record.get("period", "")))
            reds = self._extract_reds(record, lot_name)

            c1 = sum(1 for n in reds if z1_start <= n < z2_start)
            c2 = sum(1 for n in reds if z2_start <= n < z3_start)
            c3 = sum(1 for n in reds if z3_start <= n < z3_end)

            zone1_list.append(c1)
            zone2_list.append(c2)
            zone3_list.append(c3)

        return {"dates": dates, "zone1": zone1_list, "zone2": zone2_list, "zone3": zone3_list}

    def _blue_ball_trend(self, recent, lot_name):
        """蓝球号码走势：最近50期，每期的蓝球号码列表。

        双色球=1蓝球，大乐透=2蓝球。

        Returns:
            list: [{period: "2026001", nums: [3]}, ...]
        """
        is_dlt = lot_name == "大乐透"
        result = []
        for record in reversed(recent):
            period_str = str(record.get("period", ""))
            nums_str = str(record.get("nums", ""))
            if "+" not in nums_str:
                result.append({"period": period_str, "nums": []})
                continue
            blue_str = nums_str.split("+")[1] if "+" in nums_str else ""
            blues = parse_reds(clean_nums(blue_str))
            result.append({"period": period_str, "nums": blues})
        return result

    def _sum_value_chart(self, recent, lot_name):
        """和值/跨度走势：最近50期每期的红球和值与红球跨度。

        Returns:
            dict: {
                "dates": ["2026144", ...],
                "red_sum": [82, 95, ...],       # 红球和值
                "red_span": [27, 21, ...],      # 红球跨度(最大-最小)
            }
        """
        dates = []
        red_sums = []
        red_spans = []
        for record in reversed(recent):
            period_str = str(record.get("period", ""))
            dates.append(str(period_str))
            nums_str = str(record.get("nums", ""))
            red_str = nums_str.split("+")[0] if "+" in nums_str else nums_str
            reds = parse_reds(clean_nums(red_str))
            if reds:
                red_sums.append(sum(reds))
                red_spans.append(max(reds) - min(reds))
            else:
                red_sums.append(0)
                red_spans.append(0)
        return {"dates": dates, "red_sum": red_sums, "red_span": red_spans}

    def _oddeven_ratio(self, recent, lot_name):
        """奇偶比趋势：最近50期每期的奇偶号码数量。

        Returns:
            dict: {
                "dates": ["2026144", ...],
                "odd": [3, 2, ...],   # 奇数个数
                "even": [3, 4, ...],  # 偶数个数
            }
        """
        dates = []
        odds = []
        evens = []
        for record in reversed(recent):
            period_str = str(record.get("period", ""))
            dates.append(str(period_str))
            nums_str = str(record.get("nums", ""))
            red_str = nums_str.split("+")[0] if "+" in nums_str else nums_str
            reds = parse_reds(clean_nums(red_str))
            odd_n = sum(1 for n in reds if n % 2 == 1)
            even_n = len(reds) - odd_n
            odds.append(odd_n)
            evens.append(even_n)
        return {"dates": dates, "odd": odds, "even": evens}

    # ------------------------------------------------------------------
    # 单彩种生成（供 API 分片调用）
    # ------------------------------------------------------------------

    def _load_lot_data(self, lot_name):
        """加载单个彩种的 JSON 数据文件。

        Args:
            lot_name: 彩种名称，如 "福彩3D"

        Returns:
            list: 历史开奖数据列表，文件不存在或解析失败返回空列表
        """
        filepath = os.path.join(self.lot_data_dir, lot_name + ".json")
        if not os.path.isfile(filepath):
            logger.warning("文件不存在: %s", filepath)
            return []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list) or len(history) == 0:
                logger.warning("数据为空或格式错误: %s", lot_name)
                return []
            return history
        except (json.JSONDecodeError, IOError) as e:
            logger.error("读取 %s 失败: %s", filepath, e)
            return []

    def generate_lot(self, lot_name):
        """生成单个彩种的走势数据，含新鲜度元数据。

        与 generate_all() 不同，本方法不写文件，返回 dict 供 API 序列化。

        Args:
            lot_name: 彩种名称

        Returns:
            dict: {
                "lot": "福彩3D",
                "generated_at": 1750000000.0,    # 生成时间戳
                "generated_at_str": "2026-07-23 21:00:00",
                "period_count": 856,
                "period_range": {"start": "2024001", "end": "2026123"},
                "file_mtime": 1750000000.0,       # 数据文件 mtime
                "data": { /* 走势数据，同 generate_lottery 返回格式 */ }
            }
            数据文件不存在或解析失败返回 None
        """
        history = self._load_lot_data(lot_name)
        if not history:
            return None

        # 生成走势数据
        trend_data = self.generate_lottery(lot_name, history)

        # 新鲜度元数据
        filepath = os.path.join(self.lot_data_dir, lot_name + ".json")
        file_mtime = 0.0
        if os.path.isfile(filepath):
            file_mtime = os.path.getmtime(filepath)

        now_ts = time.time()
        periods = [str(r.get("period", "")) for r in history if r.get("period")]
        period_start = min(periods) if periods else ""
        period_end = max(periods) if periods else ""

        return {
            "lot": lot_name,
            "generated_at": now_ts,
            "generated_at_str": datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S"),
            "file_mtime": file_mtime,
            "period_count": len(history),
            "period_range": {"start": period_start, "end": period_end},
            "stale": False,
            "data": trend_data or {},
        }

    def get_all_lot_names(self):
        """获取所有彩种名称列表（按 lot_data 目录下的 JSON 文件）。

        Returns:
            list: ["福彩3D", "排列三", "双色球", ...]
        """
        names = []
        if not os.path.isdir(self.lot_data_dir):
            return names
        for filename in sorted(os.listdir(self.lot_data_dir)):
            if filename.endswith(".json") and not filename.startswith("_"):
                names.append(filename.replace(".json", ""))
        return names

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_reds(record, lot_name):
        """
        从记录中提取红球号码列表。

        Args:
            record: 单期开奖记录
            lot_name: 彩种名称

        Returns:
            list: 红球号码列表
        """
        nums_str = str(record.get("nums", ""))
        if not nums_str:
            return []
        # 取 + 号之前的部分作为红球
        red_str = nums_str.split("+")[0] if "+" in nums_str else nums_str
        return parse_reds(clean_nums(red_str))
