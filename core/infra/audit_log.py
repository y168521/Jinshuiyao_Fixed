# -*- coding: utf-8 -*-
"""操作审计日志模块（全局统一审计）

本模块是金水谣系统唯一的操作审计日志入口，统一记录所有关键操作到审计日志文件，
形成可追溯的闭环。所有子系统（彩票/足彩/股票/基金）共享此模块。

职责范围：
  - 预测生成 / 复盘结果
  - 子系统状态变更（熔断、恢复）
  - 数据拉取结果（成功/失败/降级）
  - 系统启动/关闭事件

与其他"audit"模块的关系（非重复，职责不同）：
  - engines/audit.py   — 彩票号码合规校验（验证号码范围/格式），不是审计日志
  - jinshuiyao/audit.py   — 足彩崩溃捕获与自愈系统（运行时异常监控），不是审计日志

日志格式: JSON Lines（每行一个JSON对象），文件扩展名 .logl
"""
import os
import json
import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 审计日志路径（默认：金水谣数据/log/change_audit.logl）
_audit_log_path: Optional[str] = None
_log_lock = threading.Lock()


def set_audit_log_path(path: str):
    """设置审计日志文件路径"""
    global _audit_log_path
    _audit_log_path = path
    # 确保目录存在
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _get_default_path() -> str:
    """获取默认审计日志路径"""
    try:
        from config import DATA_SAVE
        return os.path.join(DATA_SAVE, "log", "change_audit.logl")
    except ImportError:
        return os.path.join("金水谣数据", "log", "change_audit.logl")


def _ensure_path():
    """确保日志路径已设置（线程安全）"""
    global _audit_log_path
    if _audit_log_path is not None:
        return
    with _log_lock:
        if _audit_log_path is not None:
            return
        _audit_log_path = _get_default_path()
        parent = os.path.dirname(_audit_log_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)


def log_event(
    event_type: str,
    subsystem: str = "global",
    summary: str = "",
    detail: str = "",
    data: Optional[dict] = None,
    level: str = "info",
):
    """记录一条审计事件

    Args:
        event_type: 事件类型（PREDICT/REVIEW/FETCH/CIRCUIT_BREAKER/SYSTEM等）
        subsystem: 子系统名称（lottery/stock/football/global）
        summary: 简短摘要
        detail: 详细描述
        data: 附加数据字典
        level: 日志级别（info/warn/error/debug）
    """
    _ensure_path()

    record = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": event_type,
        "subsystem": subsystem,
        "level": level,
        "summary": summary,
        "detail": detail,
    }
    if data:
        record["data"] = data

    line = json.dumps(record, ensure_ascii=False)

    try:
        with _log_lock:
            with open(_audit_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        logger.warning("写入审计日志失败: %s", e)


# 便捷函数
def log_predict(subsystem: str, lot: str, scheme: str, ticket_count: int, success: bool = True):
    """记录预测生成事件"""
    log_event(
        event_type="PREDICT",
        subsystem=subsystem,
        summary=f"生成{lot}预测（{scheme}）: {ticket_count}注",
        detail=f"彩种={lot}, 方案={scheme}, 注数={ticket_count}, 成功={success}",
        data={"lot": lot, "scheme": scheme, "ticket_count": ticket_count, "success": success},
    )


def log_review(subsystem: str, lot: str, hit_rate: float, period: str = ""):
    """记录复盘事件"""
    log_event(
        event_type="REVIEW",
        subsystem=subsystem,
        summary=f"复盘{lot}: 命中率{hit_rate:.1%}",
        detail=f"彩种={lot}, 期号={period}, 命中率={hit_rate}",
        data={"lot": lot, "period": period, "hit_rate": hit_rate},
    )


def log_fetch(subsystem: str, source: str, success: bool, count: int = 0, fallback: bool = False):
    """记录数据拉取事件"""
    status = "成功" if success else ("降级" if fallback else "失败")
    log_event(
        event_type="FETCH",
        subsystem=subsystem,
        summary=f"数据拉取{status}: {source} ({count}条)",
        detail=f"来源={source}, 成功={success}, 降级={fallback}, 条数={count}",
        data={"source": source, "success": success, "fallback": fallback, "count": count},
        level="info" if success else ("warn" if fallback else "error"),
    )


def log_circuit_breaker(name: str, from_state: str, to_state: str, reason: str = ""):
    """记录熔断器状态变更"""
    log_event(
        event_type="CIRCUIT_BREAKER",
        subsystem="global",
        summary=f"熔断器[{name}]: {from_state} -> {to_state}",
        detail=f"熔断器={name}, 从{from_state}转为{to_state}, 原因={reason}",
        data={"name": name, "from": from_state, "to": to_state, "reason": reason},
        level="warn" if to_state == "open" else "info",
    )


def log_system(event: str, detail: str = ""):
    """记录系统事件"""
    log_event(
        event_type="SYSTEM",
        subsystem="global",
        summary=f"系统{event}",
        detail=detail,
    )


def read_recent(limit: int = 50, event_type: Optional[str] = None) -> list:
    """读取最近的审计日志

    Args:
        limit: 读取条数（从最新往前数）
        event_type: 按类型过滤，None则不过滤

    Returns:
        日志记录列表（最新的在前）
    """
    _ensure_path()
    records = []
    try:
        with open(_audit_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if event_type and rec.get("type") != event_type:
                        continue
                    records.append(rec)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return []

    return records[-limit:][::-1]  # 最新的在前
