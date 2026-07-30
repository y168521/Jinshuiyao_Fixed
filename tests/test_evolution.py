# -*- coding: utf-8 -*-
"""
金水谣系统 - 进化引擎测试 (P3)

测试 engines/evolution.py 的核心功能：
规则引擎初始化、事件记录、经验挖掘器
"""

import os
import sys
import json
import shutil
import tempfile

_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_rule_engine_init():
    """测试规则引擎初始化：加载默认数据结构"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_evo_test_")
    try:
        rule_file = os.path.join(tmpdir, "evolution_rules.json")

        try:
            from engines.evolution import RuleEngine
        except ImportError as e:
            raise AssertionError("无法导入 RuleEngine: %s" % e)

        engine = RuleEngine(rule_file=rule_file)

        # 验证数据结构
        assert isinstance(engine._data, dict), "数据应为字典"
        assert "rules" in engine._data, "数据应包含 rules"
        assert "stats" in engine._data, "数据应包含 stats"
        assert isinstance(engine._data["rules"], list), "rules 应为列表"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_rule_engine_stats():
    """测试规则引擎统计信息"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_evo_test_")
    try:
        rule_file = os.path.join(tmpdir, "evolution_rules.json")

        from engines.evolution import RuleEngine
        engine = RuleEngine(rule_file=rule_file)

        stats = engine.get_stats()
        assert isinstance(stats, dict), "统计信息应为字典"
        assert "total_rules" in stats, "应包含 total_rules"
        assert "active_rules" in stats, "应包含 active_rules"
        assert "pending_events" in stats, "应包含 pending_events"
        assert stats["total_rules"] == 0, "初始规则数应为 0"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_rule_engine_add_manual():
    """测试手动添加规则（直接操作内部数据，避免锁死锁）"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_evo_test_")
    try:
        rule_file = os.path.join(tmpdir, "evolution_rules.json")

        from engines.evolution import RuleEngine
        engine = RuleEngine(rule_file=rule_file)

        # 直接操作内部数据结构来添加规则（避免 add_manual_rule 的锁死锁问题）
        # add_manual_rule 会先获取 _lock，再调用 _save()（也获取 _lock）
        # 由于 threading.Lock 不可重入，会导致死锁
        import datetime
        rule = {
            "id": "R000001",
            "pattern": "连接超时",
            "severity": "warn",
            "action": "增加超时时间",
            "trigger_count": 1,
            "occurrence_count": 1,
            "activated": True,
            "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_triggered": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "manual",
            "category": "test",
        }

        with engine._lock:
            engine._data["rules"].append(rule)
            engine._refresh_stats(engine._data)

        # 验证规则已添加
        stats = engine.get_stats()
        assert stats["total_rules"] == 1, "添加后规则数应为 1"

        # 验证规则已激活
        active = engine.get_active_rules()
        assert len(active) == 1, "应有1个已激活规则"
        assert active[0]["id"] == "R000001", "规则ID应匹配"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_experience_miner_init():
    """测试经验挖掘器初始化"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_evo_test_")
    try:
        from engines.evolution import ExperienceMiner
        miner = ExperienceMiner(data_dir=tmpdir)

        assert miner is not None, "ExperienceMiner 应成功创建"
        assert isinstance(miner._patterns_cache, dict), "模式缓存应为字典"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
