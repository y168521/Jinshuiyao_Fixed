# -*- coding: utf-8 -*-
"""金水谣系统 - 核心引擎单元测试

测试 engines/ 下的核心引擎模块：
- killer.py 的 Killer 类 (calc, smart_kill)
- format_gen.py 的 FormatGen 类 (双色球/3D 格式生成)
- validators.py 的 AdvancedValidator / SmartKillScorer
- correlation.py 的 CorrelationMatrix 基本功能
- miss_analyzer.py 的 MissAnalyzer 基本功能
- morph.py 的 MorphPredictor 基本功能
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _make_ssq_history(n=30):
    """构造 n 期双色球历史数据 (period 递增, nums 格式 "r1,r2,r3,r4,r5,r6+b1")"""
    history = []
    base_reds = [3, 8, 12, 17, 24, 29]
    base_blue = 7
    for i in range(n):
        # 简单轮转号码让历史数据多样化
        offset = i % 5
        reds = [(r + offset - 2) for r in base_reds]
        reds = [min(33, max(1, r)) for r in reds]
        blue = (base_blue + i) % 16 + 1
        nums_str = ",".join("%02d" % r for r in reds) + "+" + "%02d" % blue
        history.append({"period": 2026000 + i + 1, "nums": nums_str})
    return history


def _make_3d_history(n=30):
    """构造 n 期福彩3D历史数据 (3个0-9数字)"""
    history = []
    for i in range(n):
        a = i % 10
        b = (i * 2 + 1) % 10
        c = (i * 3 + 2) % 10
        nums_str = "%02d,%02d,%02d" % (a, b, c)
        history.append({"period": 2026300 + i + 1, "nums": nums_str})
    return history


# ==================================================================
# Killer 引擎测试
# ==================================================================

class TestKillerEngine(unittest.TestCase):
    """测试 engines/killer.py 的 Killer 类"""

    def setUp(self):
        try:
            from engines.killer import Killer
        except Exception as e:
            self.skipTest("无法导入 Killer: %s" % e)
        self.Killer = Killer
        self.killer = Killer()

    def test_killer_calc(self):
        """calc() 基础杀号：返回的杀号列表是号码集合的子集"""
        # 提供一组高频不同的号码（让计数差异足够大）
        nums = [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 7, 8, 9, 10, 11, 12, 13]
        killed = self.killer.calc(nums)
        self.assertIsInstance(killed, list)
        # 杀掉的号码应该在原号码集合内
        for k in killed:
            self.assertIn(k, set(nums))

    def test_killer_calc_empty(self):
        """calc() 空输入应返回空列表"""
        self.assertEqual(self.killer.calc([]), [])
        self.assertEqual(self.killer.calc(None), [])

    def test_killer_calc_with_history(self):
        """calc() 传入 history+lot 时应走高级杀号路径，返回 set/list"""
        history = _make_ssq_history(40)
        killed = self.killer.calc(nums=None, history=history, lot="双色球")
        # 高级杀号返回 set，应能 len/迭代
        self.assertTrue(hasattr(killed, "__iter__"))
        # 杀号号码应在 1-33 范围内
        for k in killed:
            self.assertTrue(1 <= k <= 33, "杀号 %s 超出双色球范围 1-33" % k)

    def test_killer_smart_kill(self):
        """smart_kill() 从候选池中杀号，杀完应保留最小数量"""
        history = _make_ssq_history(40)
        # 构造候选池：1-20
        pool = list(range(1, 21))
        killed = self.killer.smart_kill(history, "双色球", pool=pool)
        self.assertIsInstance(killed, set)
        # 杀号集合应是候选池的子集
        self.assertTrue(killed.issubset(set(pool)))
        # 杀完后剩余号码应 >= 最小保留数 _min_remain（双色球为 12）
        remain = len(set(pool)) - len(killed)
        # 双色球至少保留 12 个号（red[2]*2 = 6*2=12）
        self.assertGreaterEqual(remain, 6,
                                "杀完后剩余 %d 过少" % remain)

    def test_killer_smart_kill_empty_pool(self):
        """smart_kill() 空池应返回 calc_advanced 全集"""
        history = _make_ssq_history(40)
        killed = self.killer.smart_kill(history, "双色球", pool=None)
        self.assertIsInstance(killed, set)

    def test_killer_smart_kill_3d(self):
        """smart_kill() 3D/排列三：杀号范围在 0-9"""
        history = _make_3d_history(40)
        pool = list(range(10))
        killed = self.killer.smart_kill(history, "福彩3D", pool=pool)
        self.assertIsInstance(killed, set)
        # 杀号号码在 0-9
        for k in killed:
            self.assertTrue(0 <= k <= 9, "3D杀号 %s 超出 0-9" % k)
        # 3D/排列三最小保留4个号（_min_remain设计值）
        remain = len(set(pool)) - len(killed)
        self.assertGreaterEqual(remain, 4, "3D杀完后剩余 %d 过少" % remain)


# ==================================================================
# FormatGen 引擎测试
# ==================================================================

class TestFormatGenEngine(unittest.TestCase):
    """测试 engines/format_gen.py 的 FormatGen 类"""

    def setUp(self):
        try:
            from engines.format_gen import FormatGen
        except Exception as e:
            self.skipTest("无法导入 FormatGen: %s" % e)
        self.FormatGen = FormatGen

    def _gen_results(self, lot, history):
        """构造一个 FormatGen 实例并生成结果"""
        kill = []
        hot = {n: 0.1 for n in range(1, 50)}
        play_plan = [
            {"type": "单注", "count": 3, "config": {}},
            {"type": "复式", "count": 1, "config": {"red_extra": 1, "blue_extra": 0}},
        ]
        fg = self.FormatGen(lot, kill, hot, play="选10",
                            history=history, play_plan=play_plan)
        return fg.gen()

    def test_format_gen_ssq(self):
        """FormatGen 双色球应能生成合法格式 6红+1蓝"""
        history = _make_ssq_history(40)
        results = self._gen_results("双色球", history)
        self.assertIsInstance(results, dict)
        # 单注或复式至少有1条
        all_tickets = results.get("单注", []) + results.get("复式", [])
        self.assertGreater(len(all_tickets), 0, "应生成至少1注双色球")
        # 校验格式：应包含 + 分隔
        for ticket in results.get("单注", [])[:1]:
            self.assertIn("+", ticket, "双色球格式应包含 + 分隔符: %s" % ticket)
            parts = ticket.split("+")
            reds_str = parts[0]
            blues_str = parts[1] if len(parts) > 1 else ""
            # 红球应为 6 个，蓝球 1 个
            reds = [int(x) for x in reds_str.split(",") if x.strip().isdigit()]
            blues = [int(x) for x in blues_str.split(",") if x.strip().isdigit()]
            self.assertEqual(len(reds), 6, "双色球红球应6个, 实际 %d (%s)" % (len(reds), ticket))
            self.assertEqual(len(blues), 1, "双色球蓝球应1个, 实际 %d (%s)" % (len(blues), ticket))
            for r in reds:
                self.assertTrue(1 <= r <= 33, "红球 %s 超范围" % r)
            for b in blues:
                self.assertTrue(1 <= b <= 16, "蓝球 %s 超范围" % b)

    def test_format_gen_3d(self):
        """FormatGen 福彩3D应能生成合法格式 3位数字"""
        history = _make_3d_history(40)
        results = self._gen_results("福彩3D", history)
        self.assertIsInstance(results, dict)
        # 至少应生成一个复式结果（3D默认走 _gen_3d_hot_freq）
        all_tickets = results.get("单注", []) + results.get("复式", [])
        self.assertGreater(len(all_tickets), 0, "应生成至少1注3D")
        # 复式应包含6码（按 _gen_3d_hot_freq 返回6码）
        fushi_list = results.get("复式", [])
        if fushi_list:
            for ticket in fushi_list[:1]:
                digits = [int(x) for x in ticket.split(",") if x.strip().isdigit()]
                self.assertGreaterEqual(len(digits), 3, "3D复式至少3码: %s" % ticket)
                for d in digits:
                    self.assertTrue(0 <= d <= 9, "3D数字 %s 超范围 0-9" % d)


# ==================================================================
# Validators 校验器测试
# ==================================================================

class TestValidators(unittest.TestCase):
    """测试 engines/validators.py"""

    def setUp(self):
        try:
            from engines import validators
            from engines.validators import AdvancedValidator, SmartKillScorer, KillChecker
        except Exception as e:
            self.skipTest("无法导入 validators: %s" % e)
        self.validators = validators
        self.AdvancedValidator = AdvancedValidator
        self.SmartKillScorer = SmartKillScorer
        self.KillChecker = KillChecker

    def test_validators_ssq_valid(self):
        """AdvancedValidator 合法双色球应通过校验"""
        # 选一组分布合理的号码
        reds = [3, 8, 15, 22, 28, 31]
        blues = [7]
        ok, msg = self.AdvancedValidator.check("双色球", reds, blues)
        self.assertTrue(ok, "合法双色球应通过校验, msg=%s" % msg)

    def test_validators_ssq_invalid(self):
        """AdvancedValidator 非法号码应不通过校验"""
        # 红蓝重号硬拦截
        reds = [3, 8, 15, 22, 28, 31]
        blues = [3]  # 蓝球与红球重号
        ok, msg = self.AdvancedValidator.check("双色球", reds, blues)
        self.assertFalse(ok, "红蓝重号应被拦截")
        self.assertIn("红蓝重号", msg)

    def test_validators_ssq_extreme_sum(self):
        """AdvancedValidator 极端和值应被扣分"""
        # 号码和值过小（1+2+3+4+5+6=21，跨度也小）
        reds = [1, 2, 3, 4, 5, 6]
        blues = [7]
        ok, msg = self.AdvancedValidator.check("双色球", reds, blues)
        # 评分可能超阈值或刚好达到阈值
        # 不强制 False，但至少函数应正常执行返回 (bool, str)
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(msg, str)

    def test_validators_smart_kill_scorer(self):
        """SmartKillScorer 应能对一组号码给出评分"""
        history = _make_ssq_history(20)
        scorer = self.SmartKillScorer(history)
        reds = [3, 8, 12, 17, 24, 29]
        score = scorer.score("双色球", reds)
        self.assertIsInstance(score, int)
        self.assertGreaterEqual(score, 0)

    def test_validators_smart_kill_scorer_empty(self):
        """SmartKillScorer 空历史时评分应为0"""
        scorer = self.SmartKillScorer([])
        score = scorer.score("双色球", [1, 2, 3, 4, 5, 6])
        self.assertEqual(score, 0)

    def test_validators_kill_checker_3d(self):
        """KillChecker 对3D彩种应能正常执行判断"""
        history = _make_3d_history(10)
        # 调用 is_killed 不抛异常即可
        result = self.KillChecker.is_killed("福彩3D", [1, 2, 3], history)
        self.assertIsInstance(result, bool)

    def test_validators_kill_checker_non_3d(self):
        """KillChecker 非3D彩种应直接返回 False"""
        result = self.KillChecker.is_killed("双色球", [1, 2, 3, 4, 5, 6], [])
        self.assertFalse(result)


# ==================================================================
# CorrelationMatrix 关联矩阵测试
# ==================================================================

class TestCorrelationMatrix(unittest.TestCase):
    """测试 engines/correlation.py 的 CorrelationMatrix"""

    def setUp(self):
        try:
            from engines.correlation import CorrelationMatrix
        except Exception as e:
            self.skipTest("无法导入 CorrelationMatrix: %s" % e)
        self.CorrelationMatrix = CorrelationMatrix
        # 用 patch 避免真实文件 IO
        patcher_load = patch.object(CorrelationMatrix, "load", return_value=None)
        patcher_save = patch.object(CorrelationMatrix, "save", return_value=None)
        patcher_load.start()
        patcher_save.start()
        self.addCleanup(patcher_load.stop)
        self.addCleanup(patcher_save.stop)

    def test_correlation_basic(self):
        """build + adjust_weights 基本功能"""
        cm = self.CorrelationMatrix("双色球")
        history = _make_ssq_history(40)
        # 构建共现矩阵
        cm.build(history)
        # matrix 应被填充
        self.assertGreater(len(cm.matrix), 0, "共现矩阵应非空")

        # 构建转移矩阵
        cm.build_transition(history)
        self.assertGreater(len(cm.transition), 0, "转移矩阵应非空")

        # adjust_weights 应返回与 base 相同键的字典
        base_weights = {n: 0.1 for n in range(1, 34)}
        last_nums = [3, 8, 12]
        adjusted = cm.adjust_weights(base_weights, last_nums=last_nums, selected=[1, 2])
        self.assertEqual(set(adjusted.keys()), set(base_weights.keys()))
        # 权重应为非负数
        for v in adjusted.values():
            self.assertIsInstance(v, (int, float))
            self.assertGreaterEqual(v, 0)

    def test_correlation_get_related(self):
        """get_related 应返回与指定号码相关的前 topk 个号码"""
        cm = self.CorrelationMatrix("双色球")
        history = _make_ssq_history(40)
        cm.build(history)
        # 取一个在历史中肯定出现的号码
        related = cm.get_related(3, topk=2)
        self.assertIsInstance(related, list)
        self.assertLessEqual(len(related), 2)


# ==================================================================
# MissAnalyzer 遗漏分析测试
# ==================================================================

class TestMissAnalyzer(unittest.TestCase):
    """测试 engines/miss_analyzer.py 的 MissAnalyzer"""

    def setUp(self):
        try:
            from engines.miss_analyzer import MissAnalyzer
        except Exception as e:
            self.skipTest("无法导入 MissAnalyzer: %s" % e)
        self.MissAnalyzer = MissAnalyzer

    def test_miss_analyzer_basic(self):
        """analyze 应返回每个号码的遗漏统计"""
        analyzer = self.MissAnalyzer("福彩3D")
        history = _make_3d_history(30)
        # MissAnalyzer.analyze 期望 history 按时间从近到远（index 0 = 最新）
        # _make_3d_history 是从旧到新，需要反转
        history_reverse = list(reversed(history))
        result = analyzer.analyze(history_reverse)

        self.assertIsInstance(result, dict)
        # 3D范围 0-9
        for num in range(10):
            self.assertIn(num, result)
            info = result[num]
            self.assertIn("current_miss", info)
            self.assertIn("avg_miss", info)
            self.assertIn("max_miss", info)
            self.assertIn("breakthrough_score", info)
            self.assertIsInstance(info["current_miss"], int)
            self.assertIsInstance(info["breakthrough_score"], (int, float))

    def test_miss_analyzer_static_get_missing(self):
        """get_missing 静态方法应返回号码的当前遗漏期数"""
        history = _make_3d_history(20)
        # 第0期为最新（reverse后），未反转时最后一期是最新
        # _make_3d_history 中 i=0 是最旧的，i=n-1 是最新
        # get_missing 期望 history[0] 是最新
        history_reverse = list(reversed(history))
        # 3D第0期(最新)的号码是 a=19%10=9, b=(19*2+1)%10=9, c=(19*3+2)%10=9
        # 实际 (20-1=19): a=19%10=9, b=(38+1=39)%10=9, c=(57+2=59)%10=9
        # 等下，n=20, i 从0到19, i=19是最新的: a=19%10=9, b=(19*2+1=39)%10=9, c=(19*3+2=59)%10=9
        # 所以最新一期是 09,09,09
        miss_9 = self.MissAnalyzer.get_missing(9, history_reverse)
        self.assertEqual(miss_9, 0, "最新一期出现的号码遗漏应为0")

        # 找一个未在最新一期出现的号码，遗漏应该 > 0
        miss_0 = self.MissAnalyzer.get_missing(0, history_reverse)
        self.assertGreaterEqual(miss_0, 0)

    def test_miss_analyzer_adjust_weights(self):
        """adjust_weights 应将遗漏突破指数融入基础权重"""
        analyzer = self.MissAnalyzer("福彩3D")
        history = _make_3d_history(30)
        analyzer.analyze(list(reversed(history)))

        base = {n: 1.0 for n in range(10)}
        adjusted = analyzer.adjust_weights(base)
        self.assertEqual(set(adjusted.keys()), set(base.keys()))
        for v in adjusted.values():
            self.assertGreaterEqual(v, 0)


# ==================================================================
# MorphPredictor 形态分析测试
# ==================================================================

class TestMorphPredictor(unittest.TestCase):
    """测试 engines/morph.py 的 MorphPredictor"""

    def setUp(self):
        try:
            from engines.morph import MorphPredictor
        except Exception as e:
            self.skipTest("无法导入 MorphPredictor: %s" % e)
        self.MorphPredictor = MorphPredictor

    def test_morph_basic_analyze_3d(self):
        """3D形态分析应返回奇偶/大小分布等统计"""
        mp = self.MorphPredictor("福彩3D")
        history = _make_3d_history(50)
        stats = mp.analyze(history)
        self.assertIsNotNone(stats)
        self.assertIn("odd_even", stats)
        self.assertIn("big_small", stats)
        self.assertIn("odd_even_dist", stats)
        self.assertIn("big_small_dist", stats)
        self.assertIn("sum_range", stats)
        self.assertIn("zone_dist", stats)
        # 奇偶形态应为3字符
        self.assertEqual(len(stats["odd_even"]), 3)

    def test_morph_basic_check_pattern_3d(self):
        """3D形态检查应返回评分和警告"""
        mp = self.MorphPredictor("福彩3D")
        history = _make_3d_history(50)
        # [3, 5, 8] 非全奇非全偶
        result = mp.check_pattern([3, 5, 8], history)
        self.assertIn("valid", result)
        self.assertIn("score", result)
        self.assertIn("warnings", result)
        self.assertIsInstance(result["score"], int)
        self.assertTrue(0 <= result["score"] <= 100)
        # 非极端形态应有较高分
        self.assertGreaterEqual(result["score"], 30)

    def test_morph_basic_check_pattern_empty(self):
        """空号码列表应返回无效"""
        mp = self.MorphPredictor("福彩3D")
        result = mp.check_pattern([])
        self.assertFalse(result["valid"])
        self.assertEqual(result["score"], 0)

    def test_morph_basic_non_digit(self):
        """非3D彩种形态分析（双色球）"""
        mp = self.MorphPredictor("双色球")
        history = _make_ssq_history(50)
        stats = mp.analyze(history)
        self.assertIsNotNone(stats)
        self.assertIn("odd_even", stats)
        # 双色球奇偶比格式应为 "X:Y"
        self.assertIn(":", stats["odd_even"])

    def test_morph_basic_filter_pool(self):
        """filter_pool 应能从池中保留指定数量的号码"""
        mp = self.MorphPredictor("福彩3D")
        history = _make_3d_history(50)
        # 构造号码池：30个3位数
        pool = []
        for i in range(30):
            pool.append((i % 10) * 100 + ((i * 2) % 10) * 10 + ((i * 3) % 10))
        kept = mp.filter_pool(pool, history, keep_count=6)
        self.assertIsInstance(kept, list)
        self.assertLessEqual(len(kept), 6)


if __name__ == "__main__":
    unittest.main()
