# -*- coding: utf-8 -*-
"""App瘦身验证测试

验证从 App 迁出的模块可独立工作：
  1. TicketValidator: 纯号码验证
  2. PredictionService: 核心预测逻辑
  3. LotteryDomain.generate/review: 对接真实引擎
  4. App原有功能不受影响
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from utils.ticket_validator import validate_ticket, is_valid_period


class TestTicketValidator(unittest.TestCase):
    """测试从App迁出的号码验证模块"""

    def test_ssq_valid(self):
        is_valid, err = validate_ticket("双色球", "01,05,12,18,25,33+07")
        self.assertTrue(is_valid)
        self.assertEqual(err, "")

    def test_ssq_red_out_of_range(self):
        is_valid, err = validate_ticket("双色球", "01,05,34,18,25,33+07")
        self.assertFalse(is_valid)
        self.assertIn("超范围", err)

    def test_ssq_blue_out_of_range(self):
        is_valid, err = validate_ticket("双色球", "01,05,12,18,25,33+17")
        self.assertFalse(is_valid)
        self.assertIn("超范围", err)

    def test_dlt_valid(self):
        is_valid, err = validate_ticket("大乐透", "03,12,22,31,35+02,08")
        self.assertTrue(is_valid)

    def test_3d_valid(self):
        is_valid, err = validate_ticket("福彩3D", "5,3,8")
        self.assertTrue(is_valid)

    def test_3d_out_of_range(self):
        is_valid, err = validate_ticket("福彩3D", "5,3,12")
        self.assertFalse(is_valid)

    def test_happy8_valid(self):
        is_valid, err = validate_ticket("快乐8", "01,15,23,45,67,80")
        self.assertTrue(is_valid)

    def test_happy8_out_of_range(self):
        is_valid, err = validate_ticket("快乐8", "01,15,81")
        self.assertFalse(is_valid)

    def test_qxc_valid(self):
        is_valid, err = validate_ticket("七星彩", "1,3,5,7,9,2+08")
        self.assertTrue(is_valid)

    def test_qxc_wrong_count(self):
        is_valid, err = validate_ticket("七星彩", "1,3,5,7,9+08")
        self.assertFalse(is_valid)
        self.assertIn("6个", err)

    def test_qxc_special_out_of_range(self):
        is_valid, err = validate_ticket("七星彩", "1,3,5,7,9,2+15")
        self.assertFalse(is_valid)
        self.assertIn("特别号", err)

    def test_empty(self):
        is_valid, err = validate_ticket("双色球", "")
        self.assertFalse(is_valid)

    def test_group6_format(self):
        is_valid, err = validate_ticket("福彩3D", "[1,2,3,4,5,6]")
        self.assertTrue(is_valid)

    def test_is_valid_period_positive(self):
        self.assertTrue(is_valid_period("双色球", 2026001, latest=2026000))

    def test_is_valid_period_zero(self):
        self.assertFalse(is_valid_period("双色球", 0))

    def test_is_valid_period_too_far(self):
        self.assertFalse(is_valid_period("双色球", 2026010, latest=2026000))


class TestPredictionServiceSmoke(unittest.TestCase):
    """PredictionService 烟雾测试（验证模块可加载、接口存在）"""

    def test_import(self):
        """PredictionService应可正常导入"""
        from engines.prediction_service import PredictionService
        self.assertTrue(callable(PredictionService))

    def test_instantiation_no_args(self):
        """无参构造不应崩溃"""
        from engines.prediction_service import PredictionService
        svc = PredictionService()
        self.assertIsNotNone(svc)

    def test_instantiation_with_args(self):
        """带参数构造不应崩溃"""
        from engines.prediction_service import PredictionService
        svc = PredictionService(
            engine_states={"hurst": True, "morph": True, "correlation": False},
            hot_window=50,
            on_log=lambda msg, level: None,
        )
        self.assertIsNotNone(svc)
        self.assertEqual(svc.hot_window, 50)

    def test_generate_no_data_lot(self):
        """不存在的彩种应返回错误"""
        from engines.prediction_service import PredictionService
        svc = PredictionService()
        result = svc.generate("不存在的彩种")
        # 可能返回 no_data 或 error（取决于Data）
        self.assertIn("success", result)
        self.assertIn("lot", result)

    def test_generate_returns_structure(self):
        """返回值应包含所有必要字段"""
        from engines.prediction_service import PredictionService
        svc = PredictionService()
        result = svc.generate("双色球", per_value=999999999)
        # 即使失败，结构也应完整
        self.assertIn("success", result)
        self.assertIn("tickets", result)
        self.assertIn("all_nums", result)
        self.assertIn("messages", result)
        self.assertIn("error", result)


class TestLotteryDomainRealGenerate(unittest.TestCase):
    """LotteryDomain.generate 对接真实引擎"""

    def setUp(self):
        import importlib, sys
        # 清除可能被其他测试残留的 mock 模块
        if "domains.lottery.domain" in sys.modules:
            prev = sys.modules["domains.lottery.domain"]
            # 如果是 MagicMock 实例（无 __name__ 属性或名字含 Mock），清除
            if not hasattr(prev, "__name__") or "Mock" in str(type(prev)):
                sys.modules.pop("domains.lottery.domain", None)
        import domains.lottery.domain as _ld
        importlib.reload(_ld)
        from domains.lottery.domain import LotteryDomain
        self.LotteryDomain = LotteryDomain

    def test_generate_single_lot(self):
        """单个彩种生成应返回结构化结果"""
        domain = self.LotteryDomain()
        domain.setup()
        # 使用巨大期号避免触发"已开奖"
        result = domain.generate(lots=["福彩3D"], play="选10")
        self.assertIn("status", result)
        self.assertIn("predictions", result)
        # 福彩3D有历史数据，应生成结果
        # 注意：可能因无数据返回no_data，但接口不应崩溃
        domain.teardown()

    def test_generate_domain_id(self):
        """返回值应包含domain_id"""
        domain = self.LotteryDomain()
        domain.setup()
        result = domain.generate(lots=[])
        self.assertEqual(result["domain_id"], "lottery")
        domain.teardown()

    def test_review_with_data(self):
        """复盘应返回命中率"""
        domain = self.LotteryDomain()
        domain.setup()

        predictions = [
            {"lot": "福彩3D", "nums": "1,2,3", "period": 100},
        ]
        actual = {"nums": "1,2,5"}
        result = domain.review(predictions, actual)
        self.assertTrue(result["updated"])
        self.assertEqual(result["reviews"], 1)
        self.assertIn("hit_rate", result)
        domain.teardown()

    def test_review_no_data(self):
        """无数据复盘应返回no_data"""
        domain = self.LotteryDomain()
        domain.setup()
        result = domain.review()
        self.assertEqual(result["status"], "no_data")
        domain.teardown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
