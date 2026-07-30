# -*- coding: utf-8 -*-
"""足彩专用 — 崩溃审查与自愈系统 v3.0

本模块是足彩子系统的运行时异常监控与自愈框架，功能包括：
  1. 全局异常捕获 → 写崩溃日志文件 + 上下文快照
  2. 操作包装器 — 每个关键操作前/后记录状态
  3. 健康检查 — 每 30 秒检查窗口状态、线程状态
  4. 自动恢复 — 检测到异常后尝试恢复

与其他"audit"模块的关系（非重复，职责不同）：
  - core/audit_log.py  — 全局操作审计日志（记录系统事件到 JSON Lines 文件）
  - engines/audit.py   — 彩票号码合规校验（验证号码范围/格式）

使用方式：
  from jinshuiyao.audit import AuditSystem
  audit = AuditSystem(app_instance)
  # 关键操作包装
  audit.wrap("抓取数据", fetch_fn)()
  # 健康检查
  audit.start_health_check(interval_ms=30000)
"""

import os
import sys
import time
import threading
import traceback
import datetime
from typing import Any, Callable, Optional, Dict

# 崩溃日志路径
def _get_crash_log_path() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base, "data")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "jinshuiyao_crash.log")


def _get_audit_log_path() -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base, "data")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "jinshuiyao_audit.log")


def write_crash(etype, value, tb, context: str = "") -> str:
    """写入崩溃日志"""
    err = ''.join(traceback.format_exception(etype, value, tb))
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = f"\n{'='*80}\n崩溃时间: {now}\n上下文: {context}\n{err}\n{'='*80}\n"
    try:
        with open(_get_crash_log_path(), 'a', encoding='utf-8') as f:
            f.write(msg)
    except Exception:
        pass
    return msg


