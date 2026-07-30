# -*- coding: utf-8 -*-
"""
金水谣系统 L1 运行时监控守护模块

在后台持续监控系统健康状态，包括：
- 心跳检测（主线程存活 + tkinter 主循环响应）
- 异常日志监控（err_log 目录错误统计）
- 命中率统计（连续0命中告警）
- 置信度漂移检测（SmartBrain 置信度连续下降）
- CUSUM 偏移检测（命中率系统性偏移）

日志输出: 金水谣数据/log/health_log.jsonl
"""

import os
import sys
import json
import time
import math
import logging
import threading
from collections import defaultdict
from datetime import datetime

from core.log_rotation import rotate_log
from utils.safe_json import safe_load_json

logger = logging.getLogger(__name__)

# 日志文件路径（与 config.py 保持一致）
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "金水谣数据")
_LOG_DIR = os.path.join(_DATA_DIR, "log")
_ERR_LOG_DIR = os.path.join(_LOG_DIR, "err_log")
_HEALTH_LOG_FILE = os.path.join(_LOG_DIR, "health_log.jsonl")

for _d in [_LOG_DIR, _ERR_LOG_DIR]:
    os.makedirs(_d, exist_ok=True)


# ================================================================
# 结构化健康日志记录器
# ================================================================

class HealthLogger:
    """结构化健康日志记录器

    每条日志以 JSON Lines 格式写入 health_log.jsonl，
    包含 timestamp、level、category、message、data 五个字段。
    """

    LEVEL_INFO = "INFO"
    LEVEL_WARN = "WARN"
    LEVEL_CRITICAL = "CRITICAL"

    CATEGORY_HEARTBEAT = "heartbeat"
    CATEGORY_ERROR_MONITOR = "error_monitor"
    CATEGORY_HIT_RATE = "hit_rate"
    CATEGORY_CONFIDENCE = "confidence"
    CATEGORY_CUSUM = "cusum"

    def __init__(self, log_file=_HEALTH_LOG_FILE):
        """初始化健康日志记录器

        Args:
            log_file: 日志文件路径，默认 金水谣数据/log/health_log.jsonl
        """
        self.log_file = log_file
        self._lock = threading.Lock()

        os.makedirs(os.path.dirname(log_file), exist_ok=True)

    def log(self, level, category, message, data=None):
        """写入一条结构化健康日志

        Args:
            level: 日志级别 (INFO / WARN / CRITICAL)
            category: 监控类别 (heartbeat / error_monitor / hit_rate / confidence / cusum)
            message: 描述信息
            data: 附加数据字典，可选
        """
        if data is None:
            data = {}

        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "category": category,
            "message": message,
            "data": data,
        }

        line = json.dumps(entry, ensure_ascii=False)

        with self._lock:
            try:
                # 写入前检查日志轮转
                rotate_log(self.log_file, max_size_mb=5, keep_backups=3)
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except Exception as e:
                # 日志写入失败不能静默，必须上报
                logger.error("健康日志写入失败: %s", e, exc_info=True)

        # 同时通过标准 logging 输出
        log_func = logger.info
        if level == self.LEVEL_WARN:
            log_func = logger.warning
        elif level == self.LEVEL_CRITICAL:
            log_func = logger.critical
        log_func("[%s][%s] %s", category, level, message)


# ================================================================
# CUSUM 偏移检测器
# ================================================================

