# -*- coding: utf-8 -*-
"""实时流水线状态中心（阶段一·实时基建）。

为「智能研报生成」多 Agent 流水线提供**进程内共享状态**：
- 维护节点拓扑与各节点当前状态（idle / active / checking / pass / fail）
- 支持服务端脚本化运行（start_run）：边跑边把每一步状态写进来，供前端轮询跟随
- 阶段二接入真实研报 Agent 时，这里就是它们统一写入「当前跑到哪步」的入口

设计原则（铁律·并发安全）：
- 所有「读-改-写」都走同一把锁的临界区，杜绝并发竞态
- 后台推进用 daemon 线程，绝不阻塞 HTTP 请求线程
- 纯标准库实现，可被独立 import 做单元测试，不依赖项目其它模块
"""
import threading
import time
import datetime

# ---------------------------------------------------------------------------
# 节点拓扑（与前端可视化器 agent-pipeline-visualizer.html 完全一致）
# ---------------------------------------------------------------------------
NODES = [
    {"id": "coord",       "label": "团队协调者", "kind": "coord"},
    {"id": "collect",     "label": "信息采集",   "kind": "collect"},
    {"id": "analyze",     "label": "数据分析",   "kind": "analyze"},
    {"id": "write",       "label": "内容撰写",   "kind": "write"},
    {"id": "review",      "label": "质量审核",   "kind": "review"},
    {"id": "deliver",     "label": "最终交付物", "kind": "deliver"},
]
EDGES = [
    ("coord", "collect"),
    ("coord", "analyze"),
    ("coord", "write"),
    ("collect", "review"),
    ("analyze", "review"),
    ("write", "review"),
    ("review", "deliver"),
    ("review", "write", "loop"),   # 审核不通过时的回退边
]

# 流水线静态统计（阶段二可由真实任务回填）
_STATS = {
    "nodes": len(NODES),
    "parallel": 3,
    "eta_sec": 92,
    "tokens_k": 48.6,
    "quality": 94,
}

# ---------------------------------------------------------------------------
# 共享状态 + 单一锁
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()

STATE = {
    "running": False,
    "phase": "idle",        # idle | running | done | error
    "started_at": None,
    "updated_at": None,
    "loop_count": 0,        # 审核回退次数
    "current": None,        # 当前激活的节点 id
    "nodes": {n["id"]: {"state": "idle", "detail": ""} for n in NODES},
    "stats": dict(_STATS),
}

_RUN_THREAD = None


def _now_iso():
    return datetime.datetime.now().isoformat()


def get_state():
    """返回当前流水线状态的完整快照（线程安全）。"""
    with _LOCK:
        return {
            "connected": True,
            "server_time": _now_iso(),
            "build": "pipeline-state-1",
            "running": STATE["running"],
            "phase": STATE["phase"],
            "started_at": STATE["started_at"],
            "updated_at": STATE["updated_at"],
            "loop_count": STATE["loop_count"],
            "current": STATE["current"],
            "nodes": {k: dict(v) for k, v in STATE["nodes"].items()},
            "stats": dict(STATE["stats"]),
            "topology": {
                "nodes": [dict(n) for n in NODES],
                "edges": [list(e) for e in EDGES],
            },
        }


def _set_node(sid, state, detail=""):
    with _LOCK:
        STATE["nodes"][sid] = {"state": state, "detail": detail}
        STATE["updated_at"] = _now_iso()
        STATE["current"] = sid


def _reset_nodes():
    with _LOCK:
        for n in NODES:
            STATE["nodes"][n["id"]] = {"state": "idle", "detail": ""}


def _bump_loop():
    with _LOCK:
        STATE["loop_count"] += 1


# 脚本化运行步骤：[节点id, 状态, 说明, 持续秒数]
# 完整演绎「审核不通过 → 回退重写 → 复检通过」的真实故事
_SCRIPT = [
    ("coord",       "active",   "分解任务并分发到三个 Agent",         1.4),
    ("collect",     "active",   "并行检索行业资料与公开数据",          0.0),
    ("analyze",     "active",   "并行清洗、建模与趋势分析",            0.0),
    ("write",       "active",   "并行撰写研报初稿",                    2.2),
    ("collect",     "pass",     "资料采集完成（12 个来源）",           0.0),
    ("analyze",     "pass",     "数据分析完成（6 张图表）",            0.0),
    ("write",       "pass",     "初稿完成（约 3.2k 字）",             0.0),
    ("review",      "checking", "质量审核：校验数据支撑与逻辑",        1.6),
    ("review",      "fail",     "数据支撑不足，退回撰写重写",          0.0),
    ("write",       "active",   "根据审核意见重写关键章节",            1.8),
    ("write",       "pass",     "修订稿完成",                         0.0),
    ("review",      "checking", "复检：复核修订内容与引用",            1.4),
    ("review",      "pass",     "审核通过",                           0.0),
    ("deliver",     "active",   "生成最终交付物（PDF / 网页）",        1.2),
    ("deliver",     "pass",     "交付完成",                           0.0),
]


def _run_script():
    """服务端脚本化推进（在 daemon 线程中执行）。

    阶段二将把这里的「脚本」替换为真实的研报 Agent 调用，
    但对外暴露的 get_state / start_run 接口保持不变 —— 前端无需改动。
    """
    try:
        with _LOCK:
            STATE["running"] = True
            STATE["phase"] = "running"
            STATE["started_at"] = _now_iso()
            STATE["updated_at"] = _now_iso()
            STATE["loop_count"] = 0
            STATE["current"] = "coordinator"
        _reset_nodes()
        for sid, st, detail, dur in _SCRIPT:
            if st == "fail":
                _bump_loop()
            _set_node(sid, st, detail)
            if dur > 0:
                time.sleep(dur)
        with _LOCK:
            STATE["running"] = False
            STATE["phase"] = "done"
            STATE["updated_at"] = _now_iso()
    except Exception:
        with _LOCK:
            STATE["running"] = False
            STATE["phase"] = "error"
            STATE["updated_at"] = _now_iso()


def start_run():
    """触发一次流水线运行。已在运行时返回 False（避免叠加）。"""
    global _RUN_THREAD
    with _LOCK:
        if STATE["running"]:
            return False
        # 允许重新开始：构造新的 daemon 线程
        _RUN_THREAD = threading.Thread(
            target=_run_script, daemon=True, name="pipeline-run")
    _RUN_THREAD.start()
    return True


if __name__ == "__main__":
    # 极简自测：跑一遍脚本并打印若干快照
    print("start_run ->", start_run())
    time.sleep(0.5)
    print("mid:", get_state()["current"], get_state()["phase"])
    _RUN_THREAD.join(timeout=20)
    s = get_state()
    print("final phase:", s["phase"], "loop_count:", s["loop_count"])
    print("deliver state:", s["nodes"]["deliver"]["state"])
