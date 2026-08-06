# -*- coding: utf-8 -*-
"""
金水谣·自动化镜像模块（Automation Mirror）

背景（道衍·阴阳）：
  阳 = 定时触发；阴 = 免积分执行。原 13 个 WorkBuddy 自动化只是「阳」（计时器），
  实际脚本本就在本地免费 venv 跑（阴，0 成本），烧 WorkBuddy 积分仅因平台模型在「读 prompt + 按按钮」。
  本模块把触发器搬进金水谣进程内调度器（core/scheduler.py），用 sys.executable 调同一批脚本
  → 阳阴合一，积分归零。此即「道生一·约束内建」：免费是默认，不需外部模型来按按钮。

守卫机制（调度器原生只支持「每 N 分钟」，用 guard 实现「每日/每周/每月某时刻」）：
  - daily@HH:MM     : 每天到 HH:MM 后触发一次
  - weekly@WD@HH:MM : 每周几(WD=MON..SUN)到时刻后触发一次
  - monthly@DD      : 每月 DD 号触发一次（默认 03:00 起）
  _state 记「本周期已跑」，保证每周期仅一次（天/地/人：人复盘、地隔离、天规划）。

Batch 1：纯脚本、无 AI 的 7 个现成脚本 + （知识体检Lint 由原生 kb_lint 覆盖，不在此重复）。
Batch 2（见 memory）：记忆蒸馏/启动提示词同步（纯文件，写脚本）、AI抽考/联网新知（改用 free_model_pool）。
"""
import os
import sys
import json
import threading
import subprocess
from datetime import datetime

_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_log_dir = os.path.join(_proj, "金水谣数据", "log")
_interval_min = 15  # 每 15 分钟巡检一次守卫窗口

# 镜像任务表（Batch 1：纯脚本，无 AI，脚本均已存在）
MIRROR_TASKS = [
    {"name": "mirror_closeout", "script": "scripts/closeout_gate.py",
     "guard": "daily@23:30", "desc": "收工自检(五查门禁)"},
    {"name": "mirror_frontend_probe", "script": "scripts/frontend_health_probe.py",
     "guard": "daily@09:00", "desc": "前端健康巡检"},
    {"name": "mirror_graph_reconcile", "script": "scripts/graph_triples_reconcile.py",
     "guard": "weekly@SUN@05:30", "desc": "GraphRAG三元组调和"},
    {"name": "mirror_lottery_health", "script": "scripts/lottery_datasource_health.py",
     "guard": "daily@07:00", "desc": "彩票数据源健康日报"},
    {"name": "mirror_free_model_health", "script": "scripts/free_model_health_check.py",
     "guard": "daily@08:30", "desc": "免费模型健康巡检"},
    {"name": "mirror_lottery_backtest", "script": "scripts/backtest_lottery_honest.py",
     "guard": "daily@06:00", "desc": "诚实回测刷新"},
    {"name": "mirror_fund_daily", "script": "scripts/daily_fund_monitor.py",
     "guard": "daily@18:00", "desc": "基金监控日报"},
    {"name": "mirror_ai_fund_daily", "script": "scripts/ai_fund_daily_report.py",
     "guard": "daily@08:30", "desc": "AI深度版基金日报(付费DeepSeek+免费兜底)"},
    # ── Batch 2：纯文件脚本 + 免费模型（接硅基流动，0 积分）──
    {"name": "mirror_memory_distill", "script": "scripts/memory_distill.py",
     "guard": "weekly@SUN@04:00", "desc": "记忆蒸馏(>30天日志沉淀)"},
    {"name": "mirror_startup_sync", "script": "scripts/startup_prompt_sync.py",
     "guard": "weekly@MON@08:00", "desc": "启动提示词同步校验"},
    {"name": "mirror_ai_diligence", "script": "scripts/ai_diligence.py",
     "guard": "daily@23:45", "desc": "AI抽考门禁(免费模型)"},
    {"name": "mirror_knowledge_refresh", "script": "scripts/knowledge_refresh.py",
     "guard": "weekly@SUN@06:30", "desc": "联网新知注入(免费模型)"},
]

_wd_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
_state = {}            # name -> 周期键（本周期已跑标记）
_state_lock = threading.Lock()


def _period_key(guard):
    """本周期的唯一键，用于去重（每天/每周/每月一键）。"""
    now = datetime.now()
    if guard.startswith("daily@"):
        return now.strftime("%Y-%m-%d")
    if guard.startswith("weekly@"):
        return now.strftime("%Y-W%W")
    if guard.startswith("monthly@"):
        return now.strftime("%Y-%m")
    return now.strftime("%Y-%m-%d")


def _guard_open(guard):
    """当前是否已进入触发窗口？"""
    now = datetime.now()
    try:
        if guard.startswith("daily@"):
            hh, mm = map(int, guard.split("@")[1].split(":"))
            return now.hour == hh and now.minute >= mm
        if guard.startswith("weekly@"):
            _, wd, t = guard.split("@")
            hh, mm = map(int, t.split(":"))
            return now.weekday() == _wd_map[wd] and now.hour == hh and now.minute >= mm
        if guard.startswith("monthly@"):
            dd = int(guard.split("@")[1])
            return now.day == dd and now.hour >= 3
    except Exception:
        return False
    return False


def _write_log(name, desc, rc, out, err):
    """写入执行日志（失败不影响任务本身，地：隔离）。"""
    try:
        os.makedirs(_log_dir, exist_ok=True)
        from utils.log_rotation import check_and_rotate
        p = os.path.join(_log_dir, "automation_mirror.jsonl")
        check_and_rotate(p, max_size_mb=5)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                "name": name,
                "desc": desc,
                "rc": rc,
                "out": (out or "")[-1500:],
                "err": (err or "")[-1500:],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _make_func(task):
    """构造守卫触发函数：到窗口且本周期未跑 → 用 sys.executable 跑同款脚本。"""
    script = os.path.join(_proj, task["script"])
    name = task["name"]
    guard = task["guard"]
    desc = task["desc"]

    def _run():
        pk = _period_key(guard)
        with _state_lock:
            if _state.get(name) == pk:
                return  # 本周期已跑（天：规划去重）
        if not _guard_open(guard):
            return
        try:
            with _state_lock:
                _state[name] = pk  # 先标记，防同周期重复（地：隔离）
            if not os.path.isfile(script):
                sys.stderr.write("[mirror] 脚本缺失: %s\n" % script)
                _write_log(name, desc, 127, "", "脚本缺失: %s" % script)
                return
            r = subprocess.run(
                [sys.executable, script],
                cwd=_proj, capture_output=True, text=True, timeout=900,
            )
            _write_log(name, desc, r.returncode, r.stdout, r.stderr)
        except Exception as e:
            _write_log(name, desc, -1, "", "EXC:%s" % e)

    return _run


def register_mirrors(scheduler):
    """把镜像任务注册进调度器（每 15 分钟巡检守卫窗口）。"""
    for task in MIRROR_TASKS:
        scheduler.register(
            name=task["name"],
            func=_make_func(task),
            interval_minutes=_interval_min,
            enabled=True,
        )


if __name__ == "__main__":
    print("金水谣自动化镜像任务表（Batch 1，共 %d 项，全部无 AI、0 积分）：" % len(MIRROR_TASKS))
    for t in MIRROR_TASKS:
        print("  - %-26s %-12s %s" % (t["name"], t["guard"], t["desc"]))