class CUSUMDetector:
    """CUSUM 累积和偏移检测器

    用于检测命中率的系统性偏移（正偏移或负偏移）。
    当累积偏移超过阈值（正负2倍标准差）时触发告警。
    """

    def __init__(self, window=20, threshold_sigma=2.0):
        """初始化 CUSUM 检测器

        Args:
            window: 滑动窗口大小，用于计算基准均值和标准差
            threshold_sigma: 告警阈值，单位为标准差倍数，默认 2.0
        """
        self.window = window
        self.threshold_sigma = threshold_sigma

        # 各彩种的 CUSUM 状态
        self._state = {}  # {彩种: {"values": [], "s_high": 0.0, "s_low": 0.0}}

    def update(self, lot, hit_rate):
        """更新一个彩种的命中率数据

        Args:
            lot: 彩种名称
            hit_rate: 当期命中率 (0.0 - 1.0)

        Returns:
            dict or None: 检测到偏移时返回告警信息，否则返回 None
        """
        if lot not in self._state:
            self._state[lot] = {
                "values": [],
                "s_high": 0.0,
                "s_low": 0.0,
            }

        state = self._state[lot]
        values = state["values"]
        values.append(hit_rate)

        # 限制窗口长度
        if len(values) > self.window * 2:
            values = values[-self.window:]

        # 数据不足以计算基准
        if len(values) < self.window:
            return None

        # 使用最近 window 个值计算基准均值和标准差
        baseline = values[-self.window:]
        mean_val = sum(baseline) / len(baseline)
        variance = sum((v - mean_val) ** 2 for v in baseline) / len(baseline)
        std_val = math.sqrt(variance) if variance > 0 else 0.001

        # CUSUM 更新
        # 允许的偏移量 = 0.5 * std
        k = 0.5 * std_val
        threshold = self.threshold_sigma * std_val

        # 正偏移（命中率上升）
        state["s_high"] = max(0, state["s_high"] + (hit_rate - mean_val - k))
        # 负偏移（命中率下降）
        state["s_low"] = max(0, state["s_low"] + (mean_val - hit_rate - k))

        alert = None
        if state["s_high"] > threshold:
            alert = {
                "direction": "positive",
                "cusum_value": round(state["s_high"], 4),
                "threshold": round(threshold, 4),
                "current_hit_rate": hit_rate,
                "baseline_mean": round(mean_val, 4),
                "baseline_std": round(std_val, 4),
                "message": "命中率出现正偏移（系统性上升），CUSUM超过阈值",
            }
        elif state["s_low"] > threshold:
            alert = {
                "direction": "negative",
                "cusum_value": round(state["s_low"], 4),
                "threshold": round(threshold, 4),
                "current_hit_rate": hit_rate,
                "baseline_mean": round(mean_val, 4),
                "baseline_std": round(std_val, 4),
                "message": "命中率出现负偏移（系统性下降），CUSUM超过阈值",
            }

        return alert

    def reset(self, lot):
        """重置某个彩种的 CUSUM 状态

        Args:
            lot: 彩种名称
        """
        if lot in self._state:
            self._state[lot]["s_high"] = 0.0
            self._state[lot]["s_low"] = 0.0


# ================================================================
# 系统守护进程
# ================================================================

