# -*- coding: utf-8 -*-
"""跨子系统信号关联框架

核心能力：
  1. SignalBus — 事件总线，子系统间发布/订阅信号
  2. CrossDomainAnalyzer — 跨域分析器，检测子系统间关联
  3. Signal — 标准信号结构

使用场景：
  - A股大盘趋势 → 彩票资金配置策略调整
  - 彩票冷热号迁移 → 相关股票板块异动检测
  - 足彩赛事结果 → 彩票/股票情绪联动

设计原则：
  - 松耦合：子系统通过 SignalBus 通信，不直接引用对方
  - 异步：信号发布不阻塞发布方
  - 隔离：每个子系统只收到自己订阅的信号
"""
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Callable, Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class Signal:
    """标准信号对象"""

    def __init__(self, signal_type: str, source_domain: str, data: dict,
                 timestamp: Optional[str] = None, ttl: int = 3600):
        """
        Args:
            signal_type: 信号类型，如 "trend_change", "hot_number_shift", "match_result"
            source_domain: 发送方子系统标识，如 "stock", "lottery", "football"
            data: 信号数据字典
            timestamp: 时间戳（默认当前时间）
            ttl: 生存时间（秒），过期信号自动丢弃
        """
        self.signal_type = signal_type
        self.source_domain = source_domain
        self.data = data
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ttl = ttl
        import uuid
        self.id = f"{source_domain}_{signal_type}_{uuid.uuid4().hex[:8]}"

    def is_expired(self) -> bool:
        """检查信号是否过期"""
        try:
            sig_time = datetime.strptime(self.timestamp, "%Y-%m-%d %H:%M:%S")
            elapsed = (datetime.now() - sig_time).total_seconds()
            return elapsed > self.ttl
        except Exception:
            return False

    def __repr__(self):
        return f"Signal({self.signal_type}, from={self.source_domain}, data_keys={list(self.data.keys())})"


