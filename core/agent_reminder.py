# -*- coding: utf-8 -*-
"""金水谣本地助手 · 主动提醒引擎

让助手从"你问它答"升级为"到点主动找你"：
  - 系统级提醒：与已有调度任务时点对齐（收工门禁23:30 / 免费模型探活08:30 / 基金日报18:00）
  - 用户级提醒：从 user_profile.json 的"记住"记忆里解析周期事项（如"我每天晚上8点收工"）
  - 去重：同一规则当天只推一次（fired_log 记日期）
  - 注入：对话开始时 pop 待提醒，助手主动开口

道衍：阳=主动服务(阴=不骚扰) → 守两仪：只读不强制、当天去重防刷屏；
      天=规则可配置、地=落盘隔离、人=用户可记可忘；知止=不碰业务数据、不自动执行高风险。
"""

import os
import re
import json
import threading
from datetime import datetime
from utils.safe_json import safe_write_json

# 系统级提醒规则（time 为 HH:MM；调度器每30分钟扫一次，±窗口内触发）
SYSTEM_REMINDERS = [
    {"id": "free_health", "title": "免费模型探活", "time": "08:30",
     "text": "早上好～08:30 是免费模型探活时刻，我已自动检查模型池健康，异常会自愈重探活；你可以顺手确认一下状态。"},
    {"id": "fund_report", "title": "基金日报", "time": "18:00",
     "text": "18:00 到了，可以让我生成今天的基金日报。"},
    {"id": "closeout", "title": "收工门禁自检", "time": "23:30",
     "text": "快到 23:30 收工点，记得跑收工门禁自检（closeout_gate），确认 git 未提交/索引登记/今日卡都齐了再收工。"},
]

_WEEK_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
             "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}
# 用户记忆周期解析正则（宽松匹配常见中文表达，支持"晚上/下午"12小时制→24小时偏移）
_RE_DAY = re.compile(r'(每天|每日|天天).*?((?:凌晨|早上|上午|中午|下午|晚上|夜里|夜晚)?)\s*(\d{1,2})\s*[点时分]')
_RE_WEEK = re.compile(r'(每周|每星期|周)\D{0,4}?([一二三四五六日天])')
_RE_MONTH = re.compile(r'(每月|每个月|月)\D{0,6}?(\d{1,2})\s*[号日]')


def _parse_user_reminders(memories):
    """从用户记忆文本解析周期性提醒。返回 [{id, period, when, text}]"""
    out = []
    for i, m in enumerate(memories):
        text = m if isinstance(m, str) else (m.get("text") if isinstance(m, dict) else "")
        if not text:
            continue
        md = _RE_DAY.search(text)
        if md:
            hour = int(md.group(3))
            period_word = md.group(2) or ""
            if period_word in ("下午", "晚上", "夜里", "夜晚") and hour < 12:
                hour += 12  # 12小时制→24小时制（如"晚上8点"=20点）
            out.append({"id": f"u_day_{i}", "period": "day", "when": hour,
                        "text": text})
            continue
        mw = _RE_WEEK.search(text)
        if mw:
            out.append({"id": f"u_week_{i}", "period": "week",
                        "when": _WEEK_MAP.get(mw.group(2), 0),
                        "text": text})
            continue
        mm = _RE_MONTH.search(text)
        if mm:
            out.append({"id": f"u_month_{i}", "period": "month", "when": int(mm.group(2)),
                        "text": text})
    return out


def _due_key(rid, now):
    return f"{rid}:{now.strftime('%Y-%m-%d')}"


def check_due(mem_dir, now=None, window_min=15):
    """返回当前到期的提醒列表（已去重，今天未推的）。

    系统规则用窗口（±window_min 分钟）；用户规则整点匹配即触发（调度器30分钟内必扫到当天该小时）。
    """
    now = now or datetime.now()
    h, m = now.hour, now.minute
    results = []
    # 系统规则
    for r in SYSTEM_REMINDERS:
        rh, rm = (int(x) for x in r["time"].split(":"))
        diff = (h * 60 + m) - (rh * 60 + rm)
        if -window_min <= diff <= window_min:
            results.append({"id": r["id"], "title": r["title"], "text": r["text"], "kind": "system"})
    # 用户规则
    try:
        pf = os.path.join(mem_dir, "user_profile.json")
        if os.path.isfile(pf):
            with open(pf, "r", encoding="utf-8") as f:
                prof = json.load(f)
            mems = prof.get("memories", [])
            texts = [x.get("text", "") if isinstance(x, dict) else str(x) for x in mems]
            for ur in _parse_user_reminders(texts):
                ok = False
                if ur["period"] == "day":
                    ok = (ur["when"] == h)
                elif ur["period"] == "week":
                    ok = (ur["when"] == now.weekday())
                elif ur["period"] == "month":
                    ok = (ur["when"] == now.day)
                if ok:
                    results.append({"id": ur["id"], "title": "你的日程", "text": ur["text"], "kind": "user"})
    except Exception:
        pass
    return results


def render_due(mem_dir, now=None):
    """调度器定时调用：把到期且今天未推的提醒写入 pending_reminders.json。返回新写入数。"""
    now = now or datetime.now()
    pending_path = os.path.join(mem_dir, "pending_reminders.json")
    fired = {}
    pending = []
    try:
        if os.path.isfile(pending_path):
            with open(pending_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            fired = data.get("fired_log", {}) or {}
            pending = data.get("pending", []) or []
    except Exception:
        pass
    due = check_due(mem_dir, now)
    new_count = 0
    for d in due:
        key = _due_key(d["id"], now)
        if key in fired:
            continue  # 今天已推过
        fired[key] = now.strftime("%Y-%m-%d %H:%M")
        pending.append({"id": d["id"], "title": d["title"], "text": d["text"],
                        "kind": d["kind"], "due": now.strftime("%Y-%m-%d %H:%M")})
        new_count += 1
    try:
        os.makedirs(mem_dir, exist_ok=True)
        safe_write_json(pending_path, {"pending": pending, "fired_log": fired})
    except Exception:
        pass
    return new_count


def pop_pending(mem_dir):
    """对话开始时调用：取出待提醒文本列表并清空（用户已看到）。"""
    pending_path = os.path.join(mem_dir, "pending_reminders.json")
    if not os.path.isfile(pending_path):
        return []
    try:
        with open(pending_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pending = data.get("pending", []) or []
        if pending:
            safe_write_json(pending_path, {"pending": [], "fired_log": data.get("fired_log", {})})
        return [p.get("text", "") for p in pending if p.get("text")]
    except Exception:
        return []
