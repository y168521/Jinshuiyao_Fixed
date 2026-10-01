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
    from core.infra.data_maintenance import DataMaintainer

    maintainer = DataMaintainer()
    report = maintainer.vacuum_all()
    print(report)
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import tempfile
from utils.safe_json import safe_write_json

logger = logging.getLogger("jinshuiyao.data_maintenance")


def _dm_get_file_age_days(filepath: str) -> float:
    try:
        return (time.time() - os.path.getmtime(filepath)) / (24 * 3600)
    except OSError:
        return -1


def _dm_get_file_size_kb(filepath: str) -> float:
    try:
        return os.path.getsize(filepath) / 1024.0
    except OSError:
        return 0.0


def _dm_scan_json_files(directory: str) -> List[str]:
    if not os.path.isdir(directory):
        logger.debug("目录不存在，跳过扫描: %s", directory)
        return []
    return [os.path.join(directory, e) for e in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, e)) and e.endswith(".json")]


def _dm_load_json_safe(filepath: str, default: object = None) -> object:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning("加载 JSON 失败: %s (%s)", filepath, e)
        return default
    except Exception as e:
        logger.error("加载 JSON 异常: %s (%s)", filepath, e, exc_info=True)
        return default


def _dm_save_json_safe(filepath: str, data: object) -> bool:
    try:
        return safe_write_json(filepath, data)
    except (OSError, TypeError) as e:
        logger.error("写入 JSON 失败: %s (%s)", filepath, e)
        return False


def _dm_try_restore_from_backup(filepath: str) -> bool:
    parent = os.path.dirname(filepath) or "."
    basename = os.path.basename(filepath)
    try:
        entries = os.listdir(parent)
    except OSError:
        return False
    backup_files = []
    for entry in entries:
        if entry.startswith(basename + ".bak."):
            try:
                backup_files.append((int(entry[len(basename) + 5:]), os.path.join(parent, entry)))
            except ValueError:
                continue
    backup_files.sort(key=lambda x: x[0], reverse=True)
    for _, bp in backup_files:
        try:
            with open(bp, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, (dict, list)):
                safe_write_json(filepath, data, backup=False)
                logger.info("从备份恢复成功: %s -> %s", bp, filepath)
                return True
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("备份文件也损坏: %s (%s)", bp, e)
    return False


def _dm_cleanup_expired_cache(m, max_age_days: int = 7) -> dict:
    result = {"cleaned": 0, "freed_kb": 0.0, "files": []}
    cache_dirs = [os.path.join(m.data_dir, "stock", "cache"),
                  os.path.join(m.data_dir, "fund", "cache")]
    for cache_dir in cache_dirs:
        if not os.path.isdir(cache_dir):
            logger.debug("缓存目录不存在，跳过: %s", cache_dir)
            continue
        for filepath in _dm_scan_json_files(cache_dir):
            age = _dm_get_file_age_days(filepath)
            if age < 0:
                logger.warning("无法获取文件修改时间: %s", filepath)
                continue
            if age > max_age_days:
                size_kb = _dm_get_file_size_kb(filepath)
                try:
                    os.remove(filepath)
                    result["cleaned"] += 1
                    result["freed_kb"] += size_kb
                    result["files"].append(filepath)
                except OSError as e:
                    logger.error("删除缓存文件失败: %s (%s)", filepath, e)
    result["freed_kb"] = round(result["freed_kb"], 2)
    return result


def _extract_item_timestamp(item) -> Optional[float]:
    if not isinstance(item, dict):
        return None
    for key in ("timestamp", "time", "date", "created_at", "prediction_time", "update_time"):
        if key in item:
            val = item[key]
            try:
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    return datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError, OverflowError):
                continue
    return None