class SignalBus:
    """跨子系统信号总线

    单例模式，所有子系统共享同一个总线。
    支持发布/订阅/查询信号。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._subscribers = defaultdict(list)
            cls._instance._history = []
            cls._instance._max_history = 500
        return cls._instance

    def subscribe(self, signal_type: str, subscriber_domain: str,
                  callback: Callable[[Signal], None]):
        """订阅信号

        Args:
            signal_type: 信号类型（支持通配符 "*" 订阅所有）
            subscriber_domain: 订阅方子系统标识
            callback: 回调函数
        """
        self._subscribers[signal_type].append({
            "domain": subscriber_domain,
            "callback": callback,
            "registered": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        logger.info("信号订阅: %s[%s] → %s", subscriber_domain, signal_type, callback.__name__)

    def unsubscribe(self, signal_type: str, subscriber_domain: str):
        """取消订阅"""
        self._subscribers[signal_type] = [
            s for s in self._subscribers[signal_type]
            if s["domain"] != subscriber_domain
        ]

    def publish(self, signal: Signal):
        """发布信号

        信号会分发给匹配的订阅者（包括通配符订阅者）。
        过期信号不分发。
        """
        if signal.is_expired():
            logger.debug("信号已过期，丢弃: %s", signal.id)
            return

        # 保存到历史
        self._history.append(signal)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # 分发给精确匹配的订阅者
        delivered = 0
        for sub in self._subscribers.get(signal.signal_type, []):
            try:
                sub["callback"](signal)
                delivered += 1
            except Exception as e:
                logger.error("信号分发失败 %s → %s: %s", signal.id, sub["domain"], e)

        # 分发给通配符订阅者
        for sub in self._subscribers.get("*", []):
            try:
                sub["callback"](signal)
                delivered += 1
            except Exception as e:
                logger.error("通配信号分发失败 %s → %s: %s", signal.id, sub["domain"], e)

        logger.debug("信号已发布: %s, 分发 %d 个订阅者", signal.id, delivered)

    def query(self, signal_type: Optional[str] = None, source_domain: Optional[str] = None,
              since: Optional[str] = None, limit: int = 20) -> List[Signal]:
        """查询信号历史

        Args:
            signal_type: 信号类型过滤（None=全部）
            source_domain: 来源子系统过滤（None=全部）
            since: 起始时间
            limit: 最大返回数
        """
        results = []
        for sig in reversed(self._history):  # 最新的在前
            if signal_type and sig.signal_type != signal_type:
                continue
            if source_domain and sig.source_domain != source_domain:
                continue
            if since and sig.timestamp < since:
                continue
            if sig.is_expired():
                continue
            results.append(sig)
            if len(results) >= limit:
                break
        return results

    def stats(self) -> dict:
        """总线统计"""
        return {
            "total_subscribers": sum(len(v) for v in self._subscribers.values()),
            "signal_types": list(self._subscribers.keys()),
            "history_size": len(self._history),
            "recent_signals": [
                {"type": s.signal_type, "from": s.source_domain, "time": s.timestamp}
                for s in self._history[-10:]
            ],
        }

    @classmethod
    def reset(cls):
        """重置单例（仅测试用）"""
        cls._instance = None


class CrossDomainAnalyzer:
    """跨域分析器

    检测不同子系统间的关联模式。
    """

    # 预定义的跨域关联规则
    CROSS_DOMAIN_RULES = [
        {
            "id": "stock_trend_lottery_budget",
            "name": "A股趋势→彩票预算",
            "description": "当A股大盘连续下跌时，降低彩票投入预算；上涨时可适当增加",
            "trigger_signal": "stock.trend_change",
            "action_domain": "lottery",
            "condition": lambda data: data.get("direction") == "down" and data.get("strength", 0) > 60,
            "action": "adjust_budget",
            "action_params": {"factor": 0.7},  # 降预算到70%
        },
        {
            "id": "lottery_hot_stock_sector",
            "name": "彩票热号→板块异动",
            "description": "彩票高频号码对应数字相关板块（如3/7/8对应幸运数字概念）",
            "trigger_signal": "lottery.hot_number_shift",
            "action_domain": "stock",
            "condition": lambda data: data.get("shift_magnitude", 0) > 2,
            "action": "watch_sectors",
            "action_params": {"sectors": ["幸运数字", "数字娱乐"]},
        },
        {
            "id": "football_result_lottery_emotion",
            "name": "足彩结果→彩票情绪",
            "description": "足彩大奖/冷门结果可能影响彩票投注热度",
            "trigger_signal": "football.match_result",
            "action_domain": "lottery",
            "condition": lambda data: data.get("upset", False),
            "action": "emotion_alert",
            "action_params": {"alert": "足彩冷门，彩票投注热度可能上升"},
        },
    ]

    def __init__(self, signal_bus: Optional[SignalBus] = None):
        self.bus = signal_bus or SignalBus()
        self._active_rules = list(self.CROSS_DOMAIN_RULES)
        self._action_log = []

    def analyze_signal(self, signal: Signal) -> List[dict]:
        """分析信号，返回触发的跨域动作

        Args:
            signal: 收到的信号

        Returns:
            list: 触发的动作列表 [{"rule_id", "action", "params", "target_domain"}, ...]
        """
        actions = []

        for rule in self._active_rules:
            if signal.signal_type != rule["trigger_signal"]:
                continue
            if signal.source_domain == rule["action_domain"]:
                continue  # 不处理自己发自己的信号

            try:
                if rule["condition"](signal.data):
                    action = {
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        "action": rule["action"],
                        "params": rule["action_params"],
                        "target_domain": rule["action_domain"],
                        "trigger_signal": signal.id,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    actions.append(action)
                    self._action_log.append(action)
                    logger.info("跨域动作触发: %s → %s (%s)",
                                rule["name"], rule["action_domain"], rule["action"])
            except Exception as e:
                logger.error("跨域规则执行失败 %s: %s", rule["id"], e)

        return actions

    def register_rule(self, rule: dict):
        """注册自定义跨域规则

        Args:
            rule: 规则字典，包含 id, name, description, trigger_signal,
                  action_domain, condition(callable), action, action_params
        """
        self._active_rules.append(rule)
        logger.info("跨域规则已注册: %s", rule.get("id", rule.get("name")))

    def get_action_log(self, limit: int = 20) -> List[dict]:
        """获取动作日志"""
        return self._action_log[-limit:]

    def status(self) -> dict:
        """分析器状态"""
        return {
            "active_rules": len(self._active_rules),
            "rules": [{"id": r["id"], "name": r["name"], "trigger": r["trigger_signal"],
                      "target": r["action_domain"]} for r in self._active_rules],
            "action_log_size": len(self._action_log),
        }
