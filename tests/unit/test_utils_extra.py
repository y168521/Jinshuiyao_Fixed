# -*- coding: utf-8 -*-
"""金水谣系统 - 工具模块单元测试

测试 utils/ 下的额外工具模块：
- utils/change_audit.py 的日志记录和备份功能
- utils/locks.py 的锁功能
- utils/ticket_validator.py 验证双色球/3D
"""
import os
import sys
import json
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ==================================================================
# change_audit 变更审计测试
# ==================================================================

class TestChangeAudit(unittest.TestCase):
    """测试 utils/change_audit.py"""

    @classmethod
    def setUpClass(cls):
        """使用临时目录重定向审计目录，避免污染真实审计日志"""
        try:
            import utils.change_audit as ca
        except Exception as e:
            raise unittest.SkipTest("无法导入 change_audit: %s" % e)
        cls.ca_module = ca

        # 保存原值
        cls._orig_audit_file = ca.AUDIT_FILE
        cls._orig_audit_dir = ca.AUDIT_DIR
        cls._orig_backup_dir = ca.BACKUP_DIR

        # 创建临时目录并重定向
        cls.tmp_root = tempfile.mkdtemp(prefix="jinshuiyao_audit_test_")
        cls.new_audit_dir = os.path.join(cls.tmp_root, "log")
        cls.new_audit_file = os.path.join(cls.new_audit_dir, "change_audit.logl")
        cls.new_backup_dir = os.path.join(cls.tmp_root, "backups")
        os.makedirs(cls.new_audit_dir, exist_ok=True)
        os.makedirs(cls.new_backup_dir, exist_ok=True)

        ca.AUDIT_DIR = cls.new_audit_dir
        ca.AUDIT_FILE = cls.new_audit_file
        ca.BACKUP_DIR = cls.new_backup_dir

    @classmethod
    def tearDownClass(cls):
        """恢复原值并清理临时目录"""
        try:
            cls.ca_module.AUDIT_DIR = cls._orig_audit_dir
            cls.ca_module.AUDIT_FILE = cls._orig_audit_file
            cls.ca_module.BACKUP_DIR = cls._orig_backup_dir
        except Exception:
            pass
        try:
            shutil.rmtree(cls.tmp_root, ignore_errors=True)
        except Exception:
            pass

    def test_change_audit_log(self):
        """log_fix/log_opt/log_new 应写入审计日志"""
        # 清空审计文件以便计数
        with open(self.new_audit_file, "w", encoding="utf-8") as f:
            f.write("")

        self.ca_module.log_fix("test_file.py", "修复测试Bug", "测试详情")
        self.ca_module.log_opt("test_file.py", "优化测试逻辑")
        self.ca_module.log_new("test_file.py", "新增测试功能")

        # 读取审计文件验证
        entries = []
        with open(self.new_audit_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        self.assertEqual(len(entries), 3, "应写入3条日志")
        # 第一条是 FIX
        self.assertEqual(entries[0]["type"], "FIX")
        self.assertEqual(entries[0]["file"], "test_file.py")
        self.assertEqual(entries[0]["summary"], "修复测试Bug")
        self.assertEqual(entries[0]["detail"], "测试详情")
        # 第二条是 OPT
        self.assertEqual(entries[1]["type"], "OPT")
        # 第三条是 NEW
        self.assertEqual(entries[2]["type"], "NEW")

    def test_change_audit_query(self):
        """query 应能按文件名和类型过滤"""
        with open(self.new_audit_file, "w", encoding="utf-8") as f:
            f.write("")
        self.ca_module.log_fix("query_test.py", "修复1")
        self.ca_module.log_fix("other.py", "修复2")
        self.ca_module.log_opt("query_test.py", "优化1")

        # 按文件查询
        results = self.ca_module.query(file_path="query_test.py")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["file"], "query_test.py")

        # 按类型查询
        fix_results = self.ca_module.query(entry_type="FIX")
        self.assertGreaterEqual(len(fix_results), 2)
        for r in fix_results:
            self.assertEqual(r["type"], "FIX")

    def test_change_audit_backup(self):
        """backup_before_modify 应能备份文件"""
        # 创建一个测试文件
        test_file = os.path.join(self.tmp_root, "to_backup.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("# original content\n")

        # 备份
        backup_path = self.ca_module.backup_before_modify(
            test_file, project_dir=self.tmp_root)
        self.assertIsNotNone(backup_path, "备份应返回非None路径")
        self.assertTrue(os.path.isfile(backup_path), "备份文件应存在")

        # 验证备份内容与原文件一致
        with open(backup_path, "r", encoding="utf-8") as f:
            backup_content = f.read()
        self.assertEqual(backup_content, "# original content\n")

        # list_backups 应能找到刚才的备份
        backups = self.ca_module.list_backups(test_file, project_dir=self.tmp_root)
        self.assertGreaterEqual(len(backups), 1, "应至少有1个备份")
        for b in backups:
            self.assertIn("path", b)
            self.assertIn("name", b)
            self.assertIn("time", b)
            self.assertIn("size", b)

    def test_change_audit_backup_nonexistent(self):
        """备份不存在的文件应返回 None"""
        result = self.ca_module.backup_before_modify(
            "nonexistent_file_xyz.py", project_dir=self.tmp_root)
        self.assertIsNone(result)

    def test_change_audit_get_recent(self):
        """get_recent 应返回最近N条记录"""
        with open(self.new_audit_file, "w", encoding="utf-8") as f:
            f.write("")
        for i in range(5):
            self.ca_module.log_fix("recent_test.py", "修复%d" % i)

        recent = self.ca_module.get_recent(limit=3)
        self.assertEqual(len(recent), 3, "应返回最近3条")
        # 应是按时间顺序的最后3条
        summaries = [r["summary"] for r in recent]
        self.assertEqual(summaries, ["修复2", "修复3", "修复4"])


# ==================================================================
# locks 锁功能测试
# ==================================================================

class TestLocks(unittest.TestCase):
    """测试 utils/locks.py"""

    def setUp(self):
        try:
            from utils import locks
        except Exception as e:
            self.skipTest("无法导入 locks: %s" % e)
        self.locks = locks

    def test_locks_json_lock(self):
        """json_lock 应是 threading.Lock 类型并可正常使用"""
        self.assertTrue(hasattr(self.locks, "json_lock"))
        # 应能 acquire/release
        self.assertTrue(self.locks.json_lock.acquire(blocking=False))
        # 再次 acquire 应失败（已持有）
        self.assertFalse(self.locks.json_lock.acquire(blocking=False))
        self.locks.json_lock.release()

    def test_locks_corr_lock(self):
        """corr_lock 应是 threading.Lock 类型"""
        self.assertTrue(hasattr(self.locks, "corr_lock"))
        self.assertIsInstance(self.locks.corr_lock, type(self.locks.json_lock))

    def test_locks_preds_lock(self):
        """preds_lock 应是 threading.Lock 类型"""
        self.assertTrue(hasattr(self.locks, "preds_lock"))
        self.assertIsInstance(self.locks.preds_lock, type(self.locks.json_lock))

    def test_locks_concurrent_safety(self):
        """锁应能保证并发安全（简单计数测试）"""
        counter = {"value": 0}
        # 使用 json_lock 保护计数器
        results = []

        def worker():
            for _ in range(100):
                with self.locks.json_lock:
                    counter["value"] += 1
                    results.append(counter["value"])

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 5个线程各加100次 = 500
        self.assertEqual(counter["value"], 500, "锁应保证并发计数正确")

    def test_locks_thread_safety(self):
        """不同锁应独立工作"""
        # json_lock 和 corr_lock 应是不同实例
        self.assertIsNot(self.locks.json_lock, self.locks.corr_lock)
        self.assertIsNot(self.locks.json_lock, self.locks.preds_lock)
        self.assertIsNot(self.locks.corr_lock, self.locks.preds_lock)


# ==================================================================
# ticket_validator 彩票号码验证测试
# ==================================================================

class TestTicketValidator(unittest.TestCase):
    """测试 utils/ticket_validator.py"""

    def setUp(self):
        try:
            from utils.ticket_validator import validate_ticket, is_valid_period
        except Exception as e:
            self.skipTest("无法导入 ticket_validator: %s" % e)
        self.validate_ticket = validate_ticket
        self.is_valid_period = is_valid_period

    def test_ticket_validator_ssq_valid(self):
        """合法双色球号码应通过校验"""
        # 6红 + 1蓝，号码在范围内
        valid, msg = self.validate_ticket("双色球", "01,05,12,18,25,33+07")
        self.assertTrue(valid, "合法双色球应通过: %s" % msg)

        # 边界号码
        valid, msg = self.validate_ticket("双色球", "01,02,03,04,05,06+01")
        self.assertTrue(valid, "最小号码应通过: %s" % msg)

        valid, msg = self.validate_ticket("双色球", "28,29,30,31,32,33+16")
        self.assertTrue(valid, "最大号码应通过: %s" % msg)

    def test_ticket_validator_ssq_invalid(self):
        """非法双色球号码应被拒绝"""
        # 红球超范围 (>33)
        valid, msg = self.validate_ticket("双色球", "01,05,12,18,25,34+07")
        self.assertFalse(valid, "红球34应被拒绝")
        self.assertIn("红球", msg)

        # 红球超范围 (<1)
        valid, msg = self.validate_ticket("双色球", "00,05,12,18,25,33+07")
        self.assertFalse(valid, "红球00应被拒绝")

        # 蓝球超范围 (>16)
        valid, msg = self.validate_ticket("双色球", "01,05,12,18,25,33+17")
        self.assertFalse(valid, "蓝球17应被拒绝")
        self.assertIn("蓝球", msg)

        # 蓝球超范围 (<1)
        valid, msg = self.validate_ticket("双色球", "01,05,12,18,25,33+00")
        self.assertFalse(valid, "蓝球00应被拒绝")

        # 空号码
        valid, msg = self.validate_ticket("双色球", "")
        self.assertFalse(valid)

    def test_ticket_validator_3d(self):
        """3D号码验证：合法与非法"""
        # 合法3D（3个0-9数字）
        valid, msg = self.validate_ticket("福彩3D", "01,05,09")
        self.assertTrue(valid, "合法3D应通过: %s" % msg)

        # 边界：0和9
        valid, msg = self.validate_ticket("福彩3D", "00,05,09")
        self.assertTrue(valid, "边界3D应通过: %s" % msg)

        # 非法：数字超范围 (>9)
        valid, msg = self.validate_ticket("福彩3D", "01,05,10")
        self.assertFalse(valid, "3D数字10应被拒绝")
        self.assertIn("超范围", msg)

        # 排列三同样规则
        valid, msg = self.validate_ticket("排列三", "03,07,08")
        self.assertTrue(valid, "合法排列三应通过: %s" % msg)

    def test_ticket_validator_dlt(self):
        """大乐透号码验证"""
        # 合法大乐透 5红 + 2蓝
        valid, msg = self.validate_ticket("大乐透", "01,05,15,25,35+01,12")
        self.assertTrue(valid, "合法大乐透应通过: %s" % msg)

        # 红球超范围 (>35)
        valid, msg = self.validate_ticket("大乐透", "01,05,15,25,36+01,12")
        self.assertFalse(valid, "前区36应被拒绝")
        self.assertIn("前区", msg)

        # 蓝球超范围 (>12)
        valid, msg = self.validate_ticket("大乐透", "01,05,15,25,35+01,13")
        self.assertFalse(valid, "后区13应被拒绝")
        self.assertIn("后区", msg)

    def test_ticket_validator_kl8(self):
        """快乐8号码验证"""
        # 合法快乐8
        valid, msg = self.validate_ticket("快乐8", "01,02,03,04,05,06,07,08,09,10")
        self.assertTrue(valid, "合法快乐8应通过: %s" % msg)

        # 号码超范围 (>80)
        valid, msg = self.validate_ticket("快乐8", "01,02,03,04,05,06,07,08,09,81")
        self.assertFalse(valid, "快乐8号码81应被拒绝")

    def test_ticket_validator_dantuo_format(self):
        """胆拖格式（含[]）应直接通过"""
        valid, msg = self.validate_ticket("双色球", "[胆:01,02]拖:05,06,07+03,04")
        self.assertTrue(valid, "胆拖格式应通过: %s" % msg)

    def test_ticket_validator_is_valid_period(self):
        """is_valid_period 期号验证"""
        # 合法期号
        self.assertTrue(self.is_valid_period("双色球", 2026066, latest=2026066))
        # 期号 <= 0
        self.assertFalse(self.is_valid_period("双色球", 0, latest=2026066))
        # 期号过未来
        self.assertFalse(self.is_valid_period("双色球", 2026100, latest=2026066))


if __name__ == "__main__":
    unittest.main()