def _dm_cleanup_old_predictions(m, keep_days: int = 90) -> dict:
    result = {"before": 0, "after": 0, "removed": 0}
    path = os.path.join(m.data_dir, "predictions.json")
    if not os.path.isfile(path):
        return result
    data = _dm_load_json_safe(path, default=None)
    if data is None:
        return result
    cutoff = (datetime.now() - timedelta(days=keep_days)).timestamp()
    if isinstance(data, list):
        result["before"] = len(data)
        filtered = [it for it in data if (ts := _extract_item_timestamp(it)) is None or ts >= cutoff]
        result["after"] = len(filtered)
        result["removed"] = result["before"] - result["after"]
        if result["removed"] > 0:
            if not _dm_save_json_safe(path, filtered):
                result["after"] = result["before"]
                result["removed"] = 0
    elif isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list) and k != "_metadata"]
        if not list_keys:
            return result
        total_before = total_removed = 0
        for key in list_keys:
            records = data[key]
            total_before += len(records)
            data[key] = [it for it in records
                         if (ts := _extract_item_timestamp(it)) is None or ts >= cutoff]
            total_removed += len(records) - len(data[key])
        result["before"] = total_before
        result["after"] = total_before - total_removed
        result["removed"] = total_removed
        if total_removed > 0 and not _dm_save_json_safe(path, data):
            result["after"] = result["before"]
            result["removed"] = 0
    return result


def _dm_cleanup_temp_files(m) -> dict:
    result = {"cleaned": 0, "freed_kb": 0.0}
    if not os.path.isdir(m.data_dir):
        return result
    for root, dirs, files in os.walk(m.data_dir):
        if os.path.basename(root) in ("backups", "archive"):
            continue
        for filename in files:
            filepath = os.path.join(root, filename)
            is_temp = (filename.endswith(".tmp") or
                       (filename.startswith("test_") and "_tmp_" in filename) or
                       filename.startswith(".safe_json_"))
            if not is_temp:
                continue
            size_kb = _dm_get_file_size_kb(filepath)
            try:
                os.remove(filepath)
                result["cleaned"] += 1
                result["freed_kb"] += size_kb
            except OSError as e:
                logger.error("删除临时文件失败: %s (%s)", filepath, e)
    result["freed_kb"] = round(result["freed_kb"], 2)
    return result


def _dm_compress_predictions_json(m, filepath: str, keep_count: int) -> float:
    original = _dm_get_file_size_kb(filepath)
    data = _dm_load_json_safe(filepath)
    if data is None:
        return 0.0
    if isinstance(data, list):
        if len(data) <= keep_count:
            return 0.0
        trimmed = data[-keep_count:]
    elif isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list) and k != "_metadata"]
        any_trimmed = False
        for key in list_keys:
            if len(data[key]) > keep_count:
                data[key] = data[key][-keep_count:]
                any_trimmed = True
        if not any_trimmed:
            return 0.0
        trimmed = data
    else:
        return 0.0
    if _dm_save_json_safe(filepath, trimmed):
        saved = max(0.0, original - _dm_get_file_size_kb(filepath))
        return saved
    return 0.0


def _dm_compress_jsonl_file(m, filepath: str, keep_count: int) -> float:
    original = _dm_get_file_size_kb(filepath)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as e:
        logger.error("读取 JSONL 失败: %s (%s)", filepath, e)
        return 0.0
    if len(lines) <= keep_count:
        return 0.0
    trimmed = lines[-keep_count:]
    try:
        parent = os.path.dirname(filepath) or "."
        fd, tmp = tempfile.mkstemp(suffix=".tmp", prefix=".dm_", dir=parent)
    except OSError as e:
        logger.error("创建 JSONL 临时文件失败: %s (%s)", filepath, e)
        return 0.0
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(trimmed)
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
        logger.error("写入 JSONL 失败: %s (%s)", filepath, e)
        return 0.0
    return max(0.0, original - _dm_get_file_size_kb(filepath))


