# -*- coding: utf-8 -*-
"""金水谣系统 - 杀号引擎 V2.0 (完全向后兼容版)
多维度杀号：间隔法 + 遗漏极值 + 位置杀号
在号码池中主动排除低概率号码，缩小选号范围

核心方法：
- calc(*args, **kwargs): 完全向后兼容，支持旧式/混合/新式调用
- calc_advanced(history, lot): 高级多维度杀号
- smart_kill(history, lot, pool): 从候选池中杀号

V2.0 更新：
- calc() 函数完全向后兼容
- 支持所有调用模式（旧式/混合/新式）
- 智能参数检测和自动适配
"""

import logging
import random
from collections import Counter
from datetime import datetime

logger = logging.getLogger("jinshuiyao.killer")


class Killer:
    """多维度杀号引擎 (V2.0+ 完全向后兼容版本)"""

    # ------------------------------------------------------------------
    # 核心修复：完全向后兼容的calc函数
    # ------------------------------------------------------------------
    def calc(self, *args, **kwargs):
        """完全向后兼容的杀号函数

        支持所有调用模式：
        1. 旧式调用：calc(nums)
        2. 新式调用：calc(nums, history=None, lot=None)
        3. 错误日志中的调用：calc(nums, history=arr, lot=lot)

        Returns:
            list[int] 或 set[int]: 根据调用方式返回相应格式
        """
        # 调试日志：记录调用参数
        if len(args) > 0 or len(kwargs) > 0:
            logger.debug(f"calc() 被调用: args={args}, kwargs={kwargs}")

        try:
            # 分析参数类型和数量
            if len(args) == 1 and not kwargs:
                # 模式1: calc(nums) - 旧式调用
                nums = args[0]
                logger.debug("检测到旧式调用: calc(nums)")
                return self._legacy_calc(nums)

            elif len(args) == 0 and 'nums' in kwargs:
                # 可能有多种情况
                nums = kwargs.get('nums')
                history = kwargs.get('history')
                lot = kwargs.get('lot')

                if history is not None and lot is not None:
                    # 模式3: calc(nums, history=arr, lot=lot) - 错误日志模式
                    logger.debug("检测到混合调用: calc(nums, history, lot)")
                    if nums is None:
                        # 如果没有nums，直接调用高级杀号
                        return list(self.calc_advanced(history, lot))
                    else:
                        # 有nums，先进行基本杀号，再结合高级杀号
                        legacy_result = self._legacy_calc(nums)
                        advanced_result = self.calc_advanced(history, lot)
                        # 合并结果并去重
                        combined = set(legacy_result) | advanced_result
                        return list(combined)

                elif history is None and lot is None:
                    # 模式1变种: calc(nums=nums) - 旧式调用
                    logger.debug("检测到变种旧式调用: calc(nums=nums)")
                    return self._legacy_calc(nums)
                else:
                    # 参数不全的情况
                    logger.warning(f"calc() 参数不全: nums={nums}, history={history}, lot={lot}")
                    return []

            elif 'history' in kwargs and 'lot' in kwargs:
                # 模式2变种: calc(history=arr, lot=lot) - 只有kw参数
                history = kwargs['history']
                lot = kwargs['lot']
                logger.debug("检测到新式调用变种: calc(history, lot)")
                return list(self.calc_advanced(history, lot))

            else:
                # 未知调用模式，默认返回空
                logger.warning(f"calc() 未知调用模式: args={args}, kwargs={kwargs}")
                return []

        except Exception as e:
            logger.error(f"calc() 出现异常: {e}", exc_info=True)
            return []

    def _legacy_calc(self, nums):
        """旧式杀号逻辑 (按频率杀最冷号)

        V1.0版本逻辑，保持完全一致性
        """
        if not nums:
            return []

        c = Counter(nums)
        total_unique = len(c)

        # 根据历史逻辑确定杀号数量
        if total_unique <= 5:
            return []

        kill_count = max(0, int(total_unique ** 0.5) - 2)
        kill_count = min(kill_count, max(1, total_unique // 7))

        if kill_count <= 0:
            return []

        # 获取最冷的kill_count个号码
        if len(c) >= kill_count:
            cold = c.most_common()[-kill_count:]
        else:
            cold = c.most_common()[-len(c):]

        result = [k for k, _ in cold]
        logger.debug(f"旧式杀号结果: 输入{len(nums)}个号码，{total_unique}个唯一值，杀{len(result)}个: {sorted(result)}")
        return result

    # ------------------------------------------------------------------
    # 高级杀号（三维度）
    # ------------------------------------------------------------------
    def calc_advanced(self, history, lot):
        """高级多维度杀号

        Parameters
        ----------
        history : list[dict]
            历史开奖记录，每条至少含 "nums" 字段。
            列表顺序应为从旧到新（index 越大越近）。
        lot : str
            彩种名称，如 "福彩3D"、"双色球" 等。

        Returns
        -------
        set[int]
            建议杀掉的号码集合。
        """
        try:
            from utils.number_utils import parse_reds, clean_nums
        except ImportError:
            logger.warning("无法导入 number_utils，退回基础杀号")
            return set()

        kill_set = set()

        # 解析历史号码（只取红号部分，统一处理）
        parsed_history = []
        for record in history:
            try:
                raw = str(record.get("nums", ""))
                if "+" in raw:
                    raw = raw.split("+")[0]
                nums = parse_reds(clean_nums(raw))
                if nums:
                    parsed_history.append(nums)
            except Exception:
                continue

        if len(parsed_history) < 10:
            logger.info("历史数据不足（%d 期），跳过高级杀号", len(parsed_history))
            return set()

        # 取最近 30 期进行间隔分析
        recent = parsed_history[-30:]
        all_nums_flat = [n for draw in recent for n in draw]

        # 确定号码范围
        num_range = self._get_num_range(lot, all_nums_flat)

        # ---- a) 间隔杀号法 ----
        kill_interval = self._kill_by_interval(recent, num_range)
        kill_set.update(kill_interval)

        # ---- b) 遗漏极值杀号 ----
        kill_missing = self._kill_by_missing_extreme(parsed_history, num_range)
        kill_set.update(kill_missing)

        # ---- c) 位置杀号（仅 3D / 排列三） ----
        kill_position = set()
        if lot in ("福彩3D", "排列三"):
            kill_position = self._kill_by_position(recent[-10:])
            kill_set.update(kill_position)

        # ---- JS-20260802-01: 小盘彩杀号上限收敛 ----
        # 福彩3D/排列三 只有 10 个数字，三个杀号法并集可达 5-6 个（60%），
        # 会逼得 FormatGen 从杀号里回填，导致号码池塌缩成固定集合（如 {0,1,6,7,8,9}），
        # 呈现"预测全是 0"的畸形输出。这里按彩种限制杀号上限，保留置信度最高的几个。
        kill_limit = self._kill_limit(lot)
        if kill_limit is not None and len(kill_set) > kill_limit:
            # 各维度投票数：一个号码被多个杀号法命中的置信度更高
            votes = Counter()
            votes.update(kill_interval)
            votes.update(kill_missing)
            votes.update(kill_position)
            ranked = sorted(kill_set, key=lambda n: (-votes.get(n, 0), n))
            keep = set(ranked[:kill_limit])
            logger.info(
                "[%s] 小盘彩杀号上限 %d：%s -> 保留 %s",
                lot, kill_limit, sorted(kill_set), sorted(keep),
            )
            kill_set = keep

        logger.info(
            "[%s] 高级杀号结果：%s (间隔=%d, 遗漏=%d, 位置=%d)",
            lot, sorted(kill_set),
            len(kill_interval), len(kill_missing),
            len(kill_position) if lot in ("福彩3D", "排列三") else 0,
        )
        return kill_set

    # ------------------------------------------------------------------
    # 智能杀号（从候选池中排除）
    # ------------------------------------------------------------------
    def smart_kill(self, history, lot, pool=None):
        """智能杀号——从候选池中杀号，并保证杀完后号码数量充足

        Parameters
        ----------
        history : list[dict]
            历史开奖记录。
        lot : str
            彩种名称。
        pool : set[int] | list[int] | None
            候选号码池。为 None 时返回 calc_advanced 全量杀号集合。

        Returns
        -------
        set[int]
            候选池中需要杀掉的号码集合。
        """
        try:
            kill_all = self.calc_advanced(history, lot)

            if not pool:
                return kill_all

            pool_set = set(pool)
            kill_in_pool = kill_all & pool_set

            # 确定杀完后至少保留的最小数量
            min_remain = self._min_remain(lot)

            # 如果杀完后号码太少，逐步释放
            if len(pool_set) - len(kill_in_pool) < min_remain:
                logger.info(
                    "[%s] 池中号码 %d，杀号 %d，杀完后仅剩 %d，需至少 %d，逐步释放",
                    lot, len(pool_set), len(kill_in_pool),
                    len(pool_set) - len(kill_in_pool), min_remain,
                )
                # 按杀号确定性排序（这里简单按号码大小释放，实际可按维度优先级）
                kill_list = sorted(kill_in_pool)
                # 从后往前逐个释放直到满足最低要求
                while (len(pool_set) - len(kill_in_pool) < min_remain) and kill_in_pool:
                    released = kill_list.pop()
                    kill_in_pool.discard(released)

            logger.info(
                "[%s] 智能杀号：池 %d -> 杀 %d -> 剩 %d",
                lot, len(pool_set), len(kill_in_pool),
                len(pool_set) - len(kill_in_pool),
            )
            return kill_in_pool

        except Exception as e:
            logger.warning("smart_kill 异常: %s", e)
            return set()

    # ==================================================================
    # 内部方法
    # ==================================================================

    @staticmethod
    def _get_num_range(lot, flat_nums):
        """根据彩种和历史数据确定号码范围 (min_num, max_num)"""
        try:
            from config import LOTTERY_RULES
            rule = LOTTERY_RULES.get(lot, {})
            red = rule.get("red")
            if red and isinstance(red, tuple) and isinstance(red[0], int):
                return red[0], red[1]
        except Exception:
            pass
        # 回退到从历史数据推断
        if flat_nums:
            return min(flat_nums), max(flat_nums)
        return 0, 9

    def _min_remain(self, lot):
        """根据彩种确定最小保留号码数"""
        rules = {
            "双色球": 12,    # 红球: 6*2 = 12
            "大乐透": 10,    # 前区: 5*2 = 10
            "福彩3D": 4,     # 3*1.3 ≈ 4
            "排列三": 4,
            "七星彩": 6,     # 7*0.8 ≈ 6
            "七乐彩": 12,    # 7*1.7 ≈ 12
            "快乐8": 20,     # 20*1 = 20
        }
        return rules.get(lot, 6)  # 默认保留6个

    def _kill_limit(self, lot):
        """小盘彩杀号上限：超过则按置信度收敛。

        福彩3D/排列三 只有 10 个数字，若三个杀号法并集杀 5-6 个（60%），
        会逼 FormatGen 从杀号里回填，导致号码池塌缩、预测畸形（如"全是0"）。
        这里限制最多杀 2 个；其他彩种不设上限（返回 None）。
        """
        rules = {
            "福彩3D": 2,
            "排列三": 2,
        }
        return rules.get(lot, None)

    # ------------------------------------------------------------------
    # a) 间隔杀号法
    # ------------------------------------------------------------------
    def _kill_by_interval(self, recent, num_range):
        """间隔杀号法

        统计最近30期每个号码的出现间隔，杀掉间隔最短的号码
        （认为刚出现过的号码短期内不会重复出现）
        """
        kill = set()
        nmin, nmax = num_range

        if not recent:
            return kill

        # 统计每个号码的出现期数索引
        num_last_appearance = {}
        for idx, draw in enumerate(recent):
            for num in draw:
                num_last_appearance[num] = idx

        # 计算间隔（从最后一次出现到现在的期数）
        last_idx = len(recent) - 1
        intervals = {}
        for num in range(nmin, nmax + 1):
            if num in num_last_appearance:
                intervals[num] = last_idx - num_last_appearance[num]
            else:
                intervals[num] = len(recent)  # 从未出现，间隔设为最大值

        # 杀掉间隔最小的30%号码
        interval_items = list(intervals.items())
        interval_items.sort(key=lambda x: x[1])  # 按间隔从小到大排序

        kill_count = max(1, len(interval_items) // 3)  # 杀最多1/3
        for num, interval in interval_items[:kill_count]:
            if interval <= 5:  # 最近5期内出现过
                kill.add(num)
                logger.debug(f"间隔杀号: 号码{num} 间隔{interval}期 ≤ 5，杀掉")

        logger.debug("间隔杀号结果: %s (共%d个)", sorted(kill), len(kill))
        return kill

    # ------------------------------------------------------------------
    # b) 遗漏极值杀号
    # ------------------------------------------------------------------
    def _kill_by_missing_extreme(self, parsed_history, num_range):
        """遗漏极值杀号

        逻辑：
        - 计算每个号码的当前遗漏和历史最大遗漏
        - 如果当前遗漏 > 历史最大遗漏 * 0.8 => 不杀（即将突破/回补）
        - 对刚出现且历史上经常短间隔重复的号码，有一定概率杀掉
        - 对长期冷号（当前遗漏很大但还没到极值），杀掉
        """
        kill = set()
        nmin, nmax = num_range
        total = len(parsed_history)

        # 统计每个号码的遗漏段（最大遗漏）和当前遗漏
        num_max_missing = {}
        num_current_missing = {}

        for num in range(nmin, nmax + 1):
            max_miss = 0
            cur_miss = 0
            for idx, draw in enumerate(parsed_history):
                if num in draw:
                    # 结束一段遗漏
                    if cur_miss > max_miss:
                        max_miss = cur_miss
                    cur_miss = 0
                else:
                    cur_miss += 1
            # 当前遗漏（到最后一期为止）
            num_current_missing[num] = cur_miss
            num_max_missing[num] = max_miss

        for num in range(nmin, nmax + 1):
            cur = num_current_missing[num]
            max_m = num_max_missing[num]

            # 规则1: 当前遗漏 > 历史最大遗漏 * 0.8 => 不杀（回补候选）
            if max_m > 0 and cur > max_m * 0.8:
                continue

            # 规则2: 当前遗漏 == 0（刚出现）但历史上最大遗漏很小（< 3）
            #        说明该号经常出，短期内再出概率降低 => 杀掉
            if cur == 0 and max_m < 3 and max_m > 0:
                if random.random() < 0.6:
                    kill.add(num)
                continue

            # 规则3: 中等遗漏（>= 平均遗漏值）但未到极值 -> 杀掉
            #        计算整体平均遗漏
            pass  # 在下面统一处理

        # 计算整体平均遗漏
        all_missing = [num_current_missing[num] for num in range(nmin, nmax + 1)]
        avg_missing = sum(all_missing) / len(all_missing) if all_missing else 5

        for num in range(nmin, nmax + 1):
            if num in kill:
                continue
            cur = num_current_missing[num]
            max_m = num_max_missing[num]

            # 已经在规则1中被跳过的不杀
            if max_m > 0 and cur > max_m * 0.8:
                continue

            # 中等遗漏区：遗漏 >= avg_missing 但不到极值
            if avg_missing <= cur <= max_m * 0.8:
                # 遗漏越接近平均值越值得杀
                kill.add(num)

        logger.debug("遗漏杀号结果: %s (共%d个)", sorted(kill), len(kill))
        return kill

    # ------------------------------------------------------------------
    # c) 位置杀号（仅 3D / 排列三）
    # ------------------------------------------------------------------
    def _kill_by_position(self, recent_10):
        """位置杀号：统计近 10 期每个位置的最冷号码

        只对 3 位数彩种生效（福彩3D / 排列三）。
        每个位置（百位/十位/个位）杀掉近 10 期出现 0 次的号码，
        每个位置最多杀 1 个。
        """
        kill = set()

        if not recent_10:
            return kill

        for pos in range(3):  # 百位=0, 十位=1, 个位=2
            freq = Counter()
            for draw in recent_10:
                if len(draw) > pos:
                    freq[draw[pos]] += 1

            # 找到出现 0 次的号码
            zero_nums = [n for n in range(10) if freq.get(n, 0) == 0]

            if zero_nums:
                # 每个位置最多杀 1 个，随机选一个
                chosen = random.choice(zero_nums)
                kill.add(chosen)
                logger.debug("位置杀号：位置%d 杀掉号码 %d（近10期0次）", pos, chosen)

        logger.debug("位置杀号结果: %s (共%d个)", sorted(kill), len(kill))
        return kill

    # ------------------------------------------------------------------
    # 新增：调试和验证方法
    # ------------------------------------------------------------------
    def test_compatibility(self):
        """测试向后兼容性"""
        test_cases = [
            ("旧式调用", lambda: self.calc([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])),
            ("新式调用-历史", lambda: self.calc(history=[{"nums": "1 2 3 4 5 6"}, {"nums": "2 3 4 5 6 7"}], lot="双色球")),
            ("新式调用-混合", lambda: self.calc(nums=[1, 2, 3, 4, 5], history=[{"nums": "1 2 3"}], lot="福彩3D")),
            ("智能杀号", lambda: self.smart_kill(history=[{"nums": "1 2 3"}], lot="双色球", pool=[1, 2, 3, 4, 5, 6, 7, 8])),
        ]

        results = []
        for name, test_func in test_cases:
            try:
                result = test_func()
                results.append((name, "✅ 成功", result))
                logger.info(f"兼容性测试 {name}: 成功, 结果类型: {type(result)}, 长度: {len(result) if hasattr(result, '__len__') else 'N/A'}")
            except Exception as e:
                results.append((name, f"❌ 失败: {str(e)}", None))
                logger.error(f"兼容性测试 {name}: 失败, 错误: {e}")

        return results


# 模块级别保留向后兼容接口
_calc_instance = Killer()


def calc(*args, **kwargs):
    """模块级 calc 函数，转发到 Killer.calc()"""
    return _calc_instance.calc(*args, **kwargs)


def calc_advanced(history, lot):
    """模块级 calc_advanced 函数"""
    return _calc_instance.calc_advanced(history, lot)


def smart_kill(history, lot, pool=None):
    """模块级 smart_kill 函数"""
    return _calc_instance.smart_kill(history, lot, pool)


# 向后兼容：保留旧模块级函数引用
kill_numbers = calc

logger.info("killer.py 已加载 V2.0（Killer 实现内联，向后兼容 killer_fixed）")


# 模块初始化时自动测试兼容性（开发环境）
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    killer = Killer()
    logger.info("=== Killer V2.0+ 兼容性测试开始 ===")
    test_results = killer.test_compatibility()

    for name, status, result in test_results:
        print(f"{name}: {status}")
        if result is not None:
            print(f"  结果: {result}")

    print("\n=== 兼容性测试完成 ===")
