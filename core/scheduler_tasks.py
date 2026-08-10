# -*- coding: utf-8 -*-
"""
金水谣系统 - 通用定时任务调度器（TaskScheduler）

从 core/scheduler.py 拆分（JS-20260810-10 架构整理）：
通用调度基类独立成模块，scheduler.py 重导出保持兼容。

基于 threading.Timer 的轻量级定时任务调度器，不引入额外依赖。
"""
import os
import sys
import time
import logging
import threading
from datetime import datetime

# 日志轮转工具（防止 JSONL 文件无限增长）
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _proj_root not in sys.path:
    sys.path.insert(0, _proj_root)
from utils.log_rotation import check_and_rotate

logger = logging.getLogger(__name__)

# ================================================================
# TaskScheduler - 通用定时任务调度器
# ================================================================

# run_now=True 任务的启动后首跑延迟（秒）：
# 避免开机瞬间所有"启动即补"任务 + 后台审查同时抢占 CPU/网络，
# 统一延后 60 秒错峰，同时保证"开机 1 分钟内即可自动补给"。
_FIRST_RUN_DELAY = 60

class TaskScheduler:
    """基于 threading.Timer 的通用定时任务调度器

    使用 threading.Timer 实现循环调度，每次执行后重新创建 Timer。
    单个任务异常不会影响其他任务的执行。

    Usage:
        scheduler = TaskScheduler()
        scheduler.register("my_task", my_func, interval_minutes=10)
        scheduler.start()
        # ...
        scheduler.stop()
    """

    def __init__(self):
        """初始化调度器"""
        self._tasks = {}          # {name: task_info_dict}
        self._timers = {}         # {name: threading.Timer}
        self._lock = threading.Lock()
        self._started = False
        logger.info("定时任务调度器已初始化")

    # ------------------------------------------------------------------
    # 任务注册/注销
    # ------------------------------------------------------------------

    def register(self, name, func, interval_minutes, enabled=True, run_now=False):
        """注册定时任务

        Args:
            name: 任务名称（唯一标识）
            func: 要执行的函数（无参）
            interval_minutes: 执行间隔（分钟）
            enabled: 是否启用，默认 True
            run_now: 是否在调度器启动后立即首跑（默认延迟 _FIRST_RUN_DELAY 秒，
                后续循环仍按 interval_minutes）。用于"开机即补"型任务
                （自动复盘/数据抓取/探活），避免要等一个完整间隔才第一次执行。
        """
        with self._lock:
            if name in self._tasks:
                logger.warning("任务 '%s' 已存在，将更新配置", name)

            self._tasks[name] = {
                "func": func,
                "interval_minutes": interval_minutes,
                "enabled": enabled,
                "run_now": run_now,
                "last_run": None,
                "next_run": None,
                "run_count": 0,
                "last_error": None,
            }
            logger.info(
                "已注册任务 '%s' (间隔: %d分钟, 启用: %s%s)",
                name, interval_minutes, enabled,
                ", 启动立即首跑" if run_now else "",
            )

            # 如果调度器已启动且任务启用，立即开始调度
            if self._started and enabled:
                self._schedule_task(name)

    def unregister(self, name):
        """注销任务

        停止该任务的定时器并从注册表中移除。

        Args:
            name: 任务名称
        """
        with self._lock:
            self._cancel_timer(name)
            if name in self._tasks:
                del self._tasks[name]
                logger.info("已注销任务 '%s'", name)
            else:
                logger.warning("尝试注销不存在的任务 '%s'", name)

    # ------------------------------------------------------------------
    # 启动/停止
    # ------------------------------------------------------------------

    def start(self):
        """启动所有已注册且已启用的任务

        run_now=True 的任务在启动后延迟 _FIRST_RUN_DELAY 秒优先首跑一次，
        之后循环按各自 interval_minutes 走。

        可重入：多次调用不会创建重复的定时器。
        """
        with self._lock:
            if self._started:
                logger.debug("调度器已在运行中，忽略重复启动")
                return

            self._started = True
            for name, task in self._tasks.items():
                if task["enabled"]:
                    first_delay = _FIRST_RUN_DELAY if task.get("run_now") else None
                    self._schedule_task(name, delay=first_delay)

            enabled_count = sum(1 for t in self._tasks.values() if t["enabled"])
            logger.info(
                "定时任务调度器已启动 (共 %d 个任务, 已启用 %d 个)",
                len(self._tasks), enabled_count,
            )

    def stop(self):
        """停止所有任务

        可重入：多次调用安全。
        """
        with self._lock:
            if not self._started:
                logger.debug("调度器未在运行中，忽略停止请求")
                return

            self._started = False
            for name in list(self._timers.keys()):
                self._cancel_timer(name)

            logger.info("定时任务调度器已停止")

    # ------------------------------------------------------------------
    # 手动触发
    # ------------------------------------------------------------------

    def run_once(self, name):
        """手动触发某个任务执行一次

        Args:
            name: 任务名称

        Returns:
            bool: 是否成功触发
        """
        with self._lock:
            task = self._tasks.get(name)
            if task is None:
                logger.warning("尝试执行不存在的任务 '%s'", name)
                return False

        # 在独立线程中执行，避免阻塞调用方
        thread = threading.Thread(
            target=self._execute_task,
            args=(name,),
            daemon=True,
        )
        thread.setName("scheduler_once_{}".format(name))
        thread.start()
        return True

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def status(self):
        """返回所有任务的状态

        Returns:
            list[dict]: 每个任务的状态信息，包含:
              - name: 任务名称
              - enabled: 是否启用
              - interval_minutes: 执行间隔
              - last_run: 上次执行时间 (ISO 格式字符串或 None)
              - next_run: 下次执行时间 (ISO 格式字符串或 None)
              - run_count: 累计执行次数
              - last_error: 上次错误信息 (或 None)
        """
        with self._lock:
            result = []
            for name, task in self._tasks.items():
                result.append({
                    "name": name,
                    "enabled": task["enabled"],
                    "interval_minutes": task["interval_minutes"],
                    "last_run": task["last_run"],
                    "next_run": task["next_run"],
                    "run_count": task["run_count"],
                    "last_error": task["last_error"],
                })
            return result

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _schedule_task(self, name, delay=None):
        """为指定任务创建并启动 Timer

        必须在持有 _lock 的情况下调用。

        Args:
            name: 任务名称
            delay: 首次延迟（秒）；None=用任务自身 interval_minutes
        """
        task = self._tasks.get(name)
        if task is None or not task["enabled"]:
            return

        # 取消已有的 Timer（防止重复）
        self._cancel_timer(name)

        interval_seconds = task["interval_minutes"] * 60
        if delay is None:
            delay = interval_seconds
        next_run = datetime.now().timestamp() + delay
        task["next_run"] = datetime.fromtimestamp(next_run).isoformat()

        timer = threading.Timer(
            delay,
            self._timer_callback,
            args=(name,),
        )
        timer.setName("scheduler_{}".format(name))
        timer.daemon = True
        self._timers[name] = timer
        timer.start()

    def _cancel_timer(self, name):
        """取消指定任务的 Timer

        必须在持有 _lock 的情况下调用（或由持有锁的方法调用）。

        Args:
            name: 任务名称
        """
        timer = self._timers.pop(name, None)
        if timer is not None:
            timer.cancel()

    def _timer_callback(self, name):
        """Timer 回调：执行任务并重新调度

        Args:
            name: 任务名称
        """
        # 执行任务（在 Timer 线程中）
        self._execute_task(name)

        # 重新调度（需要获取锁）
        with self._lock:
            if self._started:
                task = self._tasks.get(name)
                if task is not None and task["enabled"]:
                    self._schedule_task(name)

    def _execute_task(self, name):
        """执行单个任务（带异常隔离）

        Args:
            name: 任务名称
        """
        with self._lock:
            task = self._tasks.get(name)
            if task is None:
                return

        logger.info("[调度器] 开始执行任务: %s", name)
        t_start = time.time()
        _exec_success = False
        _exec_error = None

        try:
            func = task["func"]
            result = func()

            elapsed = time.time() - t_start
            _exec_success = True
            with self._lock:
                task["last_run"] = datetime.now().isoformat()
                task["run_count"] += 1
                task["last_error"] = None

            logger.info(
                "[调度器] 任务 '%s' 执行完成 (耗时: %.1fs)", name, elapsed,
            )

        except Exception as e:
            elapsed = time.time() - t_start
            _exec_error = str(e)
            with self._lock:
                task["last_run"] = datetime.now().isoformat()
                task["run_count"] += 1
                task["last_error"] = str(e)

            logger.error(
                "[调度器] 任务 '%s' 执行异常 (耗时: %.1fs): %s",
                name, elapsed, e, exc_info=True,
            )

        # 写入 JSONL 执行日志（供前端可视化使用，写入失败不影响任务本身）
        try:
            import json as _json
            _log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "金水谣数据", "log",
            )
            os.makedirs(_log_dir, exist_ok=True)
            _log_path = os.path.join(_log_dir, "scheduler_exec.jsonl")
            check_and_rotate(_log_path, max_size_mb=5)
            _entry = {
                "timestamp": datetime.now().isoformat(),
                "name": name,
                "duration_ms": int(elapsed * 1000),
                "success": _exec_success,
                "error": _exec_error,
            }
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 日志写入失败不影响任务执行
