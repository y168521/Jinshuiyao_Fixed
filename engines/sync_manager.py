# -*- coding: utf-8 -*-
"""
金水谣系统 - 离线优先同步管理器

确保系统联网时自动同步，离线时也能正常运行。

设计原则:
  - 默认离线运行，联网是增强而非必须
  - 所有核心功能离线可用
  - 联网时自动同步知识、规则、优化参数
  - 网络检测使用 requests 超时机制（不依赖第三方网络检测库）

同步钩子（预留扩展点）:
  - sync_knowledge     : 知识库同步
  - sync_rules         : 规则同步
  - sync_engine_params : 引擎参数同步
  - sync_model_updates : 模型更新下载
  - report_health      : 健康状态上报
"""

import os
import json
import time
import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 用于网络探测的轻量级 URL 列表（按优先级排序）
_PROBE_URLS = [
    "https://www.baidu.com",
    "https://www.qq.com",
    "https://httpbin.org/get",
]

# 网络检测默认超时（秒）
_DEFAULT_NETWORK_TIMEOUT = 3

# 离线队列文件名
_OFFLINE_QUEUE_FILENAME = "offline_queue.jsonl"

# 同步历史最大保留条数
_MAX_SYNC_HISTORY = 50


# ═══════════════════════════════════════════════════════════════════════════
# NetworkDetector - 轻量级网络状态检测
# ═══════════════════════════════════════════════════════════════════════════

class NetworkDetector:
    """轻量级网络状态检测

    使用 requests HEAD 请求探测网络连通性，不依赖第三方网络检测库。
    采用 URL 直连方式，避免 DNS 查询在某些离线环境中被劫持的问题。
    """

    def __init__(self):
        self._cache_online: Optional[bool] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 30.0  # 缓存有效期 30 秒
        self._last_latency: float = -1.0
        self._lock = threading.Lock()

    def is_online(self, timeout: float = _DEFAULT_NETWORK_TIMEOUT) -> bool:
        """检测网络是否可用

        尝试以 HEAD 请求连接一个轻量级 URL，超时由调用者指定。
        结果会被缓存，在 TTL 内的重复调用直接返回缓存值。

        Args:
            timeout: 连接超时秒数，默认 3 秒

        Returns:
            True 表示网络可用，False 表示不可用
        """
        # 检查缓存
        now = time.time()
        with self._lock:
            if self._cache_online is not None and (now - self._cache_time) < self._cache_ttl:
                return self._cache_online

        # 实际探测
        try:
            import requests
        except ImportError:
            logger.warning("requests 库不可用，默认视为离线")
            with self._lock:
                self._cache_online = False
                self._cache_time = now
            return False

        online = False
        latency = float("inf")

        for url in _PROBE_URLS:
            try:
                start = time.time()
                resp = requests.head(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    headers={"Connection": "close"},
                )
                elapsed_ms = (time.time() - start) * 1000.0
                # 任何 2xx/3xx 响应都视为在线
                if resp.status_code < 400:
                    online = True
                    latency = elapsed_ms
                    break  # 第一个成功即返回
            except requests.RequestException:
                continue

        # 写入缓存
        with self._lock:
            self._cache_online = online
            self._cache_time = now
            # 顺便缓存延迟（供 get_network_info 使用）
            if online:
                self._last_latency = latency

        status = "在线" if online else "离线"
        logger.debug("网络检测结果: %s (延迟 %.1fms)", status, latency if online else -1)
        return online

    def get_network_info(self) -> dict:
        """获取网络详细信息

        Returns:
            包含 online/latency_ms/last_check 的字典
        """
        online = self.is_online()
        latency = -1.0
        if online:
            with self._lock:
                latency = getattr(self, "_last_latency", -1.0)
        return {
            "online": online,
            "latency_ms": round(latency, 1),
            "last_check": datetime.now().isoformat(timespec="seconds"),
        }

    def invalidate_cache(self):
        """清除网络状态缓存，强制下次检测时重新探测"""
        with self._lock:
            self._cache_online = None
            self._cache_time = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# OfflineQueue - 离线操作队列
# ═══════════════════════════════════════════════════════════════════════════

class OfflineQueue:
    """离线操作队列 - 离线时缓存待同步的操作

    使用 JSONL 格式（每行一个 JSON 对象）持久化到磁盘。
    文件路径: <data_dir>/sync/offline_queue.jsonl

    线程安全：所有文件操作通过锁保护。
    """

    def __init__(self, data_dir: str = "金水谣数据"):
        self._queue_dir = os.path.join(data_dir, "sync")
        self._queue_file = os.path.join(self._queue_dir, _OFFLINE_QUEUE_FILENAME)
        self._lock = threading.Lock()
        self._ensure_dir()

    def _ensure_dir(self):
        """确保队列目录存在"""
        try:
            os.makedirs(self._queue_dir, exist_ok=True)
        except OSError as e:
            logger.error("创建同步队列目录失败 [%s]: %s", self._queue_dir, e)
            raise

    def enqueue(self, operation: str, data: dict):
        """将操作加入队列

        Args:
            operation: 操作类型，如 "sync_knowledge", "report_analytics",
                       "download_update" 等
            data: 操作附带的数据字典
        """
        entry = {
            "operation": operation,
            "data": data,
            "enqueued_at": datetime.now().isoformat(timespec="seconds"),
        }
        line = json.dumps(entry, ensure_ascii=False)

        with self._lock:
            try:
                with open(self._queue_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                logger.info("操作已加入离线队列: %s (队列长度=%d)",
                            operation, self._peek_unlocked())
            except OSError as e:
                logger.error("写入离线队列失败 [%s]: %s", self._queue_file, e)
                raise

    def dequeue_all(self) -> list:
        """取出所有待同步操作

        读取后将清空队列文件。

        Returns:
            操作条目列表，每个条目为 dict，包含 operation/data/enqueued_at
        """
        with self._lock:
            entries = []
            if not os.path.isfile(self._queue_file):
                return entries
            try:
                with open(self._queue_file, "r", encoding="utf-8") as f:
                    for raw_line in f:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            entry = json.loads(raw_line)
                            entries.append(entry)
                        except json.JSONDecodeError as e:
                            logger.warning("离线队列中有无法解析的行，已跳过: %s", e)
                            continue
            except OSError as e:
                logger.error("读取离线队列失败 [%s]: %s", self._queue_file, e)
                raise

            # 读取成功后清空文件
            try:
                with open(self._queue_file, "w", encoding="utf-8") as f:
                    pass  # 清空文件内容
            except OSError as e:
                logger.error("清空离线队列文件失败: %s", e)

            logger.info("从离线队列取出 %d 条操作", len(entries))
            return entries

    def peek(self) -> int:
        """查看队列中有多少待同步操作

        Returns:
            待同步操作数量
        """
        with self._lock:
            return self._peek_unlocked()

    def _peek_unlocked(self) -> int:
        """不加锁的内部计数方法（调用方须持有锁）"""
        if not os.path.isfile(self._queue_file):
            return 0
        try:
            count = 0
            with open(self._queue_file, "r", encoding="utf-8") as f:
                for raw_line in f:
                    if raw_line.strip():
                        count += 1
            return count
        except OSError as e:
            logger.error("读取离线队列计数失败: %s", e)
            return -1

    def clear(self):
        """清空队列（同步成功后调用）"""
        with self._lock:
            try:
                if os.path.isfile(self._queue_file):
                    with open(self._queue_file, "w", encoding="utf-8") as f:
                        pass
                    logger.info("离线队列已清空")
                else:
                    logger.debug("离线队列文件不存在，无需清空")
            except OSError as e:
                logger.error("清空离线队列失败: %s", e)
                raise


# ═══════════════════════════════════════════════════════════════════════════
# SyncManager - 同步管理器
# ═══════════════════════════════════════════════════════════════════════════

class SyncManager:
    """同步管理器 - 管理联网/离线状态和同步操作

    核心职责:
      1. 检测网络连接状态
      2. 联网时：处理离线队列 + 同步知识/规则/参数
      3. 离线时：将操作缓存到离线队列，确保系统正常运行
      4. 提供同步状态查询接口

    所有同步操作彼此独立，单个失败不影响其他。
    """

    # 已知的同步操作类型（用于校验）
    KNOWN_OPERATIONS = {
        "sync_knowledge",
        "sync_rules",
        "sync_engine_params",
        "sync_model_updates",
        "report_health",
        "report_analytics",
        "download_update",
    }

    def __init__(self, data_dir: str = "金水谣数据"):
        self.network = NetworkDetector()
        self.queue = OfflineQueue(data_dir)
        self.data_dir = data_dir

        self.is_online: bool = False
        self.last_sync_time: Optional[str] = None
        self.sync_history: list = []

        self._lock = threading.Lock()

        logger.info("同步管理器已初始化 (数据目录: %s)", data_dir)

    # ------------------------------------------------------------------
    # 网络检测
    # ------------------------------------------------------------------

    def check_connection(self) -> bool:
        """检查网络连接状态并更新内部标记

        Returns:
            当前是否在线
        """
        self.is_online = self.network.is_online()
        status = "在线" if self.is_online else "离线"
        logger.info("网络状态: %s", status)
        return self.is_online

    # ------------------------------------------------------------------
    # 同步操作（每个独立，单个失败不影响其他）
    # ------------------------------------------------------------------

    def sync_knowledge(self, knowledge_db=None) -> dict:
        """同步知识库

        扫描 knowledge/ 目录下的所有 .json/.md 文件，统计数量与总大小，
        模拟知识库同步操作（离线优先模式下执行本地快照与校验）。

        Args:
            knowledge_db: 知识库对象（可选），预留用于未来的深度同步；
                          为 None 时仅基于文件系统扫描。

        Returns:
            {"success": bool, "synced": int, "total_size": int,
             "files": [...], "message": str}
        """
        # 定位 knowledge 目录（相对于项目根目录，即当前文件的上两级）
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        knowledge_dir = os.path.join(base_dir, "knowledge")

        result = {
            "success": False,
            "synced": 0,
            "total_size": 0,
            "files": [],
            "message": "",
        }

        try:
            if not os.path.isdir(knowledge_dir):
                result["message"] = f"knowledge 目录不存在: {knowledge_dir}"
                logger.warning(result["message"])
                self._record_sync("sync_knowledge", False, result["message"])
                return result

            synced_files = []
            total_size = 0

            for fname in sorted(os.listdir(knowledge_dir)):
                fpath = os.path.join(knowledge_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                # 仅处理 .json 和 .md 文件
                if not (fname.endswith(".json") or fname.endswith(".md")):
                    continue
                # 跳过纯备份文件（.bak.N 后缀）以避免重复计数
                if ".bak." in fname:
                    continue
                try:
                    size = os.path.getsize(fpath)
                except OSError:
                    continue
                synced_files.append({
                    "name": fname,
                    "size": size,
                    "path": fpath,
                })
                total_size += size

            result["success"] = True
            result["synced"] = len(synced_files)
            result["total_size"] = total_size
            result["files"] = synced_files
            result["message"] = (
                f"知识库同步完成，共 {len(synced_files)} 个文件，总大小 {total_size} 字节"
            )

            # 离线时也加入队列以备联网后推送
            if not self.is_online:
                try:
                    self._queue_if_offline("sync_knowledge", {
                        "file_count": len(synced_files),
                        "total_size": total_size,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
                except Exception as e:
                    logger.error("知识库同步加入离线队列失败: %s", e)

            self._record_sync("sync_knowledge", True, result["message"])
            logger.info("知识库同步完成: %d 个文件, %d 字节",
                        len(synced_files), total_size)
            return result

        except Exception as e:
            result["message"] = f"知识库同步失败: {str(e)}"
            logger.error(result["message"])
            self._record_sync("sync_knowledge", False, result["message"])
            return result

    def sync_rules(self, rule_engine=None) -> dict:
        """同步进化规则和预测规则

        读取金水谣数据/evolution_rules.json 中的规则，按类别统计，
        同时扫描引擎目录中的规则相关模块，生成规则同步报告。

        Args:
            rule_engine: 规则引擎对象（可选），预留用于未来的深度规则同步；
                         为 None 时仅基于文件系统统计。

        Returns:
            {"success": bool, "rules_count": int, "categories": [...], "message": str}
        """
        rules_file = os.path.join(self.data_dir, "evolution_rules.json")

        result = {
            "success": False,
            "rules_count": 0,
            "categories": [],
            "message": "",
        }

        try:
            rules_data = {}
            if os.path.isfile(rules_file):
                try:
                    with open(rules_file, "r", encoding="utf-8") as f:
                        rules_data = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("读取 evolution_rules.json 失败: %s", e)
                    rules_data = {}

            rules_list = rules_data.get("rules", [])
            if not isinstance(rules_list, list):
                rules_list = []

            # 按类别统计
            category_map = {}
            activated_count = 0
            severity_map = {}

            for rule in rules_list:
                if not isinstance(rule, dict):
                    continue
                cat = rule.get("category", "uncategorized")
                sev = rule.get("severity", "unknown")
                if rule.get("activated", False):
                    activated_count += 1
                category_map[cat] = category_map.get(cat, 0) + 1
                severity_map[sev] = severity_map.get(sev, 0) + 1

            categories = [
                {"name": name, "count": count}
                for name, count in sorted(category_map.items(),
                                           key=lambda x: -x[1])
            ]

            # 额外统计：引擎规则文件
            engines_dir = os.path.dirname(os.path.abspath(__file__))
            engine_rule_files = []
            for fname in sorted(os.listdir(engines_dir)):
                if fname.endswith(".py") and ("rule" in fname.lower()
                                              or "evolution" in fname.lower()
                                              or "evolve" in fname.lower()):
                    fpath = os.path.join(engines_dir, fname)
                    try:
                        size = os.path.getsize(fpath)
                    except OSError:
                        size = 0
                    engine_rule_files.append({"name": fname, "size": size})

            result["success"] = True
            result["rules_count"] = len(rules_list)
            result["categories"] = categories
            result["activated"] = activated_count
            result["severities"] = severity_map
            result["engine_rule_files"] = engine_rule_files
            result["message"] = (
                f"规则同步完成，共 {len(rules_list)} 条规则（激活 {activated_count}），{len(categories)} 个类别，{len(engine_rule_files)} 个引擎规则文件"
            )

            # 离线时入队
            if not self.is_online:
                try:
                    self._queue_if_offline("sync_rules", {
                        "rules_count": len(rules_list),
                        "categories": [c["name"] for c in categories],
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
                except Exception as e:
                    logger.error("规则同步加入离线队列失败: %s", e)

            self._record_sync("sync_rules", True, result["message"])
            logger.info("规则同步完成: %d 条规则, %d 个类别",
                        len(rules_list), len(categories))
            return result

        except Exception as e:
            result["message"] = f"规则同步失败: {str(e)}"
            logger.error(result["message"])
            self._record_sync("sync_rules", False, result["message"])
            return result

    def sync_analytics(self, analytics_data: dict) -> bool:
        """同步分析数据（匿名统计数据）

        Args:
            analytics_data: 待上报的分析数据字典

        Returns:
            是否同步成功
        """
        if not self.is_online:
            logger.info("当前离线，分析数据上报已加入队列")
            try:
                self._queue_if_offline("report_analytics", {
                    "analytics": analytics_data,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                })
            except Exception as e:
                logger.error("加入离线队列失败: %s", e)
            return False

        try:
            logger.info("分析数据上报：预留接口，未实现，安全跳过（诚实标记 JS-20260806-10）")
            # TODO: 实现具体的数据上报逻辑（联网端点就绪后实现）
            #   1. 将 analytics_data 序列化
            #   2. POST 到远程统计端点
            # 诚实标记：本接口未实际执行 → record reserved=True + success=False；
            # 返回 True 仅表「队列已 ack/已处理」（避免离线队列误判失败），非「同步成功」。
            self._record_sync("report_analytics", False,
                              "reserved: 预留接口未实现，已安全跳过（非成功、非失败）",
                              reserved=True)
            return True
        except Exception as e:
            logger.error("分析数据上报失败: %s", e)
            self._record_sync("report_analytics", False, str(e))
            return False

    def sync_engine_params(self, params: dict) -> bool:
        """同步引擎参数（联网时）

        Args:
            params: 引擎参数字典

        Returns:
            是否同步成功
        """
        if not self.is_online:
            logger.info("当前离线，引擎参数同步已加入队列")
            try:
                self._queue_if_offline("sync_engine_params", {
                    "params": params,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                })
            except Exception as e:
                logger.error("加入离线队列失败: %s", e)
            return False

        try:
            logger.info("引擎参数同步：预留接口，未实现，安全跳过（诚实标记 JS-20260806-10）")
            # TODO: 实现具体的参数同步逻辑（联网端点就绪后实现）
            # 诚实标记：本接口未实际执行 → record reserved=True + success=False；
            # 返回 True 仅表「队列已 ack/已处理」，非「同步成功」。
            self._record_sync("sync_engine_params", False,
                              "reserved: 预留接口未实现，已安全跳过（非成功、非失败）",
                              reserved=True)
            return True
        except Exception as e:
            logger.error("引擎参数同步失败: %s", e)
            self._record_sync("sync_engine_params", False, str(e))
            return False

    def sync_model_updates(self) -> bool:
        """检查并下载模型更新（联网时）

        Returns:
            是否有更新或同步成功
        """
        if not self.is_online:
            logger.info("当前离线，模型更新检查已加入队列")
            try:
                self._queue_if_offline("sync_model_updates", {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                })
            except Exception as e:
                logger.error("加入离线队列失败: %s", e)
            return False

        try:
            logger.info("模型更新检查：预留接口，未实现，安全跳过（诚实标记 JS-20260806-10）")
            # TODO: 实现具体的模型更新检查逻辑（联网端点就绪后实现）
            # 诚实标记：本接口未实际执行 → record reserved=True + success=False；
            # 返回 True 仅表「队列已 ack/已处理」，非「同步成功」。
            self._record_sync("sync_model_updates", False,
                              "reserved: 预留接口未实现，已安全跳过（非成功、非失败）",
                              reserved=True)
            return True
        except Exception as e:
            logger.error("模型更新检查失败: %s", e)
            self._record_sync("sync_model_updates", False, str(e))
            return False

    def report_health(self, health_data: dict) -> bool:
        """上报系统健康状态（联网时）

        Args:
            health_data: 健康状态数据字典

        Returns:
            是否上报成功
        """
        if not self.is_online:
            logger.info("当前离线，健康状态上报已加入队列")
            try:
                self._queue_if_offline("report_health", {
                    "health": health_data,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                })
            except Exception as e:
                logger.error("加入离线队列失败: %s", e)
            return False

        try:
            logger.info("健康状态上报：预留接口，未实现，安全跳过（诚实标记 JS-20260806-10）")
            # TODO: 实现具体的健康上报逻辑（联网端点就绪后实现）
            # 诚实标记：本接口未实际执行 → record reserved=True + success=False；
            # 返回 True 仅表「队列已 ack/已处理」，非「同步成功」。
            self._record_sync("report_health", False,
                              "reserved: 预留接口未实现，已安全跳过（非成功、非失败）",
                              reserved=True)
            return True
        except Exception as e:
            logger.error("健康状态上报失败: %s", e)
            self._record_sync("report_health", False, str(e))
            return False

    # ------------------------------------------------------------------
    # 数据上报与参数同步（本地实现，无需网络）
    # ------------------------------------------------------------------

    def upload_data(self) -> dict:
        """数据上报

        统计金水谣数据/ 目录下所有文件的数量和总大小，模拟上报到中心。
        按子目录分类统计，便于了解数据分布。

        Returns:
            {"success": bool, "uploaded": int, "total_size_kb": float,
             "message": str}
        """
        data_dir = self.data_dir

        result = {
            "success": False,
            "uploaded": 0,
            "total_size_kb": 0.0,
            "message": "",
        }

        try:
            if not os.path.isdir(data_dir):
                result["message"] = f"数据目录不存在: {data_dir}"
                logger.warning(result["message"])
                return result

            total_files = 0
            total_bytes = 0
            dir_stats = {}

            for root, dirs, files in os.walk(data_dir):
                # 跳过 sync 子目录（离线队列等内部数据）
                rel_dir = os.path.relpath(root, data_dir)
                if rel_dir == "sync":
                    continue
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        size = os.path.getsize(fpath)
                    except OSError:
                        continue
                    total_files += 1
                    total_bytes += size
                    # 按顶层目录归类
                    parts = rel_dir.split(os.sep) if rel_dir != "." else []
                    top_dir = parts[0] if parts else "root"
                    if top_dir not in dir_stats:
                        dir_stats[top_dir] = {"files": 0, "size": 0}
                    dir_stats[top_dir]["files"] += 1
                    dir_stats[top_dir]["size"] += size

            total_size_kb = round(total_bytes / 1024.0, 2)

            result["success"] = True
            result["uploaded"] = total_files
            result["total_size_kb"] = total_size_kb
            result["dir_stats"] = dir_stats
            result["message"] = (
                f"数据上报完成，共 {total_files} 个文件，总大小 {total_size_kb:.2f} KB"
            )

            # 离线时入队
            if not self.is_online:
                try:
                    self._queue_if_offline("report_analytics", {
                        "uploaded": total_files,
                        "total_size_kb": total_size_kb,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
                except Exception as e:
                    logger.error("数据上报加入离线队列失败: %s", e)

            self._record_sync("upload_data", True, result["message"])
            logger.info("数据上报完成: %d 个文件, %.2f KB",
                        total_files, total_size_kb)
            return result

        except Exception as e:
            result["message"] = f"数据上报失败: {str(e)}"
            logger.error(result["message"])
            self._record_sync("upload_data", False, result["message"])
            return result

    def sync_parameters(self) -> dict:
        """参数同步

        读取 config.py 中的关键系统配置，生成参数清单，
        模拟与中心节点的参数同步校验。

        Returns:
            {"success": bool, "params_count": int, "synced": [...],
             "message": str}
        """
        result = {
            "success": False,
            "params_count": 0,
            "synced": [],
            "message": "",
        }

        try:
            # 尝试从项目根目录导入 config
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            import sys
            if base_dir not in sys.path:
                sys.path.insert(0, base_dir)

            try:
                import config as cfg
            except ImportError:
                result["message"] = "无法导入 config 模块"
                logger.warning(result["message"])
                return result

            # 提取关键配置项（大写常量）
            synced_params = []
            for key in sorted(dir(cfg)):
                if key.startswith("_"):
                    continue
                val = getattr(cfg, key)
                # 仅同步简单类型和短字符串/字典，跳过模块等复杂对象
                if isinstance(val, (int, float, bool, str)):
                    synced_params.append({
                        "key": key,
                        "value": str(val)[:200],  # 截断过长的值
                        "type": type(val).__name__,
                    })
                elif isinstance(val, (dict, list, tuple)):
                    synced_params.append({
                        "key": key,
                        "value": f"<{type(val).__name__} len={len(val)}>",
                        "type": type(val).__name__,
                    })

            # 特别标记关键参数
            critical_keys = {"VERSION", "BASE_DIR", "TICKET_PRICE",
                             "DEFAULT_MAX_BUDGET", "MAX_BUDGET_LIMIT",
                             "DEFAULT_HOT_WINDOW"}
            for p in synced_params:
                p["critical"] = p["key"] in critical_keys

            result["success"] = True
            result["params_count"] = len(synced_params)
            result["synced"] = synced_params
            result["critical_count"] = sum(
                1 for p in synced_params if p.get("critical")
            )
            result["message"] = (
                f"参数同步完成，共 {len(synced_params)} 个参数（其中关键参数 {result['critical_count']} 个）"
            )

            # 离线时入队
            if not self.is_online:
                try:
                    self._queue_if_offline("sync_engine_params", {
                        "params_count": len(synced_params),
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
                except Exception as e:
                    logger.error("参数同步加入离线队列失败: %s", e)

            self._record_sync("sync_parameters", True, result["message"])
            logger.info("参数同步完成: %d 个参数", len(synced_params))
            return result

        except Exception as e:
            result["message"] = f"参数同步失败: {str(e)}"
            logger.error(result["message"])
            self._record_sync("sync_parameters", False, result["message"])
            return result

    def check_model_updates(self) -> dict:
        """模型更新检查

        扫描各引擎模块的版本信息和最后修改时间，
        对比本地状态，判断是否有可用更新。

        Returns:
            {"success": bool, "has_updates": bool, "updates": [...],
             "message": str}
        """
        engines_dir = os.path.dirname(os.path.abspath(__file__))

        result = {
            "success": False,
            "has_updates": False,
            "updates": [],
            "message": "",
        }

        try:
            if not os.path.isdir(engines_dir):
                result["message"] = f"引擎目录不存在: {engines_dir}"
                logger.warning(result["message"])
                return result

            engine_modules = []
            for fname in sorted(os.listdir(engines_dir)):
                if not fname.endswith(".py") or fname.startswith("_"):
                    continue
                fpath = os.path.join(engines_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                try:
                    mtime = os.path.getmtime(fpath)
                    size = os.path.getsize(fpath)
                except OSError:
                    continue
                module_name = fname[:-3]  # 去掉 .py
                engine_modules.append({
                    "module": module_name,
                    "file": fname,
                    "size": size,
                    "last_modified": datetime.fromtimestamp(mtime).isoformat(
                        timespec="seconds"),
                    "mtime": mtime,
                })

            # 检查是否有近期更新的模块（最近 24 小时内修改过视为"有更新"）
            now = time.time()
            recent_threshold = 24 * 3600  # 24 小时
            updates = []
            for mod in engine_modules:
                if (now - mod["mtime"]) < recent_threshold:
                    updates.append({
                        "module": mod["module"],
                        "last_modified": mod["last_modified"],
                        "size": mod["size"],
                        "status": "recently_updated",
                    })

            # 额外检查：数据目录中的模型/规则文件
            data_dir = self.data_dir
            data_files_check = ["evolution_rules.json", "brain_state.json",
                                "predictions.json", "correlation_matrix.json"]
            for df in data_files_check:
                df_path = os.path.join(data_dir, df)
                if os.path.isfile(df_path):
                    try:
                        mtime = os.path.getmtime(df_path)
                        size = os.path.getsize(df_path)
                        if (now - mtime) < recent_threshold:
                            updates.append({
                                "module": df,
                                "last_modified": datetime.fromtimestamp(
                                    mtime).isoformat(timespec="seconds"),
                                "size": size,
                                "status": "recently_updated",
                                "type": "data_file",
                            })
                    except OSError:
                        pass

            result["success"] = True
            result["has_updates"] = len(updates) > 0
            result["updates"] = updates
            result["total_engines"] = len(engine_modules)
            result["engine_list"] = [m["module"] for m in engine_modules]
            result["message"] = (
                f"模型更新检查完成，共 {len(engine_modules)} 个引擎模块，{len(updates)} 项近期更新"
            )

            # 离线时入队
            if not self.is_online and updates:
                try:
                    self._queue_if_offline("sync_model_updates", {
                        "update_count": len(updates),
                        "modules": [u["module"] for u in updates],
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
                except Exception as e:
                    logger.error("模型更新检查加入离线队列失败: %s", e)

            self._record_sync("check_model_updates", True, result["message"])
            logger.info("模型更新检查完成: %d 个引擎, %d 项更新",
                        len(engine_modules), len(updates))
            return result

        except Exception as e:
            result["message"] = f"模型更新检查失败: {str(e)}"
            logger.error(result["message"])
            self._record_sync("check_model_updates", False, result["message"])
            return result

    def upload_health(self) -> dict:
        """健康上报

        收集系统资源状态（CPU/内存/磁盘）和各子系统健康状况，
        生成健康报告并模拟上报。

        Returns:
            {"success": bool, "health_score": int, "metrics": {...},
             "message": str}
        """
        result = {
            "success": False,
            "health_score": 0,
            "metrics": {},
            "message": "",
        }

        try:
            metrics = {}
            health_score = 100  # 满分 100，逐项扣分

            # 1. 进程运行时间
            try:
                import sys
                if hasattr(sys, "platform"):
                    metrics["platform"] = sys.platform
                if hasattr(sys, "version"):
                    metrics["python_version"] = sys.version.split()[0]
            except Exception:
                pass

            # 2. 磁盘使用情况（数据目录所在磁盘）
            try:
                data_dir = self.data_dir
                if os.path.isdir(data_dir):
                    # 使用 os.statvfs 或 ctypes 获取磁盘信息（跨平台降级方案）
                    disk_total = 0
                    disk_free = 0
                    disk_used_pct = 0.0
                    try:
                        # Windows 下使用 ctypes
                        import ctypes
                        if os.name == "nt":
                            free_bytes = ctypes.c_ulonglong(0)
                            total_bytes = ctypes.c_ulonglong(0)
                            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                                ctypes.c_wchar_p(data_dir),
                                ctypes.byref(free_bytes),
                                ctypes.byref(total_bytes),
                                None,
                            )
                            disk_total = total_bytes.value
                            disk_free = free_bytes.value
                        else:
                            stat = os.statvfs(data_dir)
                            disk_total = stat.f_frsize * stat.f_blocks
                            disk_free = stat.f_bavail * stat.f_frsize
                        if disk_total > 0:
                            disk_used_pct = round(
                                (1 - disk_free / disk_total) * 100, 2)
                    except Exception:
                        pass

                    metrics["disk_total_mb"] = round(disk_total / (1024 * 1024), 2)
                    metrics["disk_free_mb"] = round(disk_free / (1024 * 1024), 2)
                    metrics["disk_used_percent"] = disk_used_pct

                    # 磁盘使用率超过 90% 扣分
                    if disk_used_pct > 90:
                        health_score -= 20
                    elif disk_used_pct > 75:
                        health_score -= 10
            except Exception as e:
                logger.warning("获取磁盘信息失败: %s", e)

            # 3. 数据目录健康检查
            try:
                data_dir = self.data_dir
                data_files = 0
                data_size = 0
                if os.path.isdir(data_dir):
                    for root, dirs, files in os.walk(data_dir):
                        data_files += len(files)
                        for fname in files:
                            fpath = os.path.join(root, fname)
                            try:
                                data_size += os.path.getsize(fpath)
                            except OSError:
                                pass

                metrics["data_files"] = data_files
                metrics["data_size_kb"] = round(data_size / 1024.0, 2)

                # 关键数据文件存在性检查
                critical_files = ["evolution_rules.json", "brain_state.json"]
                missing_critical = []
                for cf in critical_files:
                    if not os.path.isfile(os.path.join(data_dir, cf)):
                        missing_critical.append(cf)
                metrics["missing_critical_files"] = missing_critical
                if missing_critical:
                    health_score -= 15
            except Exception as e:
                logger.warning("数据目录健康检查失败: %s", e)

            # 4. 引擎模块完整性
            try:
                engines_dir = os.path.dirname(os.path.abspath(__file__))
                engine_count = 0
                if os.path.isdir(engines_dir):
                    for fname in os.listdir(engines_dir):
                        if fname.endswith(".py") and not fname.startswith("_"):
                            engine_count += 1
                metrics["engine_modules"] = engine_count
                if engine_count < 10:
                    health_score -= 10
            except Exception:
                pass

            # 5. 内存使用（尝试通过 psutil 或 tracemalloc 获取）
            try:
                import tracemalloc
                if not tracemalloc.is_tracing():
                    try:
                        tracemalloc.start()
                    except Exception:
                        pass
                if tracemalloc.is_tracing():
                    current, peak = tracemalloc.get_traced_memory()
                    metrics["memory_current_kb"] = round(current / 1024, 2)
                    metrics["memory_peak_kb"] = round(peak / 1024, 2)
            except Exception:
                pass

            # 6. 同步子系统状态
            try:
                pending = self.queue.peek()
                metrics["pending_operations"] = pending
                metrics["online"] = self.is_online
                if pending > 50:
                    health_score -= 5
            except Exception:
                pass

            # 确保分数在 0-100 之间
            health_score = max(0, min(100, health_score))

            result["success"] = True
            result["health_score"] = health_score
            result["metrics"] = metrics
            result["timestamp"] = datetime.now().isoformat(timespec="seconds")
            result["message"] = (
                f"健康上报完成，健康评分 {health_score}/100"
            )

            # 离线时入队
            if not self.is_online:
                try:
                    self._queue_if_offline("report_health", {
                        "health_score": health_score,
                        "metrics_keys": list(metrics.keys()),
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    })
                except Exception as e:
                    logger.error("健康上报加入离线队列失败: %s", e)

            self._record_sync("upload_health", True, result["message"])
            logger.info("健康上报完成: 评分 %d/100", health_score)
            return result

        except Exception as e:
            result["message"] = f"健康上报失败: {str(e)}"
            logger.error(result["message"])
            self._record_sync("upload_health", False, result["message"])
            return result

    # ------------------------------------------------------------------
    # 离线队列处理
    # ------------------------------------------------------------------

    def process_offline_queue(self) -> dict:
        """处理离线队列中的待同步操作

        遍历队列中的每条操作，根据操作类型分发给对应的同步方法。
        每条操作独立处理，单条失败不中断后续操作。

        Returns:
            处理结果摘要 {"total": int, "success": int, "failed": int, "errors": list}
        """
        entries = self.queue.dequeue_all()
        result = {
            "total": len(entries),
            "success": 0,
            "failed": 0,
            "errors": [],
        }

        if not entries:
            logger.info("离线队列为空，无需处理")
            return result

        logger.info("开始处理离线队列，共 %d 条操作", len(entries))

        for entry in entries:
            operation = entry.get("operation", "")
            data = entry.get("data", {})
            enqueued_at = entry.get("enqueued_at", "unknown")

            if operation not in self.KNOWN_OPERATIONS:
                logger.warning("未知的队列操作类型: %s (入队时间: %s)，跳过",
                               operation, enqueued_at)
                result["failed"] += 1
                result["errors"].append({
                    "operation": operation,
                    "error": f"未知操作类型: {operation}",
                })
                continue

            try:
                # 根据操作类型分发处理
                ok = self._dispatch_offline_operation(operation, data)
                if ok:
                    result["success"] += 1
                else:
                    result["failed"] += 1
                    result["errors"].append({
                        "operation": operation,
                        "error": "同步方法返回失败",
                    })
            except Exception as e:
                logger.error("处理离线操作失败 [%s]: %s", operation, e)
                result["failed"] += 1
                result["errors"].append({
                    "operation": operation,
                    "error": str(e),
                })

        logger.info("离线队列处理完成: 成功=%d, 失败=%d",
                    result["success"], result["failed"])
        return result

    def _dispatch_offline_operation(self, operation: str, data: dict) -> bool:
        """分发离线操作到对应的同步方法

        Args:
            operation: 操作类型
            data: 操作数据

        Returns:
            是否处理成功
        """
        # 这些方法内部会再次检查网络状态，
        # 如果此时仍离线，会将操作重新入队
        if operation == "sync_knowledge":
            return self.sync_knowledge(data.get("source", data))
        elif operation == "sync_rules":
            return self.sync_rules(data.get("source", data))
        elif operation == "sync_engine_params":
            return self.sync_engine_params(data.get("params", data))
        elif operation == "sync_model_updates":
            return self.sync_model_updates()
        elif operation == "report_health":
            return self.report_health(data.get("health", data))
        elif operation == "report_analytics":
            return self.sync_analytics(data.get("analytics", data))
        elif operation == "download_update":
            return self.sync_model_updates()
        else:
            logger.warning("无法分发操作: %s", operation)
            return False

    # ------------------------------------------------------------------
    # 自动同步
    # ------------------------------------------------------------------

    def auto_sync(self) -> dict:
        """自动同步（如果在线）

        执行流程:
          1. 检查网络
          2. 如果在线: 处理离线队列 + 同步知识/规则
          3. 如果离线: 记录状态，不做阻塞等待

        Returns:
            同步结果摘要
        """
        self.check_connection()

        if not self.is_online:
            logger.info("当前离线，自动同步跳过，所有操作将在联网后执行")
            return {
                "status": "offline",
                "message": "当前离线，自动同步跳过",
                "pending_operations": self.queue.peek(),
            }

        logger.info("检测到网络可用，开始自动同步")

        results = {}

        # 1. 先处理离线队列中积压的操作
        try:
            queue_result = self.process_offline_queue()
            results["offline_queue"] = queue_result
        except Exception as e:
            logger.error("处理离线队列异常: %s", e)
            results["offline_queue"] = {"error": str(e)}

        # 2. 同步知识库
        try:
            # knowledge_db 参数传 None 表示仅触发预留接口
            results["knowledge"] = self.sync_knowledge(None)
        except Exception as e:
            logger.error("自动同步知识库异常: %s", e)
            results["knowledge"] = {"error": str(e)}

        # 3. 同步规则
        try:
            results["rules"] = self.sync_rules(None)
        except Exception as e:
            logger.error("自动同步规则异常: %s", e)
            results["rules"] = {"error": str(e)}

        # 4. 检查模型更新
        try:
            results["model_updates"] = self.sync_model_updates()
        except Exception as e:
            logger.error("自动同步模型更新异常: %s", e)
            results["model_updates"] = {"error": str(e)}

        # 更新最后同步时间
        with self._lock:
            self.last_sync_time = datetime.now().isoformat(timespec="seconds")

        self._record_sync("auto_sync", True, "自动同步完成")

        logger.info("自动同步执行完毕")
        return results

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_sync_status(self) -> dict:
        """获取同步状态报告

        Returns:
            {
                "online": bool,
                "last_sync": str,
                "pending_operations": int,
                "sync_history": [...]
            }
        """
        with self._lock:
            return {
                "online": self.is_online,
                "network_info": self.network.get_network_info(),
                "last_sync": self.last_sync_time,
                "pending_operations": self.queue.peek(),
                "sync_history": list(self.sync_history),
            }

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _queue_if_offline(self, operation: str, data: dict):
        """离线时将操作加入队列（便捷方法）

        Args:
            operation: 操作类型
            data: 操作数据
        """
        self.queue.enqueue(operation, data)

    def _record_sync(self, operation: str, success: bool, detail: str = "",
                     reserved: bool = False):
        """记录一条同步历史

        Args:
            operation: 操作类型
            success: 是否成功（真实执行并成功才为 True）
            detail: 详细信息或错误消息
            reserved: 是否为「预留接口/未实现」的 no-op。True 时 success 应为
                False，表示「未实际执行、非成功也非失败」，用于诚实标记，
                避免对外谎称同步成功（JS-20260806-10）。
        """
        record = {
            "operation": operation,
            "success": success,
            "detail": detail,
            "reserved": reserved,
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self.sync_history.append(record)
            # 限制历史长度
            if len(self.sync_history) > _MAX_SYNC_HISTORY:
                self.sync_history = self.sync_history[-_MAX_SYNC_HISTORY:]
