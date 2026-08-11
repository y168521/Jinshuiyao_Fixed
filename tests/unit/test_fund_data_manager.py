# -*- coding: utf-8 -*-
"""基金数据安全模块测试

测试内容：
  - FundDataManager 加密/解密功能
  - 数据脱敏功能
  - 审计日志功能
  - 多用户隔离
  - 配置管理
"""
import os
import sys
import json
import tempfile
import shutil
from datetime import datetime

import unittest

# 确保项目根目录在 sys.path 中
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from domains.fund.fund_data_manager import FundDataManager, SENSITIVE_FIELDS

class TestFundDataManagerInit(unittest.TestCase):
    """测试FundDataManager初始化"""

    def setUp(self):
        self.test_user = "__test_fund_user__"
        self._tmp_root = tempfile.mkdtemp()
        self.manager = FundDataManager(self.test_user, root_dir=self._tmp_root)

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_init_creates_directories(self):
        """测试初始化时创建目录"""
        self.assertTrue(os.path.isdir(self.manager.fund_dir))

    def test_init_creates_files(self):
        """测试初始化时创建文件"""
        self.assertTrue(os.path.isfile(self.manager.public_file))
        self.assertTrue(os.path.isfile(self.manager.private_file))
        self.assertTrue(os.path.isfile(self.manager.config_file))

    def test_init_generates_key(self):
        """测试初始化时生成密钥"""
        self.assertIsNotNone(self.manager._key)
        self.assertTrue(os.path.isfile(self.manager.key_file))

    def test_init_empty_holdings(self):
        """测试初始化持仓为空（不再预置示例基金，由用户自行添加）"""
        holdings = self.manager.get_holdings()
        self.assertEqual(len(holdings), 0)

    def test_init_holdings_have_codes(self):
        """测试持仓基金都有代码"""
        holdings = self.manager.get_holdings()
        for h in holdings:
            self.assertIn("code", h)
            self.assertEqual(len(h["code"]), 6)


class TestFundDataManagerEncryption(unittest.TestCase):
    """测试加密/解密功能"""

    def setUp(self):
        self.test_user = "__test_fund_enc__"
        self._tmp_root = tempfile.mkdtemp()
        self.manager = FundDataManager(self.test_user, root_dir=self._tmp_root)

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_encrypt_decrypt(self):
        """测试加密解密可用"""
        data = {"amount": 228.58, "profit": 8.58}
        encrypted = self.manager._encrypt(data)
        self.assertNotEqual(encrypted, json.dumps(data))
        decrypted = self.manager._decrypt(encrypted)
        self.assertEqual(decrypted["amount"], 228.58)
        self.assertEqual(decrypted["profit"], 8.58)

    def test_update_sensitive_data_stored_encrypted(self):
        """测试敏感数据存为加密格式"""
        self.manager.add_holding({"code": "009051", "name": "测试基金"})
        self.manager.update_holding("009051", amount=228.58, profit=8.58)
        with open(self.manager.private_file, "r", encoding="utf-8") as f:
            content = f.read()
        # 加密后的内容应该包含 gAAAAAB（Fernet加密前缀）
        self.assertIn("gAAAAAB", content)
        # 不应该包含明文的敏感字段
        self.assertNotIn("228.58", content)

    def test_update_without_sensitive_not_in_private(self):
        """测试只更新公开字段时不新增加密内容"""
        self.manager.add_holding({"code": "009051", "name": "测试基金"})
        with open(self.manager.private_file, "r", encoding="utf-8") as f:
            before = f.read()
        self.manager.update_holding("009051", current_price=2.0)
        with open(self.manager.private_file, "r", encoding="utf-8") as f:
            after = f.read()
        # 更新公开字段不应改变加密文件（不新增敏感字段）
        self.assertEqual(after.strip(), before.strip())

    def test_sensitive_fields_protected(self):
        """测试敏感字段列表完整性"""
        expected = {"amount", "profit", "profit_rate", "units", "cost_price",
                     "buy_date", "total_invested", "executions"}
        self.assertEqual(SENSITIVE_FIELDS, expected)


