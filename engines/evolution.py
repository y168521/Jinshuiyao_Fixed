# -*- coding: utf-8 -*-
"""金水谣系统 - L3自适应进化引擎

让系统从运行经验中学习，持续自我优化。

核心能力:
1. 规则升级管线 (RuleEngine)      - 从重复出现的问题中提炼永久规则
2. 经验知识沉淀 (ExperienceMiner) - 从健康日志中挖掘知识并转化为知识库卡片
3. 自适应反馈闭环 (AdaptiveFeedback) - 增强复盘学习效果，CUSUM统计 + 策略建议
4. 进化管理器 (EvolutionManager)  - 统一管理所有进化子模块的顶层入口

数据文件:
- 金水谣数据/evolution_rules.json   - 规则持久化存储
- 金水谣数据/evolution_state.json   - 进化引擎状态快照
- 金水谣数据/evolution_patterns.json - 已挖掘的经验模式缓存
"""

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

# ---------------------------------------------------------------------------
# 安全JSON读写（带内回退，以防safe_json模块加载失败）
# ---------------------------------------------------------------------------
try:
    from utils.safe_json import safe_write_json, safe_load_json
except ImportError:
    logger.warning("无法导入utils.safe_json，使用内置安全读写回退")

    def safe_write_json(filepath, data):
        """内置安全写入回退：先写临时文件再原子替换"""
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        import tempfile
        fd, tmp_path = tempfile.mkstemp(
            suffix=".tmp", dir=parent, prefix=".evolution_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Windows下原子替换：先删再重命名
            if os.path.exists(filepath):
                os.replace(tmp_path, filepath)
            else:
                os.rename(tmp_path, filepath)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def safe_load_json(filepath, default=None):
        """内置安全加载回退：支持损坏文件恢复"""
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


# ---------------------------------------------------------------------------
# 辅助常量
# ---------------------------------------------------------------------------
_SEVERITY_LEVELS = {"info": 1, "warn": 2, "critical": 3}

_DEFAULT_RULE_THRESHOLD = 3  # 同一错误出现几次后升级为规则


# ===================================================================
# 1. 规则升级管线 (RuleEngine)
# ===================================================================

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

class ExperienceMiner:
    """经验挖掘器 - 从健康日志中提炼知识

    分析历史运行数据，挖掘重复出现的模式，
    将经验自动转化为MiroFish知识库卡片供引擎调用。
    """

    def __init__(self, data_dir="金水谣数据"):
        """初始化经验挖掘器

        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = data_dir
        self.patterns_file = os.path.join(data_dir, "evolution_patterns.json")
        self._lock = threading.Lock()
        self._patterns_cache = self._load_patterns()

        # MiroFish知识库引用（延迟初始化）
        self._mirofish = None

    def _load_patterns(self):
        """加载已挖掘的模式缓存"""
        default = {"patterns": [], "last_mined": None, "mine_count": 0}
        return safe_load_json(self.patterns_file, default)

    def _save_patterns(self):
        """保存模式缓存"""
        try:
            safe_write_json(self.patterns_file, self._patterns_cache)
        except Exception as e:
            logger.error("保存经验模式失败: %s", e, exc_info=True)
            raise

    def _get_mirofish(self):
        """延迟获取MiroFish知识库实例

        Returns:
            MiroFishDB|None: 知识库实例
        """
        if self._mirofish is None:
            try:
                from knowledge.mirofish_db import MiroFishDB
                db_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "knowledge", "mirofish_db.json"
                )
                self._mirofish = MiroFishDB(db_path=db_path)
            except ImportError:
                logger.warning("无法导入MiroFishDB，知识沉淀功能不可用")
                return None
            except Exception as e:
                logger.error("初始化MiroFishDB失败: %s", e)
                return None
        return self._mirofish

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def mine_patterns(self, health_log_path, min_occurrences=3):
        """从健康日志中挖掘重复模式

        扫描日志文件，统计相似错误信息的出现频率，
        提取出现次数 >= min_occurrences 的模式。

        Args:
            health_log_path: 健康日志文件路径（或目录路径）
            min_occurrences: 最小出现次数阈值

        Returns:
            list[dict]: [{
                "pattern": "模式描述",
                "frequency": 出现次数,
                "suggested_rule": "建议规则",
                "confidence": 0.0-1.0
            }]
        """
        # 收集日志行
        lines = self._collect_log_lines(health_log_path)
        if not lines:
            logger.info("未找到日志数据: %s", health_log_path)
            return []

        # 统计相似行
        pattern_counts = defaultdict(int)
        pattern_examples = {}

        for line in lines:
            line = line.strip()
            if not line or len(line) < 10:
                continue
            # 标准化：移除时间戳、期号等变化部分
            normalized = self._normalize_log_line(line)
            if normalized:
                pattern_counts[normalized] += 1
                if normalized not in pattern_examples:
                    pattern_examples[normalized] = line

        # 筛选高频模式
        results = []
        for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
            if count < min_occurrences:
                continue

            confidence = min(1.0, count / max(1, min_occurrences * 2))
            suggested_rule = RuleEngine._suggest_action(pattern_examples.get(pattern, ""), "auto")

            results.append({
                "pattern": pattern_examples.get(pattern, pattern),
                "frequency": count,
                "suggested_rule": suggested_rule,
                "confidence": round(confidence, 2),
            })

        # 更新缓存
        with self._lock:
            self._patterns_cache["patterns"] = results
            self._patterns_cache["last_mined"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._patterns_cache["mine_count"] = self._patterns_cache.get("mine_count", 0) + 1
            self._save_patterns()

        logger.info("挖掘到 %d 个高频模式 (min_occurrences=%d)", len(results), min_occurrences)
        return results

    def auto_generate_knowledge_card(self, pattern):
        """将经验自动转化为MiroFish知识库卡片

        Args:
            pattern: 模式字典（来自mine_patterns的返回值）
                {
                    "pattern": "模式描述",
                    "frequency": 出现次数,
                    "suggested_rule": "建议规则",
                    "confidence": 0.0-1.0
                }

        Returns:
            str|None: 知识卡片ID，或None（如果知识库不可用）
        """
        mirofish = self._get_mirofish()
        if mirofish is None:
            logger.warning("知识库不可用，跳过知识卡片生成")
            return None

        frequency = pattern.get("frequency", 1)
        pattern_text = pattern.get("pattern", "未知模式")
        suggested_rule = pattern.get("suggested_rule", "")
        # confidence 可能来自持久化 JSON 缓存（字符串/None），必须安全转 float
        # 否则 {:.0%} 格式化会抛 "Unknown format code '%' for object of type 'str'"
        _conf_raw = pattern.get("confidence", 0.5)
        try:
            confidence = float(_conf_raw)
        except (TypeError, ValueError):
            confidence = 0.5

        # 构建卡片
        title = "自动发现: {} (出现{}次)".format(
            pattern_text[:40], frequency
        )
        content = (
            "系统在运行中发现重复模式: {}\n\n"
            "出现次数: {}\n"
            "置信度: {:.0%}\n"
            "建议措施: {}\n\n"
            "此知识卡片由进化引擎自动生成，基于运行数据分析。"
        ).format(
            pattern_text[:100],
            frequency,
            confidence,
            suggested_rule or "暂无"
        )

        # 确定引擎钩子
        engine_hook = "smart_brain"
        if any(kw in pattern_text for kw in ["网络", "抓取", "fetch"]):
            engine_hook = "data_fetch"
        elif any(kw in pattern_text for kw in ["预测", "命中", "复盘"]):
            engine_hook = "smart_brain"
        elif any(kw in pattern_text for kw in ["杀号", "过滤", "排除"]):
            engine_hook = "kill_strategy"

        try:
            card_id = mirofish.add_card(
                title=title,
                content=content,
                category="area",
                domain="lottery",
                tags=["自愈", "自动修复", "进化引擎"],
                source="evolution:auto",
                engine_hook=engine_hook,
                priority=min(10, max(1, int(confidence * 10))),
            )
            logger.info("知识卡片已生成: %s (模式出现%d次, 置信度%.0f%%)",
                         card_id, frequency, confidence * 100)
            return card_id
        except Exception as e:
            logger.error("生成知识卡片失败: %s", e, exc_info=True)
            return None

    def batch_generate_cards(self, patterns):
        """批量将多个模式转化为知识卡片

        Args:
            patterns: 模式列表（来自mine_patterns）

        Returns:
            list[str]: 成功创建的卡片ID列表
        """
        card_ids = []
        for pattern in patterns:
            if pattern.get("confidence", 0) >= 0.3:  # 只转化置信度>=30%的模式
                cid = self.auto_generate_knowledge_card(pattern)
                if cid:
                    card_ids.append(cid)
        if card_ids:
            logger.info("批量生成了 %d 张知识卡片", len(card_ids))
        return card_ids

    def get_cached_patterns(self):
        """获取缓存的经验模式

        Returns:
            list[dict]: 缓存的模式列表
        """
        with self._lock:
            return list(self._patterns_cache.get("patterns", []))

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_log_lines(log_path):
        """收集日志行（支持单文件或目录）

        Args:
            log_path: 日志文件路径或目录路径

        Returns:
            list[str]: 日志行列表
        """
        lines = []
        if not os.path.exists(log_path):
            return lines

        if os.path.isdir(log_path):
            for fname in os.listdir(log_path):
                fpath = os.path.join(log_path, fname)
                if os.path.isfile(fpath) and (fname.endswith(".log") or fname.endswith(".txt")):
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            lines.extend(f.readlines())
                    except IOError as e:
                        logger.warning("读取日志文件失败 [%s]: %s", fpath, e)
        else:
            try:
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines.extend(f.readlines())
            except IOError as e:
                logger.warning("读取日志文件失败 [%s]: %s", log_path, e)

        return lines

    @staticmethod
    def _normalize_log_line(line):
        """标准化日志行，移除时间戳、期号等变化部分

        Args:
            line: 原始日志行

        Returns:
            str: 标准化后的模式字符串，或空字符串
        """
        # 移除常见时间戳格式: 2024-01-15 12:30:45
        text = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2}(\.\d+)?', '', line)
        # 移除日志级别前缀: [INFO], [ERROR], [WARN]
        text = re.sub(r'\[(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\]\s*', '', text)
        # 移除纯数字（期号、行号等）
        text = re.sub(r'\b\d{5,}\b', '', text)
        # 移除文件路径中的数字版本号
        text = re.sub(r'v?\d+\.\d+(?:\.\d+)?', '', text)
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) < 8:
            return ""

        return text


# ===================================================================
# 3. 自适应反馈闭环 (AdaptiveFeedback)
# ===================================================================

class AdaptiveFeedback:
    """自适应反馈闭环 - 增强复盘学习效果

    在基础SmartBrain复盘学习之上，增加:
    1. 命中率的CUSUM统计 - 累积和控制图检测命中率偏移
    2. 命中率异常偏低时触发策略调整建议
    3. 将结果反馈给Watchdog更新监控指标
    4. 发现新模式时通过ExperienceMiner沉淀知识
    """

    def __init__(self, brain=None, watchdog=None, experience_miner=None):
        """初始化自适应反馈

        Args:
            brain: SmartBrain实例（可选）
            watchdog: SystemWatchdog实例（可选）
            experience_miner: ExperienceMiner实例（可选）
        """
        self.brain = brain
        self.watchdog = watchdog
        self.experience_miner = experience_miner
        self._lock = threading.Lock()

        # CUSUM统计: 每个彩种的累积和
        # cusum_high: 检测命中率偏高，cusum_low: 检测命中率偏低
        self._cusum_data = defaultdict(lambda: {
            "cusum_high": 0.0,
            "cusum_low": 0.0,
            "history": [],          # 近期命中率记录
            "drift": 0.0,          # 允许的偏移量
            "threshold": 4.0,      # CUSUM告警阈值（h参数）
        })

        # 策略调整建议缓存
        self._suggestions_cache = defaultdict(list)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def on_review_complete(self, lot, predictions, actual_nums, hits):
        """复盘完成后的增强回调

        比基础 learn_from_review 多做:
        1. 记录命中率的CUSUM统计
        2. 如果命中率异常偏低，触发策略调整建议
        3. 将结果反馈给Watchdog更新监控指标
        4. 如果发现新模式，通过ExperienceMiner沉淀知识

        Args:
            lot: 彩种名
            predictions: 本期所有预测 [{nums, type, scheme, hits}]
            actual_nums: 实际开奖号码列表
            hits: 总命中数
        """
        with self._lock:
            # 1. 调用SmartBrain的基础学习
            if self.brain and hasattr(self.brain, "learn_from_review"):
                try:
                    self.brain.learn_from_review(lot, predictions, actual_nums)
                except Exception as e:
                    logger.error("SmartBrain学习更新失败 [%s]: %s", lot, e)

            # 2. CUSUM统计
            hit_rate = self._calc_hit_rate(predictions, hits)
            cusum_result = self._update_cusum(lot, hit_rate)

            # 3. 命中率异常偏低时触发策略调整
            if cusum_result.get("alert_low"):
                suggestions = self.suggest_strategy_adjustments(lot)
                self._suggestions_cache[lot] = suggestions.get("suggestions", [])
                logger.warning(
                    "[%s] CUSUM检测命中率偏低 (hit_rate=%.2f%%, cusum_low=%.2f)，"
                    "已生成%d条策略建议",
                    lot, hit_rate * 100,
                    cusum_result["cusum_low"],
                    len(self._suggestions_cache[lot])
                )
            elif cusum_result.get("alert_high"):
                logger.info(
                    "[%s] CUSUM检测命中率偏高 (hit_rate=%.2f%%)，当前策略表现良好",
                    lot, hit_rate * 100
                )

            # 4. 反馈给Watchdog
            if self.watchdog and hasattr(self.watchdog, "update_metric"):
                try:
                    self.watchdog.update_metric(
                        "evolution.hit_rate." + lot, hit_rate
                    )
                    self.watchdog.update_metric(
                        "evolution.cusum_high." + lot,
                        cusum_result.get("cusum_high", 0.0)
                    )
                    self.watchdog.update_metric(
                        "evolution.cusum_low." + lot,
                        cusum_result.get("cusum_low", 0.0)
                    )
                except Exception as e:
                    logger.debug("Watchdog反馈失败: %s", e)

    def suggest_strategy_adjustments(self, lot):
        """基于近期表现建议策略调整

        分析近期CUSUM统计和命中率趋势，给出具体调整建议。

        Args:
            lot: 彩种名

        Returns:
            dict: {
                "lot": "福彩3D",
                "suggestions": [
                    {"type": "weight_adjust", "detail": "...", "confidence": 0.8},
                    {"type": "engine_toggle", "detail": "...", "confidence": 0.6}
                ]
            }
        """
        suggestions = []
        cusum = self._cusum_data.get(lot, {})
        history = cusum.get("history", [])

        if len(history) < 3:
            return {"lot": lot, "suggestions": suggestions}

        # 计算近期平均命中率
        recent_avg = sum(history[-5:]) / len(history[-5:])
        older_avg = sum(history[:-5]) / len(history[:-5]) if len(history) > 5 else recent_avg

        # 策略1: 权重调整建议
        if recent_avg < older_avg * 0.6:
            confidence = min(0.95, 0.5 + (older_avg - recent_avg))
            suggestions.append({
                "type": "weight_adjust",
                "detail": "近期命中率显著下降 ({:.1f}% -> {:.1f}%)，"
                          "建议降低表现最差的引擎权重10-20%".format(
                              older_avg * 100, recent_avg * 100
                          ),
                "confidence": round(confidence, 2),
            })

        # 策略2: 引擎开关建议
        cusum_low = cusum.get("cusum_low", 0.0)
        if cusum_low > 3.0:
            suggestions.append({
                "type": "engine_toggle",
                "detail": "CUSUM低位告警 ({:.1f})，建议暂时降低高风险引擎的使用频率".format(
                    cusum_low
                ),
                "confidence": min(0.9, 0.4 + cusum_low * 0.1),
            })

        # 策略3: 号码范围建议
        if recent_avg < 0.15 and len(history) >= 5:
            suggestions.append({
                "type": "range_narrow",
                "detail": "命中率持续偏低，建议缩小选号范围或增加过滤条件",
                "confidence": 0.5,
            })

        # 策略4: 热号窗口调整
        if len(history) >= 10:
            # 检查最近3期 vs 前7期的差异
            if len(history) >= 10:
                very_recent = sum(history[-3:]) / 3
                mid_recent = sum(history[-10:-3]) / 7
                if very_recent > mid_recent * 1.5:
                    suggestions.append({
                        "type": "hot_window_adjust",
                        "detail": "近期命中率上升明显，可扩大热号窗口获取更多信号",
                        "confidence": min(0.7, (very_recent - mid_recent) * 5),
                    })

        # 按置信度排序
        suggestions.sort(key=lambda s: s["confidence"], reverse=True)

        return {"lot": lot, "suggestions": suggestions}

    def get_cusum_status(self, lot):
        """获取指定彩种的CUSUM统计状态

        Args:
            lot: 彩种名

        Returns:
            dict: {cusum_high, cusum_low, history, alert_high, alert_low}
        """
        with self._lock:
            cusum = self._cusum_data.get(lot, {})
            threshold = cusum.get("threshold", 4.0)
            return {
                "cusum_high": round(cusum.get("cusum_high", 0.0), 3),
                "cusum_low": round(cusum.get("cusum_low", 0.0), 3),
                "history": list(cusum.get("history", [])),
                "alert_high": cusum.get("cusum_high", 0.0) > threshold,
                "alert_low": cusum.get("cusum_low", 0.0) > threshold,
                "threshold": threshold,
            }

    def get_suggestions(self, lot):
        """获取缓存的策略调整建议

        Args:
            lot: 彩种名

        Returns:
            list[dict]: 建议列表
        """
        with self._lock:
            return list(self._suggestions_cache.get(lot, []))

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_hit_rate(predictions, total_hits):
        """计算命中率

        Args:
            predictions: 预测列表
            total_hits: 总命中数

        Returns:
            float: 命中率 (0.0-1.0)
        """
        if not predictions:
            return 0.0

        # 统计总预测号码数
        total_nums = 0
        for p in predictions:
            nums_str = p.get("nums", "")
            # 估算号码数
            parts = nums_str.replace("+", ",").replace("[", ",").replace("]", ",").split(",")
            count = sum(1 for part in parts if part.strip().isdigit())
            total_nums += max(1, count)

        if total_nums == 0:
            return 0.0

        return total_hits / total_nums

    def _update_cusum(self, lot, hit_rate):
        """更新CUSUM累积和

        CUSUM (累积和控制图) 算法:
        - S_hi = max(0, S_hi_prev + (hit_rate - target - drift))
        - S_lo = max(0, S_lo_prev + (target - drift - hit_rate))
        - 当 S_hi > h 或 S_lo > h 时触发告警

        Args:
            lot: 彩种名
            hit_rate: 当前命中率

        Returns:
            dict: 更新后的CUSUM状态
        """
        cusum = self._cusum_data[lot]

        # 目标命中率（根据历史自适应）
        history = cusum["history"]
        if len(history) >= 5:
            target = sum(history[-5:]) / 5  # 近5期均值作为目标
        else:
            target = 0.2  # 默认目标20%

        # 允许偏移量（k参数）
        drift = target * 0.05  # 5%的允许偏移

        # 更新累积和
        old_high = cusum["cusum_high"]
        old_low = cusum["cusum_low"]
        cusum["cusum_high"] = max(0.0, old_high + (hit_rate - target - drift))
        cusum["cusum_low"] = max(0.0, old_low + (target - drift - hit_rate))
        cusum["drift"] = drift

        # 记录历史
        history.append(hit_rate)
        # 只保留最近50条
        if len(history) > 50:
            cusum["history"] = history[-50:]

        threshold = cusum["threshold"]
        return {
            "cusum_high": round(cusum["cusum_high"], 3),
            "cusum_low": round(cusum["cusum_low"], 3),
            "target": round(target, 3),
            "drift": round(drift, 3),
            "alert_high": cusum["cusum_high"] > threshold,
            "alert_low": cusum["cusum_low"] > threshold,
        }

    def get_state(self):
        """获取自适应反馈的完整状态（用于持久化）

        Returns:
            dict: 包含cusum和suggestions的状态字典
        """
        with self._lock:
            state = {
                "cusum_data": {},
                "suggestions_cache": {},
            }
            for lot, data in self._cusum_data.items():
                state["cusum_data"][lot] = {
                    "cusum_high": data["cusum_high"],
                    "cusum_low": data["cusum_low"],
                    "history": data["history"][-20:],  # 只保存最近20条
                    "drift": data["drift"],
                    "threshold": data["threshold"],
                }
            for lot, suggs in self._suggestions_cache.items():
                state["suggestions_cache"][lot] = suggs[-5:]  # 只保存最近5条
        return state

    def load_state(self, state):
        """从状态字典恢复（用于从文件加载）

        Args:
            state: 状态字典（来自get_state的输出）
        """
        with self._lock:
            if not state:
                return
            cusum_data = state.get("cusum_data", {})
            for lot, data in cusum_data.items():
                if lot in self._cusum_data:
                    self._cusum_data[lot]["cusum_high"] = data.get("cusum_high", 0.0)
                    self._cusum_data[lot]["cusum_low"] = data.get("cusum_low", 0.0)
                    self._cusum_data[lot]["history"] = data.get("history", [])
                    self._cusum_data[lot]["drift"] = data.get("drift", 0.0)
                    self._cusum_data[lot]["threshold"] = data.get("threshold", 4.0)
            suggs = state.get("suggestions_cache", {})
            for lot, items in suggs.items():
                self._suggestions_cache[lot] = items


# ===================================================================
# 4. 进化管理器 (EvolutionManager)
# ===================================================================

class EvolutionManager:
    """进化管理器 - 统一管理规则引擎+经验挖掘+自适应反馈

    系统的顶层入口，整合RuleEngine、ExperienceMiner和AdaptiveFeedback，
    提供统一的记录、复盘和报告接口。

    使用示例:
        manager = EvolutionManager(data_dir="金水谣数据", brain=brain)
        manager.start()

        # 记录错误事件
        manager.record_and_evolve("连接超时", "network")

        # 复盘完成
        manager.on_review_complete("福彩3D", predictions, actual_nums, hits)

        # 获取报告
        report = manager.get_evolution_report()
    """

    def __init__(self, data_dir="金水谣数据", brain=None, watchdog=None):
        """初始化进化管理器

        Args:
            data_dir: 数据目录路径
            brain: SmartBrain实例（可选，用于自适应反馈）
            watchdog: SystemWatchdog实例（可选，用于监控指标更新）
        """
        self.data_dir = data_dir
        self.rule_file = os.path.join(data_dir, "evolution_rules.json")
        self.state_file = os.path.join(data_dir, "evolution_state.json")

        # 初始化子模块
        self.rule_engine = RuleEngine(rule_file=self.rule_file)
        self.experience_miner = ExperienceMiner(data_dir=data_dir)
        self.adaptive_feedback = AdaptiveFeedback(
            brain=brain,
            watchdog=watchdog,
            experience_miner=self.experience_miner,
        )

        self._started = False
        self._lock = threading.Lock()

        # 统计计数
        self._stats = {
            "total_events": 0,
            "total_reviews": 0,
            "rules_activated": 0,
            "knowledge_cards_created": 0,
            "suggestions_generated": 0,
            "started_at": None,
        }

        logger.info("进化管理器就绪 (data_dir=%s)", data_dir)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self):
        """启动进化引擎

        加载历史状态，准备就绪。后续通过record_and_evolve和on_review_complete
        驱动进化过程。
        """
        with self._lock:
            if self._started:
                logger.info("进化引擎已在运行中")
                return

            # 加载历史状态
            self._load_state()
            self._started = True
            self._stats["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            logger.info(
                "进化引擎已启动 (历史事件: %d, 规则: %d, 知识卡片: %d)",
                self._stats["total_events"],
                len(self.rule_engine.get_active_rules()),
                self._stats["knowledge_cards_created"],
            )

    def stop(self):
        """停止进化引擎，保存状态"""
        with self._lock:
            if not self._started:
                return
            self._started = False
            self.save_state()
            logger.info("进化引擎已停止，状态已保存")

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def record_and_evolve(self, error_message, category, data=None):
        """统一入口: 记录事件 + 检查规则 + 挖掘知识

        这是进化引擎的核心驱动方法，每次系统发生事件时调用。
        会自动完成规则匹配、规则激活、修复动作执行。

        Args:
            error_message: 错误信息字符串
            category: 事件分类
            data: 附带数据（可选）

        Returns:
            dict: 进化处理结果 {
                "event_recorded": True,
                "rule_result": {...},
                "stats": {...}
            }
        """
        with self._lock:
            self._stats["total_events"] += 1

        # 1. 规则引擎处理
        rule_result = self.rule_engine.record_event(error_message, category, data)

        with self._lock:
            if rule_result.get("activated"):
                self._stats["rules_activated"] += 1
            if rule_result.get("new_rule_created"):
                logger.info("进化: 自动创建新规则 (%s)", error_message[:50])

        return {
            "event_recorded": True,
            "rule_result": rule_result,
            "stats": {
                "total_events": self._stats["total_events"],
                "rules_activated": self._stats["rules_activated"],
            }
        }

    def on_review_complete(self, lot, predictions, actual_nums, hits):
        """复盘完成后的进化处理

        整合自适应反馈闭环，在SmartBrain基础学习之上提供增强分析。

        Args:
            lot: 彩种名
            predictions: 本期所有预测 [{nums, type, scheme, hits}]
            actual_nums: 实际开奖号码列表
            hits: 总命中数

        Returns:
            dict: {
                "lot": str,
                "brain_learned": bool,
                "cusum_alert": bool,
                "suggestions": list,
            }
        """
        with self._lock:
            self._stats["total_reviews"] += 1

        # 调用自适应反馈
        self.adaptive_feedback.on_review_complete(
            lot, predictions, actual_nums, hits
        )

        # 检查CUSUM状态
        cusum_status = self.adaptive_feedback.get_cusum_status(lot)
        suggestions = self.adaptive_feedback.get_suggestions(lot)

        with self._lock:
            if suggestions:
                self._stats["suggestions_generated"] += len(suggestions)

        return {
            "lot": lot,
            "brain_learned": self.adaptive_feedback.brain is not None,
            "cusum_alert": cusum_status.get("alert_low", False)
                        or cusum_status.get("alert_high", False),
            "cusum_status": cusum_status,
            "suggestions": suggestions,
        }

    # ------------------------------------------------------------------
    # 报告与持久化
    # ------------------------------------------------------------------

    def get_evolution_report(self):
        """获取进化报告（规则数、知识沉淀数、建议数）

        Returns:
            dict: 完整的进化报告
        """
        rule_stats = self.rule_engine.get_stats()
        cusum_summary = {}

        # 汇总所有彩种的CUSUM状态
        for lot in list(self.adaptive_feedback._cusum_data.keys()):
            cusum_summary[lot] = self.adaptive_feedback.get_cusum_status(lot)

        # 汇总建议
        all_suggestions = {}
        for lot in list(self.adaptive_feedback._suggestions_cache.keys()):
            all_suggestions[lot] = self.adaptive_feedback.get_suggestions(lot)

        return {
            "engine": "金水谣L3自适应进化引擎",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stats": {
                "total_events": self._stats["total_events"],
                "total_reviews": self._stats["total_reviews"],
                "rules_activated": self._stats["rules_activated"],
                "knowledge_cards_created": self._stats["knowledge_cards_created"],
                "suggestions_generated": self._stats["suggestions_generated"],
                "started_at": self._stats.get("started_at"),
                "running": self._started,
            },
            "rule_engine": rule_stats,
            "experience_patterns": len(self.experience_miner.get_cached_patterns()),
            "cusum_status": cusum_summary,
            "active_suggestions": all_suggestions,
        }

    def save_state(self):
        """保存进化状态到文件

        持久化所有子模块的状态，包括:
        - 统计计数
        - CUSUM数据
        - 策略建议缓存
        """
        state = {
            "version": 1,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stats": dict(self._stats),
            "adaptive_feedback": self.adaptive_feedback.get_state(),
        }

        try:
            safe_write_json(self.state_file, state)
            logger.debug("进化状态已保存到 %s", self.state_file)
        except Exception as e:
            logger.error("保存进化状态失败: %s", e, exc_info=True)
            raise

    def _load_state(self):
        """从文件加载进化状态"""
        if not os.path.exists(self.state_file):
            logger.debug("进化状态文件不存在，使用默认状态")
            return

        state = safe_load_json(self.state_file)
        if not state or not isinstance(state, dict):
            return

        # 恢复统计
        saved_stats = state.get("stats", {})
        for key, value in saved_stats.items():
            if key in self._stats:
                self._stats[key] = value

        # 恢复自适应反馈状态
        fb_state = state.get("adaptive_feedback", {})
        if fb_state:
            self.adaptive_feedback.load_state(fb_state)

        logger.debug("进化状态已恢复 (历史事件: %d)", self._stats["total_events"])

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    def mine_and_learn(self, log_path=None, min_occurrences=3, auto_card=True):
        """一键挖掘日志并生成知识卡片

        Args:
            log_path: 日志路径（默认使用data_dir下的log目录）
            min_occurrences: 最小出现次数
            auto_card: 是否自动生成知识卡片

        Returns:
            dict: {patterns_found, cards_created}
        """
        if log_path is None:
            log_path = os.path.join(self.data_dir, "log")

        patterns = self.experience_miner.mine_patterns(
            log_path, min_occurrences=min_occurrences
        )

        cards_created = []
        if auto_card and patterns:
            cards_created = self.experience_miner.batch_generate_cards(patterns)
            with self._lock:
                self._stats["knowledge_cards_created"] += len(cards_created)

        return {
            "patterns_found": len(patterns),
            "cards_created": len(cards_created),
            "card_ids": cards_created,
        }

    def apply_all_fixes(self, context=None):
        """应用所有已激活规则的修复动作

        Args:
            context: 上下文数据

        Returns:
            list[dict]: 修复结果列表
        """
        return self.rule_engine.apply_fixes(context)