class SystemWatchdog:
    """金水谣系统 L1 运行时监控守护模块

    在后台线程中持续监控系统健康状态，检测心跳、异常日志、
    命中率异常、置信度漂移和 CUSUM 偏移等指标。

    Usage:
        watchdog = SystemWatchdog(app_reference=app, interval=30)
        watchdog.register_alert_callback(my_callback)
        watchdog.start()

        # ... 主程序运行 ...

        watchdog.stop()
    """

    def __init__(self, app_reference=None, interval=30):
        """初始化守护进程

        Args:
            app_reference: App 实例引用（用于获取系统状态）
            interval: 心跳检测间隔（秒），默认 30 秒
        """
        self.app = app_reference
        self.interval = interval

        # 健康日志记录器
        self.health_logger = HealthLogger()

        # CUSUM 检测器
        self.cusum_detector = CUSUMDetector()

        # 线程控制
        self._thread = None
        self._running = False
        self._lock = threading.Lock()

        # 告警回调列表
        self._alert_callbacks = []

        # 心跳检测状态
        self._heartbeat_fail_count = 0
        self._max_heartbeat_fails = 5  # 10秒内无响应才报警（网络抓取期间正常阻塞）

        # 错误监控状态
        self._error_count_cache = {}  # {错误签名: 连续次数}
        self._max_error_repeat = 5

        # 命中率监控状态
        self._zero_hit_streak = defaultdict(int)  # {彩种: 连续0命中次数}
        self._max_zero_hit_streak = 5

        # 置信度监控状态
        self._confidence_decline_count = {}  # {彩种: 连续下降次数}
        self._max_confidence_decline = 3
        self._last_confidence = {}  # {彩种: 上次置信度值}

        # 响应标志（用于 tkinter 主循环检测）
        self._response_flag = False
        self._flag_lock = threading.Lock()

        logger.info("系统守护进程初始化完成 (间隔: %ds)", interval)

    # --------------------------------------------------------
    # 心跳响应标志（供 App 主线程定期设置）
    # --------------------------------------------------------

    def set_alive_flag(self):
        """设置响应标志，表示主线程仍然存活

        App 的 tkinter 主循环应定期调用此方法以证明其响应性。
        """
        with self._flag_lock:
            self._response_flag = True

    def _check_response_flag(self):
        """检查并重置响应标志

        Returns:
            bool: 如果自上次检查以来标志被设置过，返回 True
        """
        with self._flag_lock:
            if self._response_flag:
                self._response_flag = False
                return True
            return False

    # --------------------------------------------------------
    # 告警回调
    # --------------------------------------------------------

    def register_alert_callback(self, callback):
        """注册告警回调函数

        当检测到异常时调用回调。
        回调签名: callback(level, category, message, data)

        Args:
            callback: 回调函数，接受四个参数 (level, category, message, data)
        """
        with self._lock:
            self._alert_callbacks.append(callback)
        logger.debug("已注册告警回调: %s", getattr(callback, '__name__', repr(callback)))

    def _fire_alert(self, level, category, message, data=None):
        """触发告警，通知所有已注册的回调

        Args:
            level: 告警级别 (INFO / WARN / CRITICAL)
            category: 告警类别
            message: 告警描述
            data: 附加数据，可选
        """
        if data is None:
            data = {}

        # 写入健康日志
        self.health_logger.log(level, category, message, data)

        # 通知回调
        with self._lock:
            callbacks = list(self._alert_callbacks)
        for cb in callbacks:
            try:
                cb(level, category, message, data)
            except Exception as e:
                logger.error("告警回调执行异常: %s", e, exc_info=True)

    # --------------------------------------------------------
    # 启动/停止
    # --------------------------------------------------------

    def start(self):
        """启动守护线程"""
        if self._running:
            logger.warning("守护线程已在运行中")
            return

        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.setName("SystemWatchdog")
        self._thread.start()
        logger.info("系统守护线程已启动")

    def stop(self):
        """停止守护线程"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("系统守护线程已停止")

    # --------------------------------------------------------
    # 主监控循环
    # --------------------------------------------------------

    def _watch_loop(self):
        """守护线程主循环"""
        logger.debug("守护循环开始")
        while self._running:
            try:
                # 1. 心跳检测
                self._check_heartbeat()

                # 2. 异常日志监控
                self._check_error_logs()

                # 3. 命中率统计
                self._check_hit_rates()

                # 4. 置信度漂移检测
                self._check_confidence_drift()

                # 5. CUSUM 偏移检测
                self._check_cusum_shift()

            except Exception as e:
                logger.error("守护循环执行异常: %s", e, exc_info=True)
                self._fire_alert(
                    HealthLogger.LEVEL_WARN,
                    HealthLogger.CATEGORY_HEARTBEAT,
                    "守护循环执行异常: {}".format(str(e)),
                    {"exception": str(e)},
                )

            # 等待下一个周期
            self._wait_for_next_cycle()

        logger.debug("守护循环结束")

    def _wait_for_next_cycle(self):
        """等待下一个监控周期，支持提前唤醒退出"""
        for _ in range(int(self.interval * 10)):
            if not self._running:
                return
            time.sleep(0.1)

    # --------------------------------------------------------
    # 1. 心跳检测
    # --------------------------------------------------------

    def _check_heartbeat(self):
        """检查主线程和 tkinter 主循环是否存活

        - 检查主线程是否存活
        - 检查响应标志是否被定期设置
        - 连续 3 次无响应 → CRITICAL 告警
        """
        main_thread = threading.main_thread()

        # 检查主线程存活
        if not main_thread.is_alive():
            self._fire_alert(
                HealthLogger.LEVEL_CRITICAL,
                HealthLogger.CATEGORY_HEARTBEAT,
                "主线程已终止",
                {"thread": "main", "alive": False},
            )
            return

        # 检查 tkinter 响应标志
        if self._check_response_flag():
            # 主线程正常响应，重置失败计数
            if self._heartbeat_fail_count > 0:
                self.health_logger.log(
                    HealthLogger.LEVEL_INFO,
                    HealthLogger.CATEGORY_HEARTBEAT,
                    "心跳恢复正常 (之前连续失败 {} 次)".format(self._heartbeat_fail_count),
                )
            self._heartbeat_fail_count = 0
        else:
            self._heartbeat_fail_count += 1
            if self._heartbeat_fail_count == self._max_heartbeat_fails:
                self._fire_alert(
                    HealthLogger.LEVEL_WARN,
                    HealthLogger.CATEGORY_HEARTBEAT,
                    "主线程连续 {} 次无响应（可能在进行网络抓取或计算密集操作）".format(self._heartbeat_fail_count),
                    {"fail_count": self._heartbeat_fail_count},
                )

    # --------------------------------------------------------
    # 2. 异常日志监控
    # --------------------------------------------------------

    def _check_error_logs(self):
        """监控 err_log 目录下的错误日志

        - 扫描最近修改的日志文件
        - 统计错误数量和类型
        - 同一错误连续出现 5 次 → 触发告警
        """
        if not os.path.isdir(_ERR_LOG_DIR):
            return

        # 只监控当天的日志文件（忽略历史日志）
        today_log = os.path.join(_ERR_LOG_DIR, f"error_{time.strftime('%Y-%m-%d')}.log")
        if not os.path.isfile(today_log):
            return

        try:
            log_files = [today_log]
        except Exception as e:
            logger.error("扫描错误日志目录失败: %s", e)
            return

        # 只读取最新的日志文件
        if not log_files:
            return

        latest_file = os.path.join(_ERR_LOG_DIR, log_files[0])

        try:
            # 读取最后 100 行
            with open(latest_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            lines = lines[-100:] if len(lines) > 100 else lines
        except Exception as e:
            logger.error("读取错误日志失败: %s", e)
            return

        # 提取错误信息
        error_signatures = []
        for line in lines:
            line = line.strip()
            if "ERROR" in line and len(line) > 10:
                # 提取错误签名：去掉时间戳，保留错误内容
                signature = self._extract_error_signature(line)
                if signature:
                    error_signatures.append(signature)

        if not error_signatures:
            return

        # 统计连续重复次数
        current_errors = defaultdict(int)
        for sig in error_signatures:
            current_errors[sig] += 1

        # 检查是否有错误超过阈值
        total_errors = len(error_signatures)
        repeated_errors = {
            sig: count for sig, count in current_errors.items()
            if count >= self._max_error_repeat
        }

        if repeated_errors:
            for sig, count in repeated_errors.items():
                # 去重：同一错误签名只告警一次
                if sig not in self._error_count_cache:
                    self._error_count_cache[sig] = True
                    self._fire_alert(
                        HealthLogger.LEVEL_WARN,
                        HealthLogger.CATEGORY_ERROR_MONITOR,
                        "错误 '{}' 连续出现 {} 次".format(sig, count),
                        {
                            "signature": sig,
                            "count": count,
                            "threshold": self._max_error_repeat,
                            "total_errors_in_file": total_errors,
                            "file": log_files[0],
                        },
                    )

        # 记录常规统计
        self.health_logger.log(
            HealthLogger.LEVEL_INFO,
            HealthLogger.CATEGORY_ERROR_MONITOR,
            "错误日志扫描完成 (文件: {}, 错误数: {}, 类型数: {})".format(
                log_files[0], total_errors, len(current_errors)
            ),
            {"total": total_errors, "types": len(current_errors)},
        )

    @staticmethod
    def _extract_error_signature(line):
        """从错误日志行中提取错误签名

        去掉时间戳前缀，提取核心错误信息。

        Args:
            line: 日志行

        Returns:
            str: 错误签名
        """
        # 格式: [2026-06-13 00:23:37] ERROR: xxx
        try:
            # 去掉 [时间戳] 前缀
            if line.startswith('['):
                end_bracket = line.find(']')
                if end_bracket > 0:
                    sig = line[end_bracket + 1:].strip()
                    # 去掉 "ERROR:" 前缀
                    if sig.upper().startswith("ERROR:"):
                        sig = sig[6:].strip()
                    return sig
        except Exception as e:
            logger.debug("提取错误签名失败: %s", e)

        return line.strip()[:100]  # 截断超长内容

    # --------------------------------------------------------
    # 3. 命中率统计
    # --------------------------------------------------------

    def _check_hit_rates(self):
        """追踪各彩种的连续0命中次数

        - 从 predictions.json 获取最近预测结果
        - 检查各彩种是否有连续多期0命中
        - 连续 5 期 0 命中 → 触发策略偏差告警
        """
        pred_file = os.path.join(_DATA_DIR, "predictions.json")
        if not os.path.isfile(pred_file):
            return

        try:
            preds = safe_load_json(pred_file, default=None)
        except Exception as e:
            logger.error("读取预测数据失败: %s", e)
            return

        if not preds:
            return

        # 按彩种和期号分组，检查最近的命中情况
        lot_periods = defaultdict(list)
        for p in preds:
            if p.get('reviewed') and p.get('hits') is not None:
                lot = p.get('lot', '')
                lot_periods[lot].append(p)

        alerts_fired = []

        for lot, records in lot_periods.items():
            # 按期号排序（最新的在前）
            records.sort(key=lambda x: x.get('period', ''), reverse=True)

            # 计算连续0命中次数
            streak = 0
            for r in records:
                if r.get('hits', 0) == 0:
                    streak += 1
                else:
                    break

            self._zero_hit_streak[lot] = streak

            if streak >= self._max_zero_hit_streak:
                alerts_fired.append(lot)
                self._fire_alert(
                    HealthLogger.LEVEL_WARN,
                    HealthLogger.CATEGORY_HIT_RATE,
                    "{} 连续 {} 期0命中，策略可能存在偏差".format(lot, streak),
                    {
                        "lottery": lot,
                        "zero_hit_streak": streak,
                        "threshold": self._max_zero_hit_streak,
                    },
                )

        # 记录整体命中率统计
        summary = {}
        for lot, streak in self._zero_hit_streak.items():
            summary[lot] = {"zero_hit_streak": streak}

        if summary:
            self.health_logger.log(
                HealthLogger.LEVEL_INFO,
                HealthLogger.CATEGORY_HIT_RATE,
                "命中率统计完成 (监控彩种数: {})".format(len(summary)),
                summary,
            )

    # --------------------------------------------------------
    # 4. 置信度漂移检测
    # --------------------------------------------------------

    def _check_confidence_drift(self):
        """监控 SmartBrain 的置信度分数

        - 获取最近的置信度历史
        - 使用滑动窗口（最近10期）
        - 置信度连续下降 3 次 → 记录告警
        """
        # 尝试从 App 获取 SmartBrain 引用
        brain = self._get_smart_brain()
        if brain is None:
            return

        conf_history = brain.state.get("confidence_history", [])
        if not conf_history:
            return

        # 按彩种分组
        lot_confidence = defaultdict(list)
        for entry in conf_history:
            lot = entry.get("lot", "")
            if lot:
                lot_confidence[lot].append(entry.get("confidence", 0.5))

        window = 10

        for lot, values in lot_confidence.items():
            # 取最近 window 个值
            recent = values[-window:] if len(values) >= window else values
            if len(recent) < 3:
                continue

            # 计算连续下降次数
            decline = 0
            for i in range(len(recent) - 1, 0, -1):
                if recent[i] < recent[i - 1]:
                    decline += 1
                else:
                    break

            self._confidence_decline_count[lot] = decline
            last_conf = recent[-1]
            self._last_confidence[lot] = last_conf

            if decline >= self._max_confidence_decline:
                self._fire_alert(
                    HealthLogger.LEVEL_WARN,
                    HealthLogger.CATEGORY_CONFIDENCE,
                    "{} 置信度连续下降 {} 次 (当前: {:.1f}%)".format(
                        lot, decline, last_conf * 100
                    ),
                    {
                        "lottery": lot,
                        "decline_count": decline,
                        "threshold": self._max_confidence_decline,
                        "current_confidence": round(last_conf, 4),
                        "recent_values": [round(v, 4) for v in recent],
                    },
                )

    # --------------------------------------------------------
    # 5. CUSUM 偏移检测
    # --------------------------------------------------------

    def _check_cusum_shift(self):
        """检测命中率的系统性偏移

        - 基于各彩种的命中率历史计算 CUSUM
        - 正偏移（命中率上升）和负偏移（命中率下降）
        - 超过阈值（正负2倍标准差）时告警
        """
        pred_file = os.path.join(_DATA_DIR, "predictions.json")
        if not os.path.isfile(pred_file):
            return

        try:
            preds = safe_load_json(pred_file, default=None)
        except Exception as e:
            logger.error("读取预测数据失败 (CUSUM): %s", e)
            return

        if not preds:
            return

        # 按彩种分期的命中率
        lot_period_hits = defaultdict(lambda: defaultdict(list))
        for p in preds:
            if p.get('reviewed') and p.get('hits') is not None:
                lot = p.get('lot', '')
                period = p.get('period', '')
                lot_period_hits[lot][period].append(p.get('hits', 0))

        for lot, periods in lot_period_hits.items():
            # 每期的平均命中率（归一化到 0-1）
            # 这里简单地用 hits > 0 的比例作为命中率指标
            # 更精确的做法取决于具体数据结构
            sorted_periods = sorted(periods.keys())
            period_rates = []
            for per in sorted_periods:
                hits_list = periods[per]
                if hits_list:
                    # 有命中的比例
                    hit_count = sum(1 for h in hits_list if h > 0)
                    rate = hit_count / len(hits_list)
                    period_rates.append(rate)

            # 用最新一期的命中率更新 CUSUM
            if period_rates:
                latest_rate = period_rates[-1]
                alert = self.cusum_detector.update(lot, latest_rate)

                if alert:
                    level = HealthLogger.LEVEL_WARN
                    direction_text = "上升" if alert["direction"] == "positive" else "下降"
                    self._fire_alert(
                        level,
                        HealthLogger.CATEGORY_CUSUM,
                        "{} 命中率系统{}偏移 (CUSUM={:.4f}, 阈值={:.4f})".format(
                            lot, direction_text,
                            alert["cusum_value"], alert["threshold"]
                        ),
                        alert,
                    )

                    # 触发后重置 CUSUM 状态
                    self.cusum_detector.reset(lot)

    # --------------------------------------------------------
    # 辅助方法
    # --------------------------------------------------------

    def _get_smart_brain(self):
        """获取 SmartBrain 实例引用

        优先从 App 引用获取，回退到直接实例化。

        Returns:
            SmartBrain or None
        """
        # 从 App 引用获取
        if self.app is not None:
            brain = getattr(self.app, 'brain', None)
            if brain is not None:
                return brain

        # 回退：尝试直接加载（带实例缓存）
        if hasattr(self, '_brain') and self._brain is not None:
            return self._brain
        try:
            from engines.smart_brain import SmartBrain
            self._brain = SmartBrain(data_dir=_DATA_DIR)
            return self._brain
        except Exception as e:
            logger.debug("无法获取 SmartBrain 引用: %s", e)
            return None

    # --------------------------------------------------------
    # 状态查询
    # --------------------------------------------------------

    def get_status(self):
        """获取当前监控状态摘要

        Returns:
            dict: 包含各项监控指标的当前状态
        """
        with self._lock:
            status = {
                "running": self._running,
                "interval": self.interval,
                "heartbeat": {
                    "fail_count": self._heartbeat_fail_count,
                    "max_fails": self._max_heartbeat_fails,
                    "status": "正常" if self._heartbeat_fail_count == 0
                              else ("警告" if self._heartbeat_fail_count < self._max_heartbeat_fails
                                    else "异常"),
                },
                "error_monitor": {
                    "cached_errors": len(self._error_count_cache),
                    "threshold": self._max_error_repeat,
                },
                "hit_rate": {
                    "zero_hit_streaks": dict(self._zero_hit_streak),
                    "threshold": self._max_zero_hit_streak,
                },
                "confidence": {
                    "decline_counts": dict(self._confidence_decline_count),
                    "last_values": {k: round(v, 4) for k, v in self._last_confidence.items()},
                    "threshold": self._max_confidence_decline,
                },
                "alert_callbacks_count": len(self._alert_callbacks),
                "last_check_time": datetime.now().isoformat(),
            }
            return status

    # --------------------------------------------------------
    # 反馈给 SmartBrain
    # --------------------------------------------------------

    def report_to_brain(self):
        """将监控发现反馈给 SmartBrain 学习

        收集当前监控状态摘要，尝试将数据写入 SmartBrain 的学习状态中，
        以便 SmartBrain 在后续预测中考虑系统健康状况。

        Returns:
            bool: 是否成功反馈
        """
        status = self.get_status()
        brain = self._get_smart_brain()
        if brain is None:
            logger.warning("无法反馈给 SmartBrain: 引用不可用")
            return False

        try:
            # 将监控摘要附加到 SmartBrain 状态中
            watchdog_report = {
                "timestamp": datetime.now().isoformat(),
                "heartbeat_status": status["heartbeat"]["status"],
                "zero_hit_streaks": status["hit_rate"]["zero_hit_streaks"],
                "confidence_declines": status["confidence"]["decline_counts"],
            }

            if "watchdog_reports" not in brain.state:
                brain.state["watchdog_reports"] = []
            brain.state["watchdog_reports"].append(watchdog_report)

            # 只保留最近 50 条报告
            if len(brain.state["watchdog_reports"]) > 50:
                brain.state["watchdog_reports"] = brain.state["watchdog_reports"][-50:]

            brain._save_state()
            logger.info("已将监控报告反馈给 SmartBrain")
            return True

        except Exception as e:
            logger.error("反馈给 SmartBrain 失败: %s", e, exc_info=True)
            return False
