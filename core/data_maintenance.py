# -*- coding: utf-8 -*-
"""
金水谣系统 - 数据库自动维护模块

提供数据文件的自动清理、压缩优化、索引重建和统计功能，
确保金水谣数据目录始终保持健康、精简的状态。

功能清单:
    - cleanup_expired_cache:   清理过期的缓存文件
    - cleanup_old_predictions: 清理过期的预测记录
    - cleanup_temp_files:      清理临时文件
    - compress_data_files:     压缩优化数据文件
    - rebuild_indices:         重建/修复核心索引文件
    - vacuum_all:              一键执行所有维护操作
    - get_data_stats:          获取数据目录统计信息

Usage:
    from core.data_maintenance import DataMaintainer

    maintainer = DataMaintainer()
    report = maintainer.vacuum_all()
    print(report)
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import tempfile
from utils.safe_json import safe_write_json

logger = logging.getLogger("jinshuiyao.data_maintenance")


class DataMaintainer:
    """金水谣数据目录自动维护器

    负责缓存清理、过期数据淘汰、临时文件清理、数据压缩和索引重建等
    维护操作，保持数据目录的健康和高效。

    Args:
        data_dir: 金水谣数据目录路径，默认为项目根目录下的 "金水谣数据"
    """

    def __init__(self, data_dir: Optional[str] = None):
        """初始化数据维护器

        Args:
            data_dir: 金水谣数据目录路径，为 None 时自动推算项目根目录下的
                      "金水谣数据" 目录
        """
        if data_dir is None:
            # 本文件位于 core/data_maintenance.py，项目根目录在上一级
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.data_dir = os.path.join(project_root, "金水谣数据")
        else:
            self.data_dir = os.path.abspath(data_dir)
        self._stats_snapshot_file = os.path.join(self.data_dir, ".maintenance_stats.json")

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    def _get_file_age_days(self, filepath: str) -> float:
        """获取文件的年龄（天数），基于最后修改时间

        Args:
            filepath: 文件路径

        Returns:
            float: 文件年龄（天数），文件不存在返回 -1
        """
        try:
            mtime = os.path.getmtime(filepath)
            age_seconds = time.time() - mtime
            return age_seconds / (24 * 3600)
        except OSError:
            return -1

    def _get_file_size_kb(self, filepath: str) -> float:
        """安全获取文件大小（KB）

        Args:
            filepath: 文件路径

        Returns:
            float: 文件大小（KB），文件不存在或出错返回 0
        """
        try:
            return os.path.getsize(filepath) / 1024.0
        except OSError:
            return 0.0

    def _scan_json_files(self, directory: str) -> List[str]:
        """扫描目录下所有 JSON 文件

        Args:
            directory: 要扫描的目录路径

        Returns:
            list[str]: JSON 文件的绝对路径列表
        """
        json_files = []
        if not os.path.isdir(directory):
            logger.debug("目录不存在，跳过扫描: %s", directory)
            return json_files
        for entry in os.listdir(directory):
            full_path = os.path.join(directory, entry)
            if os.path.isfile(full_path) and entry.endswith(".json"):
                json_files.append(full_path)
        return json_files

    def _load_json_safe(self, filepath: str, default: Any = None) -> Any:
        """安全加载 JSON 文件，出错返回默认值

        Args:
            filepath: 文件路径
            default: 加载失败时的默认返回值

        Returns:
            加载成功返回 Python 对象，失败返回 default
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning("加载 JSON 失败: %s (%s)", filepath, e)
            return default
        except Exception as e:
            logger.error("加载 JSON 异常: %s (%s)", filepath, e, exc_info=True)
            return default

    def _save_json_safe(self, filepath: str, data: Any) -> bool:
        """安全保存 JSON 文件

        Args:
            filepath: 文件路径
            data: 要写入的 Python 对象

        Returns:
            bool: 写入是否成功
        """
        try:
            return safe_write_json(filepath, data)
        except (OSError, TypeError) as e:
            logger.error("写入 JSON 失败: %s (%s)", filepath, e)
            return False

    def _try_restore_from_backup(self, filepath: str) -> bool:
        """尝试从备份文件恢复损坏的文件

        查找 {filename}.bak.0, .bak.1, .bak.2 等备份文件，
        取最新可用的备份恢复到主文件。

        Args:
            filepath: 要恢复的主文件路径

        Returns:
            bool: 是否成功恢复
        """
        parent = os.path.dirname(filepath) or "."
        basename = os.path.basename(filepath)

        # 收集备份文件
        backup_files = []
        try:
            entries = os.listdir(parent)
        except OSError:
            return False

        for entry in entries:
            if entry.startswith(basename + ".bak."):
                full_path = os.path.join(parent, entry)
                try:
                    seq = int(entry[len(basename) + 5:])
                    backup_files.append((seq, full_path))
                except ValueError:
                    continue

        # 按序号从大到小排序（最新备份在前）
        backup_files.sort(key=lambda x: x[0], reverse=True)

        for seq, bp in backup_files:
            try:
                with open(bp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 验证 JSON 至少是有效的
                if isinstance(data, (dict, list)):
                    safe_write_json(filepath, data, backup=False)
                    logger.info("从备份恢复成功: %s -> %s", bp, filepath)
                    return True
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("备份文件也损坏: %s (%s)", bp, e)
                continue

        return False

    # ------------------------------------------------------------------
    # 公开维护方法
    # ------------------------------------------------------------------

    def cleanup_expired_cache(self, max_age_days: int = 7) -> dict:
        """清理过期的缓存文件

        扫描 stock/cache/ 和 fund/cache/ 目录下的 JSON 文件，
        删除修改时间超过 max_age_days 天的文件。

        Args:
            max_age_days: 缓存文件最大保留天数，默认 7 天

        Returns:
            dict: 清理结果，包含:
                - cleaned (int):   清理的文件数量
                - freed_kb (float): 释放的磁盘空间（KB）
                - files (list):    被清理的文件路径列表

        Examples:
            >>> maintainer = DataMaintainer()
            >>> result = maintainer.cleanup_expired_cache(max_age_days=7)
            >>> print(f"清理了 {result['cleaned']} 个文件，释放 {result['freed_kb']:.1f} KB")
        """
        result = {"cleaned": 0, "freed_kb": 0.0, "files": []}

        # 要扫描的缓存子目录
        cache_dirs = [
            os.path.join(self.data_dir, "stock", "cache"),
            os.path.join(self.data_dir, "fund", "cache"),
        ]

        for cache_dir in cache_dirs:
            if not os.path.isdir(cache_dir):
                logger.debug("缓存目录不存在，跳过: %s", cache_dir)
                continue

            json_files = self._scan_json_files(cache_dir)
            for filepath in json_files:
                age = self._get_file_age_days(filepath)
                if age < 0:
                    logger.warning("无法获取文件修改时间: %s", filepath)
                    continue
                if age > max_age_days:
                    file_size_kb = self._get_file_size_kb(filepath)
                    try:
                        os.remove(filepath)
                        logger.info("清理过期缓存: %s (年龄: %.1f 天, 大小: %.1f KB)",
                                    filepath, age, file_size_kb)
                        result["cleaned"] += 1
                        result["freed_kb"] += file_size_kb
                        result["files"].append(filepath)
                    except OSError as e:
                        logger.error("删除缓存文件失败: %s (%s)", filepath, e)

        result["freed_kb"] = round(result["freed_kb"], 2)
        logger.info("缓存清理完成: 清理 %d 个文件，释放 %.2f KB",
                    result["cleaned"], result["freed_kb"])
        return result

    def cleanup_old_predictions(self, keep_days: int = 90) -> dict:
        """清理过期的预测记录

        读取 predictions.json 文件，删除时间戳超过 keep_days 天的记录，
        保留较新的记录并保存回文件。

        Args:
            keep_days: 预测记录最大保留天数，默认 90 天

        Returns:
            dict: 清理结果，包含:
                - before (int):  清理前的记录总数
                - after (int):  清理后的记录总数
                - removed (int): 删除的记录数

        Examples:
            >>> maintainer = DataMaintainer()
            >>> result = maintainer.cleanup_old_predictions(keep_days=90)
            >>> print(f"删除了 {result['removed']} 条过期预测记录")
        """
        result = {"before": 0, "after": 0, "removed": 0}
        predictions_path = os.path.join(self.data_dir, "predictions.json")

        if not os.path.isfile(predictions_path):
            logger.info("predictions.json 不存在，无需清理")
            return result

        data = self._load_json_safe(predictions_path, default=None)
        if data is None:
            logger.warning("predictions.json 加载失败，跳过清理")
            return result

        # 兼容多种数据格式
        # 格式1: 顶层是列表
        if isinstance(data, list):
            result["before"] = len(data)
            cutoff_time = datetime.now() - timedelta(days=keep_days)
            cutoff_timestamp = cutoff_time.timestamp()

            filtered = []
            for item in data:
                # 尝试从记录中提取时间戳
                ts = None
                if isinstance(item, dict):
                    # 常见时间戳字段名
                    for key in ("timestamp", "time", "date", "created_at",
                                "prediction_time", "update_time"):
                        if key in item:
                            val = item[key]
                            try:
                                if isinstance(val, (int, float)):
                                    ts = float(val)
                                elif isinstance(val, str):
                                    # 尝试解析 ISO 格式时间字符串
                                    try:
                                        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                                        ts = dt.timestamp()
                                    except (ValueError, OverflowError):
                                        pass
                            except (ValueError, TypeError):
                                pass
                            if ts is not None:
                                break

                # 如果没有时间戳字段，保留该记录（保守策略）
                if ts is None:
                    filtered.append(item)
                elif ts >= cutoff_timestamp:
                    filtered.append(item)
                else:
                    logger.debug("移除过期预测记录 (ts=%s)", item)

            result["after"] = len(filtered)
            result["removed"] = result["before"] - result["after"]

            if result["removed"] > 0:
                if self._save_json_safe(predictions_path, filtered):
                    logger.info("预测记录清理完成: 删除 %d 条，保留 %d 条",
                                result["removed"], result["after"])
                else:
                    logger.error("保存清理后的 predictions.json 失败")
                    result["after"] = result["before"]
                    result["removed"] = 0
            else:
                logger.info("无需清理预测记录 (共 %d 条)", result["before"])

        # 格式2: 顶层是字典，记录在某一个 key 下
        elif isinstance(data, dict):
            # 查找包含列表的键
            list_keys = [k for k, v in data.items() if isinstance(v, list) and k != "_metadata"]
            if not list_keys:
                logger.info("predictions.json 中无列表数据可清理")
                result["before"] = 0
                return result

            total_removed = 0
            total_before = 0
            cutoff_time = datetime.now() - timedelta(days=keep_days)
            cutoff_timestamp = cutoff_time.timestamp()

            for key in list_keys:
                records = data[key]
                total_before += len(records)
                filtered = []
                for item in records:
                    ts = None
                    if isinstance(item, dict):
                        for field in ("timestamp", "time", "date", "created_at",
                                      "prediction_time", "update_time"):
                            if field in item:
                                val = item[field]
                                try:
                                    if isinstance(val, (int, float)):
                                        ts = float(val)
                                    elif isinstance(val, str):
                                        try:
                                            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                                            ts = dt.timestamp()
                                        except (ValueError, OverflowError):
                                            pass
                                except (ValueError, TypeError):
                                    pass
                                if ts is not None:
                                    break
                    if ts is None or ts >= cutoff_timestamp:
                        filtered.append(item)

                total_removed += len(records) - len(filtered)
                data[key] = filtered

            result["before"] = total_before
            result["after"] = total_before - total_removed
            result["removed"] = total_removed

            if total_removed > 0:
                if self._save_json_safe(predictions_path, data):
                    logger.info("预测记录清理完成 (dict格式): 删除 %d 条，保留 %d 条",
                                total_removed, result["after"])
                else:
                    logger.error("保存清理后的 predictions.json 失败")
                    result["after"] = result["before"]
                    result["removed"] = 0
            else:
                logger.info("无需清理预测记录 (共 %d 条)", total_before)
        else:
            logger.warning("predictions.json 格式不支持，跳过清理")

        return result

    def cleanup_temp_files(self) -> dict:
        """清理临时文件

        清理金水谣数据目录下所有匹配以下模式的文件:
        - *.tmp
        - *.bak.N (N 为数字的备份文件，但排除 safe_json 的 .bak.0/1/2 滚动备份)
        - test_*_tmp_* (测试临时文件)

        Returns:
            dict: 清理结果，包含:
                - cleaned (int):    清理的文件数量
                - freed_kb (float): 释放的磁盘空间（KB）

        Examples:
            >>> maintainer = DataMaintainer()
            >>> result = maintainer.cleanup_temp_files()
            >>> print(f"清理了 {result['cleaned']} 个临时文件")
        """
        result = {"cleaned": 0, "freed_kb": 0.0}

        if not os.path.isdir(self.data_dir):
            logger.info("数据目录不存在，无需清理临时文件: %s", self.data_dir)
            return result

        # 遍历数据目录
        for root, dirs, files in os.walk(self.data_dir):
            # 跳过 backups 目录
            if os.path.basename(root) == "backups":
                continue
            # 跳过 archive 目录
            if os.path.basename(root) == "archive":
                continue

            for filename in files:
                filepath = os.path.join(root, filename)

                # 判断是否为临时文件
                is_temp = False

                # 模式1: *.tmp
                if filename.endswith(".tmp"):
                    is_temp = True

                # 模式2: test_*_tmp_*
                elif filename.startswith("test_") and "_tmp_" in filename:
                    is_temp = True

                # 模式3: *.safe_json_* (safe_json 模块写入过程中的残留临时文件)
                elif filename.startswith(".safe_json_"):
                    is_temp = True

                if not is_temp:
                    continue

                file_size_kb = self._get_file_size_kb(filepath)
                try:
                    os.remove(filepath)
                    logger.info("清理临时文件: %s (%.1f KB)", filepath, file_size_kb)
                    result["cleaned"] += 1
                    result["freed_kb"] += file_size_kb
                except OSError as e:
                    logger.error("删除临时文件失败: %s (%s)", filepath, e)

        result["freed_kb"] = round(result["freed_kb"], 2)
        logger.info("临时文件清理完成: 清理 %d 个文件，释放 %.2f KB",
                    result["cleaned"], result["freed_kb"])
        return result

    def compress_data_files(self, max_size_kb: int = 500) -> dict:
        """对超过指定大小的数据文件进行压缩优化

        通过裁剪旧记录来减小文件体积:
        - predictions.json: 保留最新 1000 条记录
        - health_log.jsonl: 保留最新 5000 条记录

        仅对超过 max_size_kb 的文件执行压缩。

        Args:
            max_size_kb: 触发压缩的文件大小阈值（KB），默认 500

        Returns:
            dict: 压缩结果，包含:
                - compressed (list):   被压缩的文件路径列表
                - saved_kb (float):    节省的磁盘空间（KB）

        Examples:
            >>> maintainer = DataMaintainer()
            >>> result = maintainer.compress_data_files(max_size_kb=500)
            >>> print(f"压缩了 {len(result['compressed'])} 个文件")
        """
        result = {"compressed": [], "saved_kb": 0.0}

        # 定义压缩规则: (文件名, 保留条数)
        compress_rules = {
            "predictions.json": 1000,
            "health_log.jsonl": 5000,
        }

        for filename, keep_count in compress_rules.items():
            filepath = os.path.join(self.data_dir, filename)

            if not os.path.isfile(filepath):
                logger.debug("文件不存在，跳过压缩: %s", filepath)
                continue

            file_size_kb = self._get_file_size_kb(filepath)
            if file_size_kb <= max_size_kb:
                logger.debug("文件未超过大小阈值，跳过压缩: %s (%.1f KB <= %d KB)",
                             filepath, file_size_kb, max_size_kb)
                continue

            logger.info("开始压缩: %s (当前 %.1f KB, 保留最新 %d 条)",
                        filepath, file_size_kb, keep_count)

            if filename == "predictions.json":
                saved = self._compress_predictions_json(filepath, keep_count)
            elif filename == "health_log.jsonl":
                saved = self._compress_jsonl_file(filepath, keep_count)
            else:
                continue

            if saved > 0:
                new_size_kb = self._get_file_size_kb(filepath)
                result["compressed"].append(filepath)
                result["saved_kb"] += saved
                logger.info("压缩完成: %s (节省 %.1f KB, 新大小 %.1f KB)",
                            filepath, saved, new_size_kb)
            else:
                logger.info("文件无需压缩或压缩失败: %s", filepath)

        result["saved_kb"] = round(result["saved_kb"], 2)
        return result

    def _compress_predictions_json(self, filepath: str, keep_count: int) -> float:
        """压缩 predictions.json 文件，保留最新 N 条记录

        Args:
            filepath: 文件路径
            keep_count: 保留的记录条数

        Returns:
            float: 节省的磁盘空间（KB），失败返回 0
        """
        original_size_kb = self._get_file_size_kb(filepath)

        data = self._load_json_safe(filepath)
        if data is None:
            return 0.0

        if isinstance(data, list):
            if len(data) <= keep_count:
                logger.debug("predictions.json 记录数未超限 (%d <= %d)，跳过",
                             len(data), keep_count)
                return 0.0
            # 保留最后 keep_count 条（假设列表按时间递增排列）
            trimmed = data[-keep_count:]
        elif isinstance(data, dict):
            # 查找包含列表的键并裁剪
            list_keys = [k for k, v in data.items() if isinstance(v, list) and k != "_metadata"]
            any_trimmed = False
            for key in list_keys:
                records = data[key]
                if len(records) > keep_count:
                    data[key] = records[-keep_count:]
                    any_trimmed = True
            if not any_trimmed:
                return 0.0
            trimmed = data
        else:
            return 0.0

        if self._save_json_safe(filepath, trimmed):
            new_size_kb = self._get_file_size_kb(filepath)
            saved = max(0.0, original_size_kb - new_size_kb)
            logger.info("predictions.json 压缩: %.1f KB -> %.1f KB (节省 %.1f KB)",
                        original_size_kb, new_size_kb, saved)
            return saved
        return 0.0

    def _compress_jsonl_file(self, filepath: str, keep_count: int) -> float:
        """压缩 JSONL 文件，保留最新 N 行

        Args:
            filepath: 文件路径
            keep_count: 保留的行数

        Returns:
            float: 节省的磁盘空间（KB），失败返回 0
        """
        original_size_kb = self._get_file_size_kb(filepath)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except (OSError, UnicodeDecodeError) as e:
            logger.error("读取 JSONL 文件失败: %s (%s)", filepath, e)
            return 0.0

        if len(lines) <= keep_count:
            logger.debug("JSONL 文件行数未超限 (%d <= %d)，跳过",
                         len(lines), keep_count)
            return 0.0

        # 保留最后 keep_count 行
        trimmed_lines = lines[-keep_count:]

        try:
            parent = os.path.dirname(filepath) or "."
            fd, tmp = tempfile.mkstemp(suffix=".tmp", prefix=".dm_", dir=parent)
        except OSError as e:
            logger.error("创建 JSONL 临时文件失败: %s (%s)", filepath, e)
            return 0.0
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(trimmed_lines)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, filepath)
        except OSError as e:
            try:
                os.close(fd)
            except OSError:
                pass
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            logger.error("写入 JSONL 文件失败: %s (%s)", filepath, e)
            return 0.0

        new_size_kb = self._get_file_size_kb(filepath)
        saved = max(0.0, original_size_kb - new_size_kb)
        logger.info("JSONL 压缩: %s %.1f KB -> %.1f KB (节省 %.1f KB)",
                    filepath, original_size_kb, new_size_kb, saved)
        return saved

    def rebuild_indices(self) -> dict:
        """重建数据索引，验证核心文件完整性

        验证以下核心索引文件的完整性:
        - brain_state.json: 大脑状态文件
        - evolution_rules.json: 进化规则文件
        - reference_pool.json: 参考池文件

        如果文件损坏（JSON 解析失败），尝试从备份恢复。

        Returns:
            dict: 重建结果，包含:
                - checked (int):   检查的文件数量
                - repaired (int):  修复的文件数量
                - details (list):  每个文件的检查详情列表

        Examples:
            >>> maintainer = DataMaintainer()
            >>> result = maintainer.rebuild_indices()
            >>> for detail in result['details']:
            ...     print(f"{detail['file']}: {detail['status']}")
        """
        result = {"checked": 0, "repaired": 0, "details": []}

        # 定义要验证的核心索引文件
        index_files = {
            "brain_state.json": {"required_keys": None, "description": "大脑状态"},
            "evolution_rules.json": {"required_keys": None, "description": "进化规则"},
            "reference_pool.json": {"required_keys": None, "description": "参考池"},
        }

        for filename, config in index_files.items():
            filepath = os.path.join(self.data_dir, filename)
            detail = {
                "file": filename,
                "path": filepath,
                "status": "missing",
                "description": config["description"],
                "action": "",
            }
            result["checked"] += 1

            # 检查文件是否存在
            if not os.path.isfile(filepath):
                # 尝试从备份恢复
                logger.warning("索引文件缺失: %s，尝试从备份恢复", filepath)
                if self._try_restore_from_backup(filepath):
                    detail["status"] = "recovered"
                    detail["action"] = "从备份恢复"
                    result["repaired"] += 1
                else:
                    detail["action"] = "文件缺失且无可用备份"
                result["details"].append(detail)
                continue

            # 验证 JSON 可解析性
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 验证数据结构（基本非空检查）
                if isinstance(data, dict) and len(data) == 0:
                    # 空字典，可能是异常清空
                    logger.warning("索引文件内容为空字典: %s", filepath)
                    detail["status"] = "empty"
                    detail["action"] = "文件内容为空字典，建议检查"
                elif data is None:
                    logger.warning("索引文件内容为 null: %s", filepath)
                    detail["status"] = "null_content"
                    detail["action"] = "文件内容为 null"
                else:
                    detail["status"] = "healthy"
                    detail["action"] = "验证通过"

            except json.JSONDecodeError as e:
                logger.error("索引文件 JSON 解析失败: %s (%s)", filepath, e)
                detail["status"] = "corrupted"
                detail["action"] = f"JSON 解析失败: {e}"

                # 尝试从备份恢复
                logger.info("尝试从备份恢复损坏文件: %s", filepath)
                if self._try_restore_from_backup(filepath):
                    detail["status"] = "recovered"
                    detail["action"] = "从备份恢复成功"
                    result["repaired"] += 1
                else:
                    detail["action"] = "JSON 解析失败且无可用备份"

            except (OSError, UnicodeDecodeError) as e:
                logger.error("读取索引文件失败: %s (%s)", filepath, e)
                detail["status"] = "error"
                detail["action"] = f"读取失败: {e}"

            result["details"].append(detail)

        logger.info("索引重建完成: 检查 %d 个文件，修复 %d 个",
                    result["checked"], result["repaired"])
        return result

    def vacuum_all(self) -> dict:
        """一键执行所有维护操作

        按顺序执行以下维护操作:
        1. 清理过期缓存
        2. 清理过期预测记录
        3. 清理临时文件
        4. 压缩数据文件
        5. 重建索引

        Returns:
            dict: 汇总报告，包含每步操作的结果和总结信息

        Examples:
            >>> maintainer = DataMaintainer()
            >>> report = maintainer.vacuum_all()
            >>> print(f"总释放空间: {report['summary']['total_freed_kb']:.1f} KB")
        """
        logger.info("=" * 50)
        logger.info("开始执行数据库全面维护")
        logger.info("数据目录: %s", self.data_dir)
        logger.info("=" * 50)

        report = {
            "timestamp": datetime.now().isoformat(),
            "data_dir": self.data_dir,
            "steps": {},
            "summary": {
                "total_freed_kb": 0.0,
                "total_files_cleaned": 0,
                "total_records_removed": 0,
                "files_compressed": 0,
                "indices_repaired": 0,
                "errors": 0,
            },
        }

        # 步骤1: 清理过期缓存
        try:
            result = self.cleanup_expired_cache()
            report["steps"]["cleanup_expired_cache"] = result
            report["summary"]["total_freed_kb"] += result["freed_kb"]
            report["summary"]["total_files_cleaned"] += result["cleaned"]
        except Exception as e:
            logger.error("清理过期缓存异常: %s", e, exc_info=True)
            report["steps"]["cleanup_expired_cache"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        # 步骤2: 清理过期预测记录
        try:
            result = self.cleanup_old_predictions()
            report["steps"]["cleanup_old_predictions"] = result
            report["summary"]["total_records_removed"] += result["removed"]
        except Exception as e:
            logger.error("清理过期预测记录异常: %s", e, exc_info=True)
            report["steps"]["cleanup_old_predictions"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        # 步骤3: 清理临时文件
        try:
            result = self.cleanup_temp_files()
            report["steps"]["cleanup_temp_files"] = result
            report["summary"]["total_freed_kb"] += result["freed_kb"]
            report["summary"]["total_files_cleaned"] += result["cleaned"]
        except Exception as e:
            logger.error("清理临时文件异常: %s", e, exc_info=True)
            report["steps"]["cleanup_temp_files"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        # 步骤4: 压缩数据文件
        try:
            result = self.compress_data_files()
            report["steps"]["compress_data_files"] = result
            report["summary"]["total_freed_kb"] += result["saved_kb"]
            report["summary"]["files_compressed"] = len(result["compressed"])
        except Exception as e:
            logger.error("压缩数据文件异常: %s", e, exc_info=True)
            report["steps"]["compress_data_files"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        # 步骤5: 重建索引
        try:
            result = self.rebuild_indices()
            report["steps"]["rebuild_indices"] = result
            report["summary"]["indices_repaired"] = result["repaired"]
        except Exception as e:
            logger.error("重建索引异常: %s", e, exc_info=True)
            report["steps"]["rebuild_indices"] = {"error": str(e)}
            report["summary"]["errors"] += 1

        report["summary"]["total_freed_kb"] = round(report["summary"]["total_freed_kb"], 2)

        # 保存本次维护的统计快照
        self._save_stats_snapshot(report["summary"])

        logger.info("=" * 50)
        logger.info("数据库维护完成:")
        logger.info("  清理文件: %d 个", report["summary"]["total_files_cleaned"])
        logger.info("  删除记录: %d 条", report["summary"]["total_records_removed"])
        logger.info("  释放空间: %.2f KB", report["summary"]["total_freed_kb"])
        logger.info("  压缩文件: %d 个", report["summary"]["files_compressed"])
        logger.info("  修复索引: %d 个", report["summary"]["indices_repaired"])
        logger.info("  错误数:   %d", report["summary"]["errors"])
        logger.info("=" * 50)

        return report

    def get_data_stats(self) -> dict:
        """获取数据目录的统计信息

        扫描整个金水谣数据目录，统计:
        - 总大小和文件数量
        - 各子系统（stock, fund 等）的数据大小
        - 与上次维护时的增长趋势对比

        Returns:
            dict: 统计信息，包含:
                - total_size_kb (float):      总大小（KB）
                - total_files (int):          总文件数
                - sub_systems (dict):         各子系统大小明细
                - trend (dict):               与上次快照的增长趋势
                - last_maintenance (str|None): 上次维护时间

        Examples:
            >>> maintainer = DataMaintainer()
            >>> stats = maintainer.get_data_stats()
            >>> print(f"总大小: {stats['total_size_kb']:.1f} KB")
        """
        stats = {
            "total_size_kb": 0.0,
            "total_files": 0,
            "sub_systems": {},
            "trend": {
                "size_change_kb": 0.0,
                "file_change": 0,
                "growth_percent": 0.0,
            },
            "last_maintenance": None,
        }

        if not os.path.isdir(self.data_dir):
            logger.warning("数据目录不存在: %s", self.data_dir)
            return stats

        # 扫描数据目录
        for entry in os.listdir(self.data_dir):
            entry_path = os.path.join(self.data_dir, entry)
            if os.path.isfile(entry_path):
                file_size_kb = self._get_file_size_kb(entry_path)
                stats["total_size_kb"] += file_size_kb
                stats["total_files"] += 1
            elif os.path.isdir(entry_path):
                # 跳过备份和归档目录的详细统计
                if entry in ("backups", "archive"):
                    dir_size = self._get_dir_size_kb(entry_path)
                    stats["sub_systems"][entry] = {
                        "size_kb": round(dir_size, 2),
                        "files": self._count_files(entry_path),
                    }
                    stats["total_size_kb"] += dir_size
                    stats["total_files"] += stats["sub_systems"][entry]["files"]
                else:
                    dir_size = self._get_dir_size_kb(entry_path)
                    file_count = self._count_files(entry_path)
                    stats["sub_systems"][entry] = {
                        "size_kb": round(dir_size, 2),
                        "files": file_count,
                    }
                    stats["total_size_kb"] += dir_size
                    stats["total_files"] += file_count

        stats["total_size_kb"] = round(stats["total_size_kb"], 2)

        # 读取上次维护快照，计算增长趋势
        last_snapshot = self._load_stats_snapshot()
        if last_snapshot:
            stats["last_maintenance"] = last_snapshot.get("timestamp")
            last_size = last_snapshot.get("total_size_kb", 0)
            last_files = last_snapshot.get("total_files", 0)
            stats["trend"]["size_change_kb"] = round(stats["total_size_kb"] - last_size, 2)
            stats["trend"]["file_change"] = stats["total_files"] - last_files
            if last_size > 0:
                stats["trend"]["growth_percent"] = round(
                    (stats["total_size_kb"] - last_size) / last_size * 100, 2
                )

        logger.info("数据统计: 总大小 %.2f KB, %d 个文件",
                    stats["total_size_kb"], stats["total_files"])
        return stats

    # ------------------------------------------------------------------
    # 统计快照方法（内部使用）
    # ------------------------------------------------------------------

    def _get_dir_size_kb(self, dirpath: str) -> float:
        """递归计算目录大小（KB）

        Args:
            dirpath: 目录路径

        Returns:
            float: 目录总大小（KB）
        """
        total = 0.0
        try:
            for root, dirs, files in os.walk(dirpath):
                for filename in files:
                    filepath = os.path.join(root, filename)
                    try:
                        total += os.path.getsize(filepath) / 1024.0
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _count_files(self, dirpath: str) -> int:
        """递归统计目录中的文件数量

        Args:
            dirpath: 目录路径

        Returns:
            int: 文件总数
        """
        count = 0
        try:
            for root, dirs, files in os.walk(dirpath):
                count += len(files)
        except OSError:
            pass
        return count

    def _save_stats_snapshot(self, summary: dict) -> None:
        """保存本次维护的统计快照

        将统计信息保存到 .maintenance_stats.json，用于下次增长趋势对比。

        Args:
            summary: 维护汇总信息
        """
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "total_size_kb": 0.0,
            "total_files": 0,
        }

        # 获取当前数据目录统计
        if os.path.isdir(self.data_dir):
            snapshot["total_size_kb"] = round(self._get_dir_size_kb(self.data_dir), 2)
            snapshot["total_files"] = self._count_files(self.data_dir)

        # 附加维护摘要
        snapshot["last_maintenance_summary"] = summary

        self._save_json_safe(self._stats_snapshot_file, snapshot)

    def _load_stats_snapshot(self) -> Optional[dict]:
        """加载上次维护的统计快照

        Returns:
            dict or None: 上次快照数据，不存在返回 None
        """
        if not os.path.isfile(self._stats_snapshot_file):
            return None
        return self._load_json_safe(self._stats_snapshot_file)


# ---------------------------------------------------------------------------
# 模块自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import tempfile

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 60)
    print("金水谣 data_maintenance 模块自测")
    print("=" * 60)

    # 创建临时测试目录
    with tempfile.TemporaryDirectory() as tmpdir:
        test_data_dir = os.path.join(tmpdir, "金水谣数据")
        os.makedirs(test_data_dir)

        # 构造测试数据
        stock_cache = os.path.join(test_data_dir, "stock", "cache")
        fund_cache = os.path.join(test_data_dir, "fund", "cache")
        os.makedirs(stock_cache, exist_ok=True)
        os.makedirs(fund_cache, exist_ok=True)

        # 创建过期缓存文件
        old_cache = os.path.join(stock_cache, "old_cache.json")
        with open(old_cache, "w") as f:
            f.write('{"test": 1}')
        # 修改时间设为 10 天前
        old_time = time.time() - 10 * 24 * 3600
        os.utime(old_cache, (old_time, old_time))

        # 创建新缓存文件
        new_cache = os.path.join(stock_cache, "new_cache.json")
        with open(new_cache, "w") as f:
            f.write('{"test": 2}')

        # 创建临时文件
        tmp_file = os.path.join(test_data_dir, "test_temp.tmp")
        with open(tmp_file, "w") as f:
            f.write("temp data")

        # 创建测试用 predictions.json
        predictions = []
        for i in range(100):
            ts = datetime.now() - timedelta(days=i + 1)
            predictions.append({"id": i, "timestamp": ts.isoformat(), "value": i * 10})
        predictions_path = os.path.join(test_data_dir, "predictions.json")
        with open(predictions_path, "w", encoding="utf-8") as f:
            json.dump(predictions, f, ensure_ascii=False, indent=2)

        # 创建测试用 brain_state.json
        brain_state_path = os.path.join(test_data_dir, "brain_state.json")
        with open(brain_state_path, "w", encoding="utf-8") as f:
            json.dump({"mood": "happy", "energy": 0.8}, f, ensure_ascii=False, indent=2)

        # 运行测试
        maintainer = DataMaintainer(data_dir=test_data_dir)

        print("\n--- 测试1: 清理过期缓存 ---")
        r1 = maintainer.cleanup_expired_cache(max_age_days=7)
        print(f"  结果: {r1}")
        assert r1["cleaned"] == 1, "应清理1个过期缓存"
        assert os.path.isfile(new_cache), "新缓存应保留"

        print("\n--- 测试2: 清理过期预测 ---")
        r2 = maintainer.cleanup_old_predictions(keep_days=30)
        print(f"  结果: {r2}")
        assert r2["before"] == 100, "应有100条预测记录"
        assert r2["removed"] > 0, "应删除部分过期记录"

        print("\n--- 测试3: 清理临时文件 ---")
        r3 = maintainer.cleanup_temp_files()
        print(f"  结果: {r3}")
        assert r3["cleaned"] >= 1, "应清理至少1个临时文件"

        print("\n--- 测试4: 重建索引 ---")
        r4 = maintainer.rebuild_indices()
        print(f"  结果: {r4}")
        assert r4["checked"] == 3, "应检查3个索引文件"

        print("\n--- 测试5: 数据统计 ---")
        r5 = maintainer.get_data_stats()
        print(f"  总大小: {r5['total_size_kb']:.1f} KB, 文件数: {r5['total_files']}")

        print("\n--- 测试6: 一键维护 ---")
        r6 = maintainer.vacuum_all()
        print(f"  汇总: {r6['summary']}")

    print("\n" + "=" * 60)
    print("自测完成")
    print("=" * 60)