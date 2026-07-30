# -*- coding: utf-8 -*-
"""金水谣系统 - 定时任务调度器 API 端点

路由：
  GET /api/scheduler/status  — 获取所有定时任务的运行状态
  GET /api/scheduler/log     — 获取最近的调度执行日志（JSONL）
"""
import os
import json
import urllib.parse

from ..config import BASE_DIR
from ..utils import log


def handle_scheduler_status(handler):
    """GET /api/scheduler/status — 获取所有定时任务的运行状态

    返回格式:
    {
        "ok": true,
        "tasks": [
            {
                "name": "data_refresh",
                "enabled": true,
                "interval_minutes": 60,
                "last_run": "2026-01-01T12:00:00",
                "next_run": "2026-01-01T13:00:00",
                "run_count": 5,
                "last_error": null
            },
            ...
        ]
    }
    """
    try:
        from core.scheduler import get_scheduler
        scheduler = get_scheduler()
        tasks = scheduler.status()
        handler._send_json({"ok": True, "tasks": tasks})
    except Exception as e:
        log(f'[scheduler-status] 获取调度器状态失败: {e}')
        handler._send_json({"ok": False, "error": f"获取调度器状态失败: {e}", "tasks": []}, 500)


def handle_scheduler_log(handler, parsed):
    """GET /api/scheduler/log?limit=50 — 获取最近的调度执行日志

    查询参数:
        limit: 返回条数，默认50，最大200

    返回格式:
    {
        "ok": true,
        "logs": [
            {
                "timestamp": "2026-01-01T12:00:00",
                "name": "data_refresh",
                "duration_ms": 1234,
                "success": true,
                "error": null
            },
            ...
        ]
    }
    """
    try:
        # 解析 limit 参数
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            limit = int(qs.get('limit', ['50'])[0])
            limit = max(1, min(limit, 200))
        except (ValueError, IndexError):
            limit = 50

        log_path = os.path.join(BASE_DIR, '金水谣数据', 'log', 'scheduler_exec.jsonl')

        if not os.path.isfile(log_path):
            handler._send_json({"ok": True, "logs": [], "info": "暂无执行日志"})
            return

        # 读取文件最后 N 行（高效：从尾部读取）
        logs = []
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 取最后 limit 条，倒序返回（最新的在前）
            recent_lines = lines[-limit:]
            for line in reversed(recent_lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    logs.append(entry)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            log(f'[scheduler-log] 读取日志文件失败: {e}')
            handler._send_json({"ok": False, "error": f"读取日志失败: {e}", "logs": []}, 500)
            return

        handler._send_json({"ok": True, "logs": logs, "total": len(logs)})

    except Exception as e:
        log(f'[scheduler-log] 接口异常: {e}')
        handler._send_json({"ok": False, "error": f"接口异常: {e}", "logs": []}, 500)