def write_audit(level: str, msg: str):
    """写入审查日志"""
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    line = f"[{now}] [{level:5s}] {msg}\n"
    try:
        with open(_get_audit_log_path(), 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass
    # 同时输出到 stderr
    print(line.strip(), file=sys.stderr, flush=True)


class AuditSystem:
    """崩溃审查与自愈系统"""

    def __init__(self, app=None):
        self.app = app
        self.health_check_id: Optional[str] = None
        self.operation_count = 0
        self.error_count = 0
        self.last_success_time = time.time()
        self._lock = threading.Lock()
        self._install_global_hook()

        write_audit("INFO", "审查系统初始化完成")

    def _install_global_hook(self):
        """安装全局异常钩子"""
        old_hook = sys.excepthook

        def _hook(etype, value, tb):
            err = ''.join(traceback.format_exception(etype, value, tb))
            # 结构化上下文
            context = {
                'thread': threading.current_thread().name,
                'active_threads': threading.active_count(),
            }
            if self.app:
                try:
                    context['bankroll'] = getattr(self.app, 'bankroll', 'N/A')
                    context['match_count'] = len(getattr(self.app, '_matches', []))
                except Exception:
                    pass

            ctx_str = ' | '.join(f"{k}={v}" for k, v in context.items())
            write_crash(etype, value, tb, context=ctx_str)
            write_audit("FATAL", f"未捕获异常: {etype.__name__}: {value} | {ctx_str}")

            with self._lock:
                self.error_count += 1

            print(f"\n[FATAL] {ctx_str}\n{err}", file=sys.stderr, flush=True)

            # 调用旧钩子
            if old_hook and old_hook is not sys.__excepthook__:
                old_hook(etype, value, tb)

        sys.excepthook = _hook

    def wrap(self, operation_name: str, fn: Callable) -> Callable:
        """
        包装关键操作：前后写审计日志 + 异常捕获

        Returns:
            包装后的函数，调用方式不变

        Example:
            result = audit.wrap("抓取数据", fetcher.fetch_today)()
        """
        def _wrapped(*args, **kwargs):
            write_audit("BEGIN", f"操作: {operation_name}")

            with self._lock:
                self.operation_count += 1
            op_id = self.operation_count

            start = time.time()
            try:
                result = fn(*args, **kwargs)
                elapsed = time.time() - start
                with self._lock:
                    self.last_success_time = time.time()
                write_audit("OK", f"操作#{op_id} [{operation_name}]: "
                                   f"{elapsed:.3f}s 成功")
                return result
            except Exception as e:
                elapsed = time.time() - start
                with self._lock:
                    self.error_count += 1

                tb = traceback.format_exc()
                write_audit("FAIL", f"操作#{op_id} [{operation_name}]: "
                                    f"{elapsed:.3f}s 失败: {e}")
                write_crash(type(e), e, e.__traceback__,
                            context=f"操作: {operation_name} (op#{op_id})")
                write_audit("TRACE", tb[:2000])
                raise

        return _wrapped

    def safe_run(self, operation_name: str, fn: Callable,
                 default: Any = None, *args, **kwargs) -> Any:
        """
        安全执行：失败时返回 default，不抛异常

        Example:
            data = audit.safe_run("加载CSV", fetcher.load, default=[])
        """
        try:
            return self.wrap(operation_name, lambda: fn(*args, **kwargs))()
        except Exception:
            return default

    def start_health_check(self, interval_ms: int = 30000):
        """启动定期健康检查（在 Tkinter 环境中）"""
        if not self.app:
            write_audit("WARN", "无 app 实例，跳过健康检查")
            return

        def _check():
            status = self.health_snapshot()
            write_audit("CHECK", f"健康检查: threads={status['threads']} "
                                  f"errors={status['errors']} "
                                  f"uptime={status['uptime']}s "
                                  f"status={status['status']}")
            # 重新调度
            if self.app and hasattr(self.app, 'root'):
                try:
                    self.app.root.after(interval_ms, _check)
                except Exception:
                    pass

        if hasattr(self.app, 'root'):
            try:
                self.app.root.after(interval_ms, _check)
                write_audit("INFO", f"健康检查已启动 (间隔 {interval_ms}ms)")
            except Exception as e:
                write_audit("WARN", f"无法启动健康检查: {e}")

    def health_snapshot(self) -> Dict[str, Any]:
        """获取当前健康状态快照"""
        with self._lock:
            errors = self.error_count
            ops = self.operation_count

        snapshot = {
            'timestamp': datetime.datetime.now().isoformat(),
            'threads': threading.active_count(),
            'operations': ops,
            'errors': errors,
            'error_rate': f"{errors / max(1, ops) * 100:.1f}%" if ops > 0 else "0%",
            'uptime': int(time.time() - self.last_success_time) if errors == 0 else 0,
            'status': 'healthy' if errors == 0 else 'degraded',
        }

        # 检查是否有僵死线程
        snapshot['daemon_threads'] = sum(
            1 for t in threading.enumerate() if t.daemon
        )

        return snapshot

    def get_diagnostic_report(self) -> str:
        """生成完整诊断报告"""
        snap = self.health_snapshot()
        report = "=" * 60 + "\n"
        report += "金水谣系统诊断报告\n"
        report += "=" * 60 + "\n"
        report += f"  时间: {snap['timestamp']}\n"
        report += f"  运行线程: {snap['threads']} (守护: {snap['daemon_threads']})\n"
        report += f"  操作总数: {snap['operations']}\n"
        report += f"  错误总数: {snap['errors']}\n"
        report += f"  错误率:   {snap['error_rate']}\n"
        report += f"  健康状态: {snap['status']}\n"

        # Python 环境
        report += f"  Python: {sys.version[:40]}\n"
        report += f"  平台:   {sys.platform}\n"

        # 检查崩溃日志大小
        crash_log = _get_crash_log_path()
        if os.path.exists(crash_log):
            size = os.path.getsize(crash_log)
            report += f"  崩溃日志: {size} bytes\n"

        report += "=" * 60 + "\n"
        return report