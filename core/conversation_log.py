# -*- coding: utf-8 -*-
"""金水谣引擎 - AI对话持久化日志

每次AI调用自动记录摘要、Token用量、耗时，写入JSONL文件。
重启后数据不丢失，可供后续分析和知识提取使用。

日志位置：金水谣数据/log/ai_conversations.jsonl
"""

import json
import os
import threading
from datetime import datetime

# 日志文件路径
_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "金水谣数据", "log"
)
_LOG_FILE = os.path.join(_LOG_DIR, "ai_conversations.jsonl")

# 写入锁（线程安全）
_write_lock = threading.Lock()

# 单条日志最大长度（防止写入过大的内容）
_MAX_PROMPT_LEN = 500
_MAX_REPLY_LEN = 1000


def _truncate(text: str, max_len: int) -> str:
    """截断过长文本，保留头尾"""
    if not text or len(text) <= max_len:
        return text or ""
    head = text[:max_len // 2]
    tail = text[-(max_len // 4):]
    return f"{head}...[省略{len(text) - max_len}字]...{tail}"


def log_conversation(
    system_prompt: str,
    user_prompt: str,
    reply: str,
    provider: str = "",
    model: str = "",
    token_usage: dict = None,
    duration_ms: float = 0,
    success: bool = True,
    error_msg: str = "",
):
    """记录一次AI对话到日志文件

    Args:
        system_prompt: 系统提示词（截断存储）
        user_prompt: 用户输入（截断存储）
        reply: AI回复（截断存储）
        provider: 供应商名称（deepseek/ollama等）
        model: 模型名称
        token_usage: Token用量 {"prompt": N, "completion": N, "total": N}
        duration_ms: 调用耗时（毫秒）
        success: 是否成功
        error_msg: 错误信息（失败时）
    """
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provider": provider,
        "model": model,
        "system_brief": _truncate(system_prompt, 200),
        "user_brief": _truncate(user_prompt, _MAX_PROMPT_LEN),
        "reply_brief": _truncate(reply, _MAX_REPLY_LEN),
        "tokens": token_usage or {},
        "duration_ms": round(duration_ms, 1),
        "success": success,
        "error": error_msg if not success else "",
    }

    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with _write_lock:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # 日志写入失败不影响主流程
        pass


def read_recent(limit: int = 20) -> list:
    """读取最近的对话记录

    Args:
        limit: 最多返回条数

    Returns:
        list[dict]: 对话记录列表（最新的在前）
    """
    if not os.path.isfile(_LOG_FILE):
        return []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        records = []
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        records.reverse()  # 最新的在前
        return records
    except Exception:
        return []


def get_usage_summary() -> dict:
    """汇总Token用量统计

    Returns:
        dict: 总调用次数、总Token、按供应商分组统计
    """
    if not os.path.isfile(_LOG_FILE):
        return {"total_calls": 0, "total_tokens": 0, "by_provider": {}}
    try:
        total_calls = 0
        total_tokens = 0
        total_duration = 0
        by_provider = {}
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total_calls += 1
                tokens = rec.get("tokens", {})
                t = tokens.get("total", 0)
                total_tokens += t
                total_duration += rec.get("duration_ms", 0)

                prov = rec.get("provider", "unknown")
                if prov not in by_provider:
                    by_provider[prov] = {"calls": 0, "tokens": 0, "success": 0}
                by_provider[prov]["calls"] += 1
                by_provider[prov]["tokens"] += t
                if rec.get("success"):
                    by_provider[prov]["success"] += 1

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "avg_duration_ms": round(total_duration / max(total_calls, 1), 1),
            "by_provider": by_provider,
        }
    except Exception:
        return {"total_calls": 0, "total_tokens": 0, "by_provider": {}}