def _dm_compress_data_files(m, max_size_kb: int = 500) -> dict:
    result = {"compressed": [], "saved_kb": 0.0}
    rules = {"predictions.json": 1000, "health_log.jsonl": 5000}
    for filename, keep_count in rules.items():
        filepath = os.path.join(m.data_dir, filename)
        if not os.path.isfile(filepath):
            continue
        size_kb = _dm_get_file_size_kb(filepath)
        if size_kb <= max_size_kb:
            continue
        if filename == "predictions.json":
            saved = _dm_compress_predictions_json(m, filepath, keep_count)
        else:
            saved = _dm_compress_jsonl_file(m, filepath, keep_count)
        if saved > 0:
            result["compressed"].append(filepath)
            result["saved_kb"] += saved
    result["saved_kb"] = round(result["saved_kb"], 2)
    return result


def _dm_rebuild_indices(m) -> dict:
    result = {"checked": 0, "repaired": 0, "details": []}
    index_files = {
        "brain_state.json": "大脑状态",
        "evolution_rules.json": "进化规则",
        "reference_pool.json": "参考池",
    }
    for filename, desc in index_files.items():
        filepath = os.path.join(m.data_dir, filename)
        detail = {"file": filename, "path": filepath, "status": "missing",
                  "description": desc, "action": ""}
        result["checked"] += 1
        if not os.path.isfile(filepath):
            if _dm_try_restore_from_backup(filepath):
                detail["status"] = "recovered"
                detail["action"] = "从备份恢复"
                result["repaired"] += 1
            else:
                detail["action"] = "文件缺失且无可用备份"
            result["details"].append(detail)
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and len(data) == 0:
                detail["status"] = "empty"
                detail["action"] = "文件内容为空字典，建议检查"
            elif data is None:
                detail["status"] = "null_content"
                detail["action"] = "文件内容为 null"
            else:
                detail["status"] = "healthy"
                detail["action"] = "验证通过"
        except json.JSONDecodeError as e:
            detail["status"] = "corrupted"
            detail["action"] = f"JSON 解析失败: {e}"
            if _dm_try_restore_from_backup(filepath):
                detail["status"] = "recovered"
                detail["action"] = "从备份恢复成功"
                result["repaired"] += 1
        except (OSError, UnicodeDecodeError) as e:
            detail["status"] = "error"
            detail["action"] = f"读取失败: {e}"
        result["details"].append(detail)
    return result


def _dm_vacuum_all(m) -> dict:
    s = {"total_freed_kb": 0.0, "total_files_cleaned": 0, "total_records_removed": 0,
         "files_compressed": 0, "indices_repaired": 0, "errors": 0}
    report = {"timestamp": datetime.now().isoformat(), "data_dir": m.data_dir,
              "steps": {}, "summary": s}

    def _run(name, fn, freed_key=None, count_key=None):
        try:
            res = fn()
            report["steps"][name] = res
            if freed_key:
                s["total_freed_kb"] += res[freed_key]
            if count_key:
                s["total_files_cleaned"] += res.get(count_key, 0)
            return res
        except Exception as e:
            logger.error("%s 异常: %s", name, e, exc_info=True)
            report["steps"][name] = {"error": str(e)}
            s["errors"] += 1
            return None

    r = _run("cleanup_expired_cache", lambda: _dm_cleanup_expired_cache(m), "freed_kb", "cleaned")
    r = _run("cleanup_old_predictions", lambda: _dm_cleanup_old_predictions(m))
    if r:
        s["total_records_removed"] += r["removed"]
    _run("cleanup_temp_files", lambda: _dm_cleanup_temp_files(m), "freed_kb", "cleaned")
    r = _run("compress_data_files", lambda: _dm_compress_data_files(m))
    if r:
        s["total_freed_kb"] += r["saved_kb"]
        s["files_compressed"] = len(r["compressed"])
    r = _run("rebuild_indices", lambda: _dm_rebuild_indices(m))
    if r:
        s["indices_repaired"] = r["repaired"]
    s["total_freed_kb"] = round(s["total_freed_kb"], 2)
    _dm_save_stats_snapshot(m, s)
    return report


