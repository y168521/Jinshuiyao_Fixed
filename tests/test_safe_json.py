# -*- coding: utf-8 -*-
"""
金水谣系统 - 数据安全模块测试 (P0)

测试 utils/safe_json.py 的核心功能：
原子写入、自动备份、CRC校验、损坏恢复、文件健康检查
"""

import os
import sys
import json
import shutil
import tempfile

# 确保项目根目录在 sys.path 中
_test_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_test_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from utils.safe_json import (
    safe_write_json,
    safe_load_json,
    auto_backup,
    compute_checksum,
    verify_checksum,
    check_file_health,
)


# =========================================================================
# 测试用例
# =========================================================================

def test_atomic_write():
    """测试原子写入：写入数据后验证文件内容正确"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_data.json")
        data = {"version": 1, "name": "金水谣", "items": [1, 2, 3]}

        # 执行原子写入
        ok = safe_write_json(filepath, data)
        assert ok is True, "safe_write_json 应返回 True"

        # 验证文件存在且内容正确
        assert os.path.isfile(filepath), "文件应该存在"
        with open(filepath, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["version"] == 1, "version 应为 1"
        assert loaded["name"] == "金水谣", "name 应为 '金水谣'"
        assert loaded["items"] == [1, 2, 3], "items 应为 [1, 2, 3]"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_backup_created():
    """测试备份机制：写入后检查备份文件是否自动创建"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_data.json")
        data = {"version": 1}

        # 第一次写入（无原文件，不应创建备份）
        ok = safe_write_json(filepath, data, backup=True)
        assert ok is True

        # 第二次写入（有原文件，应创建备份）
        data["version"] = 2
        ok = safe_write_json(filepath, data, backup=True)
        assert ok is True

        # 检查备份文件是否存在
        backup_found = False
        for entry in os.listdir(tmpdir):
            if entry.startswith("test_data.json.bak."):
                backup_found = True
                break
        assert backup_found, "应创建备份文件 test_data.json.bak.0"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_corrupted_recovery():
    """测试损坏恢复：模拟文件损坏后验证自动从备份恢复"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_data.json")
        data = {"version": 5, "important": True}

        # 第一次写入（无备份）
        ok = safe_write_json(filepath, data)
        assert ok is True

        # 第二次写入（会自动创建备份）
        data["version"] = 6
        ok = safe_write_json(filepath, data, backup=True)
        assert ok is True

        # 确认备份已创建
        backup_found = any(
            e.startswith("test_data.json.bak.")
            for e in os.listdir(tmpdir)
        )
        assert backup_found, "应先创建备份文件"

        # 模拟损坏：写入垃圾数据
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("{损坏的JSON内容!!!")

        # 尝试加载（应自动从备份恢复）
        loaded = safe_load_json(filepath, default={"error": True})

        assert loaded is not None, "加载不应返回 None"
        assert loaded.get("error") is not True, "不应返回默认值"
        # 恢复的数据可能是 version=5 或 version=6（取决于备份内容）
        assert loaded.get("version") in (5, 6), "恢复的数据 version 应为 5 或 6"
        assert loaded.get("important") is True, "恢复的数据 important 应为 True"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_checksum_embed():
    """测试校验和嵌入：验证写入的数据自动嵌入 SHA256 校验和"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_data.json")
        data = {"name": "校验测试", "value": 42}

        # 写入时嵌入校验和
        ok = safe_write_json(filepath, data, embed_checksum=True)
        assert ok is True

        # 加载并检查校验和字段
        with open(filepath, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert "_metadata" in loaded, "应包含 _metadata 字段"
        assert "checksum" in loaded["_metadata"], "应包含 checksum 字段"
        assert len(loaded["_metadata"]["checksum"]) == 64, "SHA256 校验和应为 64 位十六进制"

        # 验证校验和正确
        assert verify_checksum(loaded) is True, "校验和应验证通过"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_checksum_verify():
    """测试校验和验证：修改数据后校验和应该失败"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_data.json")
        data = {"name": "完整性测试", "value": 100}

        # 正常写入
        ok = safe_write_json(filepath, data, embed_checksum=True)
        assert ok is True

        # 篡改文件内容
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        # 将 value 改为 200（直接修改文件文本）
        tampered = content.replace('"value": 100', '"value": 200')
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(tampered)

        # 重新加载并验证
        with open(filepath, "r", encoding="utf-8") as f:
            tampered_data = json.load(f)

        assert verify_checksum(tampered_data) is False, "篡改后的数据校验和应失败"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_file_health_check():
    """测试文件健康检查：检查健康状态报告的结构和内容"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_data.json")
        data = {"status": "ok", "count": 10}

        # 正常写入
        ok = safe_write_json(filepath, data)
        assert ok is True

        # 检查健康状态
        health = check_file_health(filepath)

        # 验证报告结构
        assert "status" in health, "健康报告应包含 status"
        assert "file_size" in health, "健康报告应包含 file_size"
        assert "backup_count" in health, "健康报告应包含 backup_count"
        assert "last_modified" in health, "健康报告应包含 last_modified"
        assert "checksum_valid" in health, "健康报告应包含 checksum_valid"
        assert "details" in health, "健康报告应包含 details"

        # 正常文件应为 healthy
        assert health["status"] == "healthy", "正常文件状态应为 healthy"
        assert health["file_size"] > 0, "文件大小应大于 0"

        # 测试不存在的文件
        missing_health = check_file_health(os.path.join(tmpdir, "nonexistent.json"))
        assert missing_health["status"] == "missing", "不存在的文件状态应为 missing"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_write_non_dict_skip_checksum():
    """测试非字典类型写入时跳过校验和嵌入"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_list.json")
        data = [1, 2, 3, 4, 5]

        # 写入列表类型数据
        ok = safe_write_json(filepath, data, embed_checksum=True)
        assert ok is True

        # 加载并验证
        with open(filepath, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == [1, 2, 3, 4, 5], "列表数据应正确写入"
        assert "_metadata" not in loaded, "列表类型不应嵌入 _metadata"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_default_value_on_missing():
    """测试文件不存在时返回默认值"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "nonexistent.json")
        default = {"fallback": True}

        loaded = safe_load_json(filepath, default=default)
        assert loaded == default, "文件不存在时应返回默认值"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_stale_checksum_removed_on_write():
    """回归: embed_checksum=False 写覆盖旧 checksum 残留（历史事故修复）

    事故背景: 契约改为"业务数据禁注入 _metadata"（embed_checksum 默认 False）后，
    旧版本写入的 _metadata.checksum 残留文件中；新内容写入不更新 checksum，
    导致 safe_load_json 校验永远失败 → 误判"文件损坏" → 从备份恢复旧数据
    （曾吞掉 brain_state.json 的置信度记录与 mirofish_db 的卡片更新）。
    """
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_data.json")

        # 旧契约: 带 checksum 写入
        ok = safe_write_json(filepath, {"version": 1, "conf": 0}, embed_checksum=True)
        assert ok is True

        # 新契约: 默认 embed_checksum=False 覆盖写入（内容更新）
        ok = safe_write_json(filepath, {"version": 2, "conf": 1})
        assert ok is True

        with open(filepath, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert "_metadata" not in loaded, "残留 checksum 应被移除（含空 _metadata）"
        assert loaded["version"] == 2 and loaded["conf"] == 1, "新内容应完整保留"

        # 关键: 之后 safe_load_json 不再误判损坏、不再静默恢复备份
        assert verify_checksum(loaded) is True, "无 checksum 应视为通过"
        assert check_file_health(filepath)["status"] == "healthy", "文件应保持健康"
        reloaded = safe_load_json(filepath, default={})
        assert reloaded == loaded, "safe_load 应返回写入的最新内容而非备份"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_stale_checksum_no_restore_from_backup():
    """回归: 带残留旧 checksum 的文件用默认契约重写后，不再触发备份恢复"""
    tmpdir = tempfile.mkdtemp(prefix="jinshuiyao_test_")
    try:
        filepath = os.path.join(tmpdir, "test_data.json")

        # 先写旧版（带 checksum），再造一个备份，确保有可恢复的旧数据
        safe_write_json(filepath, {"version": 1}, embed_checksum=True)
        safe_write_json(filepath, {"version": 2}, embed_checksum=True, backup=True)

        # 模拟事故现场: 文件内容已被新契约覆盖但 checksum 残留旧值
        raw = json.load(open(filepath, "r", encoding="utf-8"))
        raw["conf"] = 9  # 新业务字段
        json.dump(raw, open(filepath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        # 旧行为: 校验失败 → 恢复备份（version=1, conf 丢失）
        # 新行为: 重写时移除残留 checksum → 干净加载
        ok = safe_write_json(filepath, {"version": 3, "conf": 9})
        assert ok is True

        loaded = safe_load_json(filepath, default={})
        assert loaded == {"version": 3, "conf": 9}, "应加载最新内容，不应回滚到备份"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