class TestFundDataManagerSecurity(unittest.TestCase):
    """测试数据安全功能"""

    def setUp(self):
        self.test_user = "__test_fund_sec__"
        self._tmp_root = tempfile.mkdtemp()
        self.manager = FundDataManager(self.test_user, root_dir=self._tmp_root)

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_anonymize_holdings(self):
        """测试脱敏功能"""
        self.manager.add_holding({"code": "009051", "name": "测试基金"})
        self.manager.update_holding("009051", amount=228.58, profit=8.58)
        anonymized = self.manager.anonymize_holdings()
        for h in anonymized:
            if h["code"] == "009051":
                self.assertEqual(h["amount"], 0.0)
                self.assertEqual(h["profit"], 0.0)
                self.assertIsNotNone(h["name"])

    def test_anonymize_preserves_public(self):
        """测试脱敏保留公开字段"""
        self.manager.add_holding({"code": "009051", "name": "测试基金", "category": "混合型"})
        anonymized = self.manager.anonymize_holdings()
        for h in anonymized:
            self.assertIn("code", h)
            self.assertIn("name", h)
            self.assertIn("category", h)

    def test_create_share_package(self):
        """测试创建分享包"""
        package = self.manager.create_share_package()
        self.assertIn("fund_public", package)
        self.assertIn("config", package)
        self.assertIn("description", package)
        self.assertNotIn("fund_private", package)

    def test_audit_log_created(self):
        """测试审计日志"""
        self.manager.get_holdings()
        logs = self.manager.get_audit_logs()
        self.assertGreater(len(logs), 0)

    def test_audit_log_has_timestamp(self):
        """测试审计日志有时间戳"""
        self.manager.get_holdings()
        logs = self.manager.get_audit_logs()
        for log in logs:
            self.assertIn("timestamp", log)
            self.assertIn("action", log)


class TestFundDataManagerCRUD(unittest.TestCase):
    """测试增删改查功能"""

    def setUp(self):
        self.test_user = "__test_fund_crud__"
        self._tmp_root = tempfile.mkdtemp()
        self.manager = FundDataManager(self.test_user, root_dir=self._tmp_root)

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_get_holding(self):
        """测试获取单只基金"""
        self.manager.add_holding({"code": "009051", "name": "测试基金"})
        holding = self.manager.get_holding("009051")
        self.assertIsNotNone(holding)
        self.assertEqual(holding["name"], "测试基金")

    def test_get_holding_not_found(self):
        """测试获取不存在的基金"""
        holding = self.manager.get_holding("999999")
        self.assertIsNone(holding)

    def test_update_holding(self):
        """测试更新持仓"""
        self.manager.add_holding({"code": "009051", "name": "测试基金"})
        result = self.manager.update_holding("009051", current_price=2.5)
        self.assertTrue(result)
        holding = self.manager.get_holding("009051")
        self.assertEqual(holding["current_price"], 2.5)

    def test_add_and_remove_holding(self):
        """测试添加并删除持仓"""
        new_holding = {
            "code": "999999",
            "name": "测试基金",
            "category": "测试",
            "amount": 100.0,
            "profit": 10.0,
        }
        result = self.manager.add_holding(new_holding)
        self.assertTrue(result)
        # 验证已添加
        holding = self.manager.get_holding("999999")
        self.assertIsNotNone(holding)
        # 删除
        result = self.manager.remove_holding("999999")
        self.assertTrue(result)
        self.assertIsNone(self.manager.get_holding("999999"))

    def test_add_duplicate_holding(self):
        """测试添加重复基金"""
        self.manager.add_holding({"code": "009051", "name": "初始"})
        new_holding = {"code": "009051", "name": "重复"}
        result = self.manager.add_holding(new_holding)
        self.assertFalse(result)

    def test_remove_nonexistent(self):
        """测试删除不存在的基金"""
        result = self.manager.remove_holding("999999")
        self.assertFalse(result)

    def test_plans_empty_initial(self):
        """测试初始定投计划为空"""
        plans = self.manager.get_plans()
        self.assertEqual(plans, [])

    def test_add_and_get_plan(self):
        """测试添加并获取定投计划"""
        plan = {"amount": 100.0, "frequency": "daily"}
        result = self.manager.add_plan("009051", plan)
        self.assertTrue(result)
        plans = self.manager.get_plans()
        self.assertGreater(len(plans), 0)

    def test_add_transaction(self):
        """测试添加交易记录"""
        transaction = {"type": "buy", "amount": 100.0, "price": 1.0}
        result = self.manager.add_transaction("009051", transaction)
        self.assertTrue(result)
        transactions = self.manager.get_transactions("009051")
        self.assertGreater(len(transactions), 0)

    def test_transactions_sorted(self):
        """测试交易记录按时间排序"""
        self.manager.add_transaction("009051", {"type": "buy", "amount": 100.0})
        self.manager.add_transaction("009051", {"type": "sell", "amount": 50.0})
        transactions = self.manager.get_transactions()
        # 应该按时间倒序排列
        if len(transactions) >= 2:
            self.assertGreaterEqual(
                transactions[0]["timestamp"],
                transactions[1]["timestamp"]
            )


class TestFundDataManagerPortfolio(unittest.TestCase):
    """测试组合分析功能"""

    def setUp(self):
        self.test_user = "__test_fund_port__"
        self._tmp_root = tempfile.mkdtemp()
        self.manager = FundDataManager(self.test_user, root_dir=self._tmp_root)
        # 添加 3 只不同类别的持仓用于组合分析
        self.manager.add_holding({"code": "000001", "name": "基金A", "category": "混合型"})
        self.manager.add_holding({"code": "000002", "name": "基金B", "category": "债券型"})
        self.manager.add_holding({"code": "000003", "name": "基金C", "category": "指数型"})

    def tearDown(self):
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_portfolio_summary(self):
        """测试组合概览"""
        summary = self.manager.get_portfolio_summary()
        self.assertIn("total_amount", summary)
        self.assertIn("total_profit", summary)
        self.assertIn("fund_count", summary)
        self.assertEqual(summary["fund_count"], 3)

    def test_category_distribution(self):
        """测试分类分布"""
        dist = self.manager.get_category_distribution()
        self.assertGreaterEqual(len(dist), 3)
        for cat in dist:
            self.assertIn("amount", dist[cat])
            self.assertIn("count", dist[cat])

    def test_risk_distribution(self):
        """测试风险分布"""
        dist = self.manager.get_risk_distribution()
        self.assertGreater(len(dist), 0)

    def test_performance_ranking(self):
        """测试收益率排序"""
        ranking = self.manager.get_performance_ranking()
        self.assertEqual(len(ranking), 3)
        # 验证按收益率降序排列
        for i in range(len(ranking) - 1):
            rate_i = ranking[i].get("profit_rate", 0) or 0
            rate_j = ranking[i + 1].get("profit_rate", 0) or 0
            self.assertGreaterEqual(rate_i, rate_j)

    def test_get_config(self):
        """测试获取配置"""
        config = self.manager.get_config()
        self.assertIn("version", config)
        self.assertIn("target_profit", config)

    def test_update_config(self):
        """测试更新配置"""
        result = self.manager.update_config(target_profit=0.2)
        self.assertTrue(result)
        config = self.manager.get_config()
        self.assertEqual(config["target_profit"], 0.2)


class TestFundDataManagerMultiUser(unittest.TestCase):
    """测试多用户隔离"""

    def setUp(self):
        self._tmp_root_a = tempfile.mkdtemp()
        self._tmp_root_b = tempfile.mkdtemp()
        self.manager_a = FundDataManager("__test_user_a__", root_dir=self._tmp_root_a)
        self.manager_b = FundDataManager("__test_user_b__", root_dir=self._tmp_root_b)

    def tearDown(self):
        for r in [self._tmp_root_a, self._tmp_root_b]:
            shutil.rmtree(r, ignore_errors=True)

    def test_users_have_separate_dirs(self):
        """测试不同用户数据目录不同"""
        self.assertNotEqual(
            self.manager_a.fund_dir,
            self.manager_b.fund_dir
        )

    def test_users_have_separate_keys(self):
        """测试不同用户密钥不同"""
        key_a = self.manager_a._key
        key_b = self.manager_b._key
        self.assertNotEqual(key_a, key_b)

    def test_user_data_isolated(self):
        """测试用户数据隔离"""
        # 用户A添加并更新数据
        self.manager_a.add_holding({"code": "009051", "name": "测试基金"})
        self.manager_a.update_holding("009051", amount=999.99)
        # 用户B不应看到A的数据（B 中该基金不存在）
        holding_b = self.manager_b.get_holding("009051")
        self.assertIsNone(holding_b)