def _dm_get_dir_size_kb(dirpath: str) -> float:
    total = 0.0
    try:
        for root, dirs, files in os.walk(dirpath):
            for filename in files:
                try:
                    total += os.path.getsize(os.path.join(root, filename)) / 1024.0
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _dm_count_files(dirpath: str) -> int:
    count = 0
    try:
        for root, dirs, files in os.walk(dirpath):
            count += len(files)
    except OSError:
        pass
    return count


def _dm_save_stats_snapshot(m, summary: dict) -> None:
    snapshot = {"timestamp": datetime.now().isoformat(), "total_size_kb": 0.0, "total_files": 0}
    if os.path.isdir(m.data_dir):
        snapshot["total_size_kb"] = round(_dm_get_dir_size_kb(m.data_dir), 2)
        snapshot["total_files"] = _dm_count_files(m.data_dir)
    snapshot["last_maintenance_summary"] = summary
    _dm_save_json_safe(m._stats_snapshot_file, snapshot)


def _dm_load_stats_snapshot(m) -> Optional[dict]:
    if not os.path.isfile(m._stats_snapshot_file):
        return None
    return _dm_load_json_safe(m._stats_snapshot_file)


def _dm_get_data_stats(m) -> dict:
    stats = {"total_size_kb": 0.0, "total_files": 0, "sub_systems": {},
             "trend": {"size_change_kb": 0.0, "file_change": 0, "growth_percent": 0.0},
             "last_maintenance": None}
    if not os.path.isdir(m.data_dir):
        return stats
    for entry in os.listdir(m.data_dir):
        entry_path = os.path.join(m.data_dir, entry)
        if os.path.isfile(entry_path):
            stats["total_size_kb"] += _dm_get_file_size_kb(entry_path)
            stats["total_files"] += 1
        elif os.path.isdir(entry_path):
            dir_size = _dm_get_dir_size_kb(entry_path)
            file_count = _dm_count_files(entry_path)
            stats["sub_systems"][entry] = {"size_kb": round(dir_size, 2), "files": file_count}
            stats["total_size_kb"] += dir_size
            stats["total_files"] += file_count
    stats["total_size_kb"] = round(stats["total_size_kb"], 2)
    last = _dm_load_stats_snapshot(m)
    if last:
        stats["last_maintenance"] = last.get("timestamp")
        last_size = last.get("total_size_kb", 0)
        last_files = last.get("total_files", 0)
        stats["trend"]["size_change_kb"] = round(stats["total_size_kb"] - last_size, 2)
        stats["trend"]["file_change"] = stats["total_files"] - last_files
        if last_size > 0:
            stats["trend"]["growth_percent"] = round(
                (stats["total_size_kb"] - last_size) / last_size * 100, 2)
    return stats


class DataMaintainer:
    """金水谣数据目录自动维护器（方法委托模块级函数）。"""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.data_dir = os.path.join(project_root, "金水谣数据")
        else:
            self.data_dir = os.path.abspath(data_dir)
        self._stats_snapshot_file = os.path.join(self.data_dir, ".maintenance_stats.json")

    def cleanup_expired_cache(self, max_age_days=7):
        return _dm_cleanup_expired_cache(self, max_age_days)

    def cleanup_old_predictions(self, keep_days=90):
        return _dm_cleanup_old_predictions(self, keep_days)

    def cleanup_temp_files(self):
        return _dm_cleanup_temp_files(self)

    def compress_data_files(self, max_size_kb=500):
        return _dm_compress_data_files(self, max_size_kb)

    def rebuild_indices(self):
        return _dm_rebuild_indices(self)

    def vacuum_all(self):
        return _dm_vacuum_all(self)

    def get_data_stats(self):
        return _dm_get_data_stats(self)


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