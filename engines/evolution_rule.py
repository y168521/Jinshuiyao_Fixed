# -*- coding: utf-8 -*-
"""金水谣系统 - L3自适应进化引擎子模块（JS-20260810-10 由 engines/evolution.py 拆分）"""
import os
import re
import json
import uuid
import math
import logging
import threading
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from utils.safe_json import safe_write_json, safe_load_json
except ImportError:
    def safe_write_json(filepath, data):
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=parent, prefix=".evolution_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if os.path.exists(filepath):
                os.replace(tmp_path, filepath)
            else:
                os.rename(tmp_path, filepath)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def safe_load_json(filepath, default=None):
        if default is None:
            default = {}
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("加载文件失败 [%s]: %s，返回默认值", filepath, e)
            return default

_SEVERITY_LEVELS = {"info": 1, "warn": 2, "critical": 3}
_DEFAULT_RULE_THRESHOLD = 3

class RuleEngine:

    """规则引擎 - 从重复出现的问题中提炼永久规则

    当同一类错误反复出现达到阈值（默认3次）时，

    自动将临时观察升级为永久规则，并在后续运行中自动执行修复动作。

    规则结构:

    {

        "rules": [{

            "id": "R001",

            "pattern": "错误模式描述（正则或关键词）",

            "severity": "info|warn|critical",

            "action": "自动修复动作",

            "trigger_count": 3,

            "occurrence_count": 0,

            "activated": false,

            "created": "...",

            "last_triggered": "...",

            "source": "auto|manual"

        }],

        "stats": {"total_rules": 0, "active_rules": 0}

    }

    """

    def __init__(self, rule_file="金水谣数据/evolution_rules.json"):

        """初始化规则引擎

        Args:

            rule_file: 规则持久化文件路径

        """

        self.rule_file = rule_file

        self._lock = threading.RLock()  # 可重入锁, 避免record_event->_save嵌套死锁

        self._data = self._load()

        self._pending_events = defaultdict(int)  # 未升级为规则的临时事件计数

    def _load(self):

        """加载规则文件"""

        default = {

            "rules": [],

            "stats": {"total_rules": 0, "active_rules": 0}

        }

        data = safe_load_json(self.rule_file, default)

        # 兼容旧格式：确保stats字段存在

        if "stats" not in data:

            data["stats"] = {"total_rules": 0, "active_rules": 0}

        if "rules" not in data:

            data["rules"] = []

        self._refresh_stats(data)

        logger.info("规则引擎就绪 (规则总数: %d, 已激活: %d)",

                     data["stats"]["total_rules"],

                     data["stats"]["active_rules"])

        return data

    @staticmethod

    def _refresh_stats(data):

        """刷新统计数据"""

        rules = data.get("rules", [])

        data["stats"]["total_rules"] = len(rules)

        data["stats"]["active_rules"] = sum(

            1 for r in rules if r.get("activated", False)

        )

    def _save(self):

        """持久化规则数据"""

        with self._lock:

            self._refresh_stats(self._data)

            try:

                safe_write_json(self.rule_file, self._data)

            except Exception as e:

                logger.error("保存规则文件失败: %s", e, exc_info=True)

                raise

    @staticmethod

    def _now_str():

        """返回当前时间的可读字符串"""

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod

    def _gen_rule_id():

        """生成规则ID"""

        return "R" + uuid.uuid4().hex[:6].upper()

    # ------------------------------------------------------------------

    # 公开接口

    # ------------------------------------------------------------------

    def record_event(self, error_message, category, data=None):

        """记录一次事件，检查是否触发规则升级

        流程:

        1. 遍历已有规则，用正则匹配pattern

        2. 匹配成功: occurrence_count += 1

        3. 达到trigger_count: activated = True, 执行action

        4. 无匹配: 创建临时记录（计入_pending_events），达到阈值自动创建新规则

        Args:

            error_message: 错误信息字符串

            category: 事件分类（如 "network", "parse", "predict", "data" 等）

            data: 附带数据（可选，存入规则的last_data字段）

        Returns:

            dict: {

                "matched_rule": str|None,    # 匹配到的规则ID

                "activated": bool,            # 本次是否激活了规则

                "action_result": str|None,    # 修复动作执行结果

                "new_rule_created": bool,     # 是否自动创建了新规则

                "event_category": str         # 事件分类

            }

        """

        result = {

            "matched_rule": None,

            "activated": False,

            "action_result": None,

            "new_rule_created": False,

            "event_category": category,

        }

        with self._lock:

            matched = False

            # 1. 遍历已有规则，尝试匹配

            for rule in self._data["rules"]:

                pattern = rule.get("pattern", "")

                try:

                    if re.search(pattern, error_message, re.IGNORECASE):

                        # 匹配成功

                        rule["occurrence_count"] = rule.get("occurrence_count", 0) + 1

                        rule["last_triggered"] = self._now_str()

                        if data is not None:

                            rule["last_data"] = data

                        result["matched_rule"] = rule["id"]

                        matched = True

                        # 2. 检查是否达到激活阈值

                        if (not rule.get("activated", False)

                                and rule["occurrence_count"] >= rule.get("trigger_count", _DEFAULT_RULE_THRESHOLD)):

                            rule["activated"] = True

                            result["activated"] = True

                            # 3. 执行修复动作

                            action = rule.get("action", "")

                            if action:

                                result["action_result"] = self._execute_action(action, rule, data)

                            logger.info("规则 [%s] 已激活，执行动作: %s",

                                        rule["id"], action[:50] if action else "无")

                        break

                except re.error:

                    # 正则表达式无效，跳过此规则

                    logger.warning("规则 [%s] 的正则表达式无效: %s", rule["id"], pattern)

                    continue

            # 4. 无匹配：记录临时事件

            if not matched:

                event_key = category + ":" + error_message[:100]

                self._pending_events[event_key] += 1

                count = self._pending_events[event_key]

                # 达到阈值：自动创建新规则

                if count >= _DEFAULT_RULE_THRESHOLD:

                    new_rule = self._create_rule_from_event(

                        error_message, category, count

                    )

                    if new_rule:

                        result["new_rule_created"] = True

                        result["matched_rule"] = new_rule["id"]

                        result["activated"] = True

                        # 清理临时计数

                        self._pending_events.pop(event_key, None)

                        logger.info("自动创建新规则 [%s]: %s",

                                    new_rule["id"], new_rule["pattern"][:50])

                        # 规则数量上限保护：超过500条时淘汰最旧的非激活规则

                        _MAX_RULES = 500

                        if len(self._data["rules"]) > _MAX_RULES:

                            inactive = [r for r in self._data["rules"] if not r.get("active", True)]

                            inactive.sort(key=lambda r: r.get("last_triggered", r.get("created_at", "")))

                            while len(self._data["rules"]) > _MAX_RULES and inactive:

                                old_rule = inactive.pop(0)

                                self._data["rules"].remove(old_rule)

                                logger.info("淘汰过期非激活规则 [%s]", old_rule.get("id", ""))

            # pending_events 过期清理：超过200条时清理最早的

            _MAX_PENDING = 200

            if len(self._pending_events) > _MAX_PENDING:

                # 保留计数最高的条目

                sorted_keys = sorted(self._pending_events, key=lambda k: self._pending_events[k], reverse=True)

                self._pending_events = defaultdict(int, {k: self._pending_events[k] for k in sorted_keys[:_MAX_PENDING // 2]})

            # 持久化

            self._save()

        return result

    def check_new_rule(self, error_message, category):

        """检查是否应该创建新规则（同一错误累计3次）

        Args:

            error_message: 错误信息

            category: 事件分类

        Returns:

            bool: 是否应创建新规则

        """

        event_key = category + ":" + error_message[:100]

        with self._lock:

            count = self._pending_events.get(event_key, 0)

            # 同时检查已有规则是否已覆盖（锁内访问共享数据）

            for rule in self._data["rules"]:

                try:

                    if re.search(rule.get("pattern", ""), error_message, re.IGNORECASE):

                        return False  # 已被已有规则覆盖

                except re.error:

                    continue

        return count >= _DEFAULT_RULE_THRESHOLD

    def get_active_rules(self):

        """获取所有已激活的规则

        Returns:

            list[dict]: 已激活的规则列表，按severity降序排列

        """

        with self._lock:

            active = [r for r in self._data["rules"] if r.get("activated", False)]

        # 按严重程度排序: critical > warn > info

        active.sort(

            key=lambda r: _SEVERITY_LEVELS.get(r.get("severity", "info"), 0),

            reverse=True

        )

        return active

    def apply_fixes(self, context=None):

        """应用所有已激活规则的修复动作

        Args:

            context: 上下文数据字典（传递给action的data参数）

        Returns:

            list[dict]: [{rule_id, action, result, success}]

        """

        active_rules = self.get_active_rules()

        results = []

        for rule in active_rules:

            action = rule.get("action", "")

            if not action:

                continue

            try:

                res = self._execute_action(action, rule, context)

                results.append({

                    "rule_id": rule["id"],

                    "action": action,

                    "result": res,

                    "success": True,

                })

            except Exception as e:

                logger.error("执行规则 [%s] 的修复动作失败: %s", rule["id"], e)

                results.append({

                    "rule_id": rule["id"],

                    "action": action,

                    "result": str(e),

                    "success": False,

                })

        if results:

            logger.info("应用了 %d 条规则的修复动作 (成功: %d)",

                         len(results),

                         sum(1 for r in results if r["success"]))

        return results

    def add_manual_rule(self, pattern, action, severity="warn",

                         trigger_count=1, category="manual"):

        """手动添加规则（立即激活）

        Args:

            pattern: 匹配模式（正则表达式）

            action: 修复动作描述

            severity: 严重级别

            trigger_count: 触发计数（手动添加默认1）

            category: 分类

        Returns:

            str: 新规则的ID

        """

        now = self._now_str()

        rule = {

            "id": self._gen_rule_id(),

            "pattern": pattern,

            "severity": severity,

            "action": action,

            "trigger_count": trigger_count,

            "occurrence_count": trigger_count,  # 手动规则立即达到触发阈值

            "activated": True,

            "created": now,

            "last_triggered": now,

            "source": "manual",

            "category": category,

        }

        with self._lock:

            self._data["rules"].append(rule)

            self._save()

        logger.info("手动添加规则 [%s]: %s (severity=%s)", rule["id"], pattern[:50], severity)

        return rule["id"]

    def remove_rule(self, rule_id):

        """删除指定规则

        Args:

            rule_id: 规则ID

        Returns:

            bool: 是否成功删除

        """

        with self._lock:

            before = len(self._data["rules"])

            self._data["rules"] = [r for r in self._data["rules"] if r["id"] != rule_id]

            removed = len(self._data["rules"]) < before

            if removed:

                self._save()

                logger.info("已删除规则 [%s]", rule_id)

        return removed

    def get_stats(self):

        """获取规则引擎统计信息

        Returns:

            dict: {total_rules, active_rules, pending_events, by_severity, by_category}

        """

        with self._lock:

            rules = self._data["rules"]

            stats = dict(self._data.get("stats", {}))

            stats["pending_events"] = len(self._pending_events)

            stats["by_severity"] = defaultdict(int)

            stats["by_category"] = defaultdict(int)

            for r in rules:

                stats["by_severity"][r.get("severity", "info")] += 1

                stats["by_category"][r.get("category", "unknown")] += 1

            stats["by_severity"] = dict(stats["by_severity"])

            stats["by_category"] = dict(stats["by_category"])

        return stats

    # ------------------------------------------------------------------

    # 内部方法

    # ------------------------------------------------------------------

    def _create_rule_from_event(self, error_message, category, count):

        """从累计事件自动创建规则

        Args:

            error_message: 错误信息

            category: 分类

            count: 已出现次数

        Returns:

            dict|None: 新创建的规则，或None（如果提取关键词失败）

        """

        # 从错误信息中提取关键词作为pattern

        pattern = self._extract_pattern(error_message)

        if not pattern:

            return None

        # 根据分类推断severity

        severity = "warn"

        if any(kw in error_message for kw in ["崩溃", "crash", "fatal", "critical"]):

            severity = "critical"

        elif any(kw in error_message for kw in ["警告", "warning", "超时", "timeout"]):

            severity = "warn"

        else:

            severity = "info"

        # 根据错误类型推断建议动作

        action = self._suggest_action(error_message, category)

        now = self._now_str()

        rule = {

            "id": self._gen_rule_id(),

            "pattern": pattern,

            "severity": severity,

            "action": action,

            "trigger_count": _DEFAULT_RULE_THRESHOLD,

            "occurrence_count": count,

            "activated": True,  # 达到阈值，立即激活

            "created": now,

            "last_triggered": now,

            "source": "auto",

            "category": category,

        }

        self._data["rules"].append(rule)

        return rule

    @staticmethod

    def _extract_pattern(error_message):

        """从错误信息中提取可匹配的正则pattern

        策略: 取错误信息中不含数字变量的核心关键词部分，

        转义特殊字符后作为正则匹配模式。

        Args:

            error_message: 错误信息字符串

        Returns:

            str: 正则表达式字符串，或空字符串

        """

        if not error_message or len(error_message) < 3:

            return ""

        # 取前80个字符

        text = error_message[:80].strip()

        # 移除纯数字（可能是变化的期号、数量等）

        text = re.sub(r'\b\d{4,}\b', '', text)

        # 移除多余的空白

        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) < 3:

            return ""

        # 转义正则特殊字符

        pattern = re.escape(text)

        return pattern

    @staticmethod

    def _suggest_action(error_message, category):

        """根据错误信息推断建议修复动作

        Args:

            error_message: 错误信息

            category: 分类

        Returns:

            str: 建议的修复动作描述

        """

        msg_lower = error_message.lower() if error_message else ""

        if "timeout" in msg_lower or "超时" in msg_lower:

            return "增加超时时间或启用重试机制"

        elif "connection" in msg_lower or "连接" in msg_lower:

            return "检查网络连接，必要时切换数据源"

        elif "parse" in msg_lower or "解析" in msg_lower:

            return "跳过异常数据行，启用容错解析"

        elif "file" in msg_lower or "文件" in msg_lower:

            return "检查文件路径和权限，尝试重建文件"

        elif "memory" in msg_lower or "内存" in msg_lower:

            return "清理缓存，减少数据加载量"

        elif "permission" in msg_lower or "权限" in msg_lower:

            return "检查文件和目录权限"

        elif "encode" in msg_lower or "编码" in msg_lower:

            return "强制使用UTF-8编码读写"

        elif category == "predict":

            return "记录异常预测参数，调整预测策略权重"

        elif category == "data":

            return "数据异常，启用数据校验和修复管线"

        else:

            return "记录并监控该类型错误"

    @staticmethod

    def _execute_action(action, rule, data=None):

        """执行修复动作（日志记录 + 动作描述返回）

        当前实现以记录为主，后续可扩展为实际执行脚本。

        返回动作描述字符串供调用方处理。

        Args:

            action: 动作描述字符串

            rule: 规则字典

            data: 附带数据

        Returns:

            str: 执行结果描述

        """

        logger.info("执行规则修复 [%s]: %s (data=%s)",

                     rule.get("id", "?"),

                     action,

                     str(data)[:100] if data else "无")

        return "已执行: " + action

# ===================================================================

# 2. 经验知识沉淀 (ExperienceMiner)

# ===================================================================
