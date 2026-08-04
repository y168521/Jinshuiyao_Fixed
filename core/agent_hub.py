# -*- coding: utf-8 -*-
"""金水谣 · Agent 集成中心（W63补38/JS-20260804-16）

统一 agent 注册/查询/执行的"门面层"：
  - 把系统现有能力（免费模型运维/代码审查/知识管理/数据刷新/复盘/提醒…）
    抽象成一个个可注册、可调度、可手动触发的 agent；
  - 定时调度（core/scheduler.py 定时触发）与手动入口
    （python -m core.agent_hub --run xxx）共用同一批实现函数（entrypoint 引用），
    一处注册、处处可见可跑（首尾相连，无重复实现）；
  - 新增能力 = 注册一行（register_agent），自动进入清单，可排入定时；
  - 注意：scheduler 定时任务直接执行实现（薄包装），agent_hub 仅做清单+手动触发，
    两者互不嵌套调用，避免循环依赖。

能运用到什么地方（应用地图）：
  1. 免费模型运维：free_model_sync（每日自动同步配置）/ free_model_health（每2h探活）
  2. 代码质量：ai_code_review（免费模型语义审查，与 pre-commit 钩子互补兜底）
  3. 知识管理：knowledge_extract / memory_decay / cross_link / kg_rebuild / kb_lint / vector_index_rebuild
  4. 数据与复盘：data_refresh / auto_review / data_maintenance / health_backup / file_cleanup
  5. 主动提醒：proactive_reminder
  6. 未来扩展：预测复核 / 合规检查 / 新人体验证 —— 注册即接入调度+清单

免费优先约定：每个 agent 声明 complexity（light/medium/heavy），
  调度/执行时可经 free_model_pool.pick_cfg_for_task 精准匹配免费模型；
  heavy 任务免费模型不够格时明确走付费兜底（受成本闸约束），绝不静默烧预算。
"""
import os
import sys
import json
import time
import threading

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_AGENTS = {}
_LOCK = threading.Lock()


def register_agent(name, desc, category="通用", entrypoint=None, schedule_minutes=0,
                   complexity="medium", enabled=True):
    """注册一个 agent（唯一命名；重复注册 = 覆盖）。

    Args:
        name: 唯一 agent 名（小写蛇形）
        desc: 一句话描述（用于清单/规划）
        category: 分类（免费模型/代码质量/知识管理/数据复盘/提醒）
        entrypoint: 可调用对象或 (模块路径, 函数名) 字符串；None 且已存在同名则保留
        schedule_minutes: 默认调度间隔（0=仅手动），实际间隔以 config/scheduler.json 为准
        complexity: light/medium/heavy —— 供免费模型按复杂度匹配
        enabled: 是否启用（False 时 run_agent 直接跳过）
    """
    with _LOCK:
        _AGENTS[name] = {
            "name": name, "desc": desc, "category": category,
            "entrypoint": entrypoint, "schedule_minutes": schedule_minutes,
            "complexity": complexity, "enabled": enabled,
            "last_run": None, "last_ok": None, "last_error": "",
            "run_count": 0,
        }


def _resolve_entrypoint(entrypoint):
    """解析可调用对象 / (模块路径, 函数名[.类名.方法])"""
    if entrypoint is None:
        return None
    if callable(entrypoint):
        return entrypoint
    if isinstance(entrypoint, (tuple, list)) and len(entrypoint) == 2:
        mod, fn = entrypoint
        try:
            import importlib
            m = importlib.import_module(mod)
            # 支持 "Class.method"（如 TaskScheduler._task_free_model_sync）
            if "." in fn:
                cls_name, method = fn.split(".", 1)
                cls = getattr(m, cls_name)
                return getattr(cls, method)
            return getattr(m, fn)
        except Exception:
            return None
    return None


def list_agents(category=None, detail=False):
    """agent 清单（含运行统计）；category 过滤；detail=True 输出完整状态。"""
    out = []
    for a in sorted(_AGENTS.values(), key=lambda x: x["name"]):
        if category and a["category"] != category:
            continue
        if detail:
            out.append(dict(a))
        else:
            out.append({
                "name": a["name"], "desc": a["desc"], "category": a["category"],
                "schedule_minutes": a["schedule_minutes"],
                "complexity": a["complexity"], "enabled": a["enabled"],
                "last_ok": a["last_ok"], "run_count": a["run_count"],
            })
    return out


def run_agent(name, timeout=30 * 60, **kwargs):
    """执行单个 agent（异常隔离：任何失败只记录，不抛出）。

    返回 dict：{ok, output, error, duration_ms}
    """
    with _LOCK:
        a = _AGENTS.get(name)
    if a is None:
        return {"ok": False, "output": None, "error": f"agent 不存在: {name}", "duration_ms": 0}
    if not a["enabled"]:
        return {"ok": False, "output": None, "error": "agent 已禁用", "duration_ms": 0}
    fn = _resolve_entrypoint(a["entrypoint"])
    if fn is None:
        return {"ok": False, "output": None, "error": "entrypoint 解析失败", "duration_ms": 0}
    _t0 = time.time()
    try:
        out = fn(**kwargs)
        _ok = out is not False
        with _LOCK:
            a["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            a["last_ok"] = _ok
            a["last_error"] = ""
            a["run_count"] = a.get("run_count", 0) + 1
        return {"ok": _ok, "output": out, "error": "",
                "duration_ms": round((time.time() - _t0) * 1000, 1)}
    except Exception as e:
        with _LOCK:
            a["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            a["last_ok"] = False
            a["last_error"] = str(e)[:300]
            a["run_count"] = a.get("run_count", 0) + 1
        return {"ok": False, "output": None, "error": str(e)[:300],
                "duration_ms": round((time.time() - _t0) * 1000, 1)}


def run_category(category, timeout=30 * 60):
    """按分类批量执行（每 agent 独立隔离，互不影响）。返回汇总 dict。"""
    results = {}
    for a in sorted(_AGENTS.values(), key=lambda x: x["name"]):
        if a["category"] != category or not a["enabled"]:
            continue
        results[a["name"]] = run_agent(a["name"], timeout=timeout)
    return results


def _import_default_agents():
    """注册内置 agent 清单（幂等：重复导入不重复计数注册影响）。

    entrypoint 采用字符串 (模块, 函数) 延迟解析：
      - 避免启动即导入全部任务模块（只 import 必要的）
      - 调度执行时才真正装载，失败只记 agent 错误不影响系统
    """
    if _AGENTS:
        return

    # ── 免费模型运维（自动更新配置 + 自动健康探活）──
    register_agent(
        "free_model_sync", "免费模型清单自动同步（每日拉取→探活→质量排序→写回配置）",
        category="免费模型", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_free_model_sync"),
        schedule_minutes=24 * 60, complexity="light",
    )
    register_agent(
        "free_model_health", "免费模型健康探活（每2小时，全挂自动告警）",
        category="免费模型", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_free_model_health"),
        schedule_minutes=120, complexity="light",
    )

    # ── 代码质量（免费模型优先语义审查）──
    register_agent(
        "ai_code_review", "AI 代码语义审查（免费模型优先，覆盖最近7天改动，兜底 pre-commit 钩子）",
        category="代码质量", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_ai_code_review"),
        schedule_minutes=24 * 60, complexity="heavy",
    )

    # ── 知识管理 ──
    register_agent(
        "knowledge_extract", "从复盘记录自动提取知识卡片",
        category="知识管理", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_knowledge_extract"),
        schedule_minutes=120, complexity="medium",
    )
    register_agent(
        "memory_decay", "记忆衰减：对所有知识卡做衰减+自动归档",
        category="知识管理", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_memory_decay"),
        schedule_minutes=24 * 60, complexity="light",
    )
    register_agent(
        "cross_link", "双库自动发现链接（左脑MiroFish↔右脑用户库）",
        category="知识管理", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_cross_link"),
        schedule_minutes=24 * 60, complexity="medium",
    )
    register_agent(
        "kg_rebuild", "知识图谱重建",
        category="知识管理", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_kg_rebuild"),
        schedule_minutes=24 * 60, complexity="medium",
    )
    register_agent(
        "kb_lint", "知识体检（每日触发，仅每月1号执行）",
        category="知识管理", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_kb_lint"),
        schedule_minutes=24 * 60, complexity="light",
    )
    register_agent(
        "vector_index_rebuild", "向量索引重建（离线VSM，每24小时）",
        category="知识管理", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_vector_index_rebuild"),
        schedule_minutes=24 * 60, complexity="light",
    )

    # ── 数据与复盘 ──
    register_agent(
        "data_refresh", "数据刷新：抓取最新彩票/股票/足彩/基金数据",
        category="数据复盘", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_data_refresh"),
        schedule_minutes=60, complexity="light",
    )
    register_agent(
        "auto_review", "自动复盘：对最近预测自动复盘",
        category="数据复盘", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_auto_review"),
        schedule_minutes=120, complexity="medium",
    )
    register_agent(
        "data_maintenance", "数据维护：清理过期数据、压缩归档",
        category="数据复盘", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_data_maintenance"),
        schedule_minutes=24 * 60, complexity="light",
    )
    register_agent(
        "health_backup", "健康备份：全量数据备份",
        category="数据复盘", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_health_backup"),
        schedule_minutes=24 * 60, complexity="light",
    )
    register_agent(
        "file_cleanup", "文件清理：清理临时文件、整理目录",
        category="数据复盘", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_file_cleanup"),
        schedule_minutes=24 * 60, complexity="light",
    )

    # ── 主动提醒 ──
    register_agent(
        "proactive_reminder", "主动提醒引擎：扫描到期提醒写入待提醒队列",
        category="提醒", entrypoint=("core.scheduler", "JinshuiyaoScheduler._task_proactive_reminder"),
        schedule_minutes=30, complexity="light",
    )


def print_report(category=None):
    """打印人类可读的 agent 清单（用于 ops 侧展示/规划）。"""
    _import_default_agents()
    rows = list_agents(category, detail=False)
    if not rows:
        print("（无 agent）")
        return
    name_w = max(len(r["name"]) for r in rows)
    print(f"{'agent':<{name_w}}  {'复杂度':<8}{'间隔分':<7}{'状态':<6} 说明")
    print("-" * (name_w + 45))
    for r in rows:
        comp = {"light": "轻", "medium": "中", "heavy": "重"}.get(r["complexity"], r["complexity"])
        sch = r["schedule_minutes"] or "手动"
        st = "启用" if r["enabled"] else "停用"
        last = f"上次{'✓' if r['last_ok'] else '✗'}" if r["last_ok"] is not None else ""
        print(f"{r['name']:<{name_w}}  {comp:<8}{str(sch):<7}{st:<6} {r['desc']} {last}".rstrip())


def main(argv=None):
    """CLI：python -m core.agent_hub --list [--category X] | --run NAME [--run-category X]"""
    import argparse
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="金水谣 Agent 集成中心")
    p.add_argument("--list", action="store_true", help="列出全部 agent")
    p.add_argument("--category", default="", help="按分类过滤（免费模型/代码质量/知识管理/数据复盘/提醒）")
    p.add_argument("--run", default="", help="执行指定 agent")
    p.add_argument("--run-category", default="", help="执行指定分类的全部 agent")
    p.add_argument("--json", action="store_true", help="JSON 输出（供脚本/接口消费）")
    args = p.parse_args(argv)

    _import_default_agents()

    if args.run:
        res = run_agent(args.run)
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            print(f"[agent:{args.run}] ok={res['ok']} {res['duration_ms']}ms"
                  + (f" error={res['error']}" if res["error"] else ""))
        return 0 if res["ok"] else 2
    if args.run_category:
        res = run_category(args.run_category)
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            for n, r in res.items():
                print(f"[agent:{n}] ok={r['ok']} {r['duration_ms']}ms"
                      + (f" error={r['error']}" if r["error"] else ""))
        return 0 if all(r["ok"] for r in res.values()) else 2
    if args.json:
        print(json.dumps(list_agents(args.category, detail=True), ensure_ascii=False))
    else:
        print_report(args.category)
    return 0


if __name__ == "__main__":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
