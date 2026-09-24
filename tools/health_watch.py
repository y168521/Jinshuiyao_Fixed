# -*- coding: utf-8 -*-
"""金水谣 · 健康看门狗（JS-20260925-05）

为什么要有这个文件
------------------
项目里其实**早就写好了** `tools/staleness_check.py`（2026-08-02），它首跑就抓到过
「knowledge_graph.json 从未生成（调度器 kg_rebuild 没跑成功）」。但全仓 grep 显示
它的被引用处数是 **0** —— 从来没有任何定时任务或门禁调用它。

于是形成了三个断层，让问题能潜伏 46 天：
  ① 产生层：日志/报告照常生成（"已注册任务 kg_rebuild" 每天都在打）
  ② 拦截层：不在门禁链路上，不阻断任何操作
  ③ 呈现层：只躺在终端输出和日志文件里，没人看

**"有日志"不等于"会报警"，更不等于"有人看见"。** 本文件补的就是第 ②③ 层：
把分散的检查汇总成**一份人可读的告警**，并且只报「能变绿」的项。

设计铁律
--------
1. **只报能变绿的**：用「长期未动」的绝对天数阈值，而不是「资产比源旧」
   （后者在源刚更新时必然为真，天天红 = 噪音，噪音比没有告警更糟）。
2. **只读**：不修改任何业务数据，只写告警文件。
3. **自身异常绝不静默**：读不到一律按"有问题"报出（静默才是敌人）。

用法
----
    python tools/health_watch.py          # 打印 + 写告警文件
    python tools/health_watch.py --quiet  # 只写文件，退出码 0/1
"""
import os
import sys
import time
import json
import argparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# 复用 staleness_check 的资产清单与 mtime 工具（它是"孤儿检查器"，这里把它接上链路）
_TOOLS = os.path.join(BASE_DIR, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
from staleness_check import ASSETS, _mtime  # noqa: E402

# --- 阈值（模块级常量，登记见 金水谣_标准唯一真源.md §三 3.8）-----------------
ASSET_STALE_DAYS = 7
"""派生资产（卡片/三元组/向量/图谱/索引）超过本天数未构建即告警。

为什么不用"资产比源旧"：源（经验收集箱）几乎每天在写，那样天天都是"陈旧"，
天天红 = 没人看 = 等于没有告警。用绝对天数，重建一次即可变绿。
"""

TASK_LATE_FACTOR = 3
"""调度器任务超过「间隔 × 本系数」仍未成功执行即告警（含从未执行过的）。

3 倍是留足容错：服务重启、一次失败重试、一次超时都不该立刻报警。
"""

OPTIONAL_ASSETS = frozenset(["Skill备用区(兼容)"])
"""可选资产白名单：这些目录是旧版兼容路径（迁移后本就不再创建），
缺失属常态、也不需要修复 → 报出来只会稀释真正的问题。
**告警的价值等于它能不能变绿**，不能变绿的存量告警就是噪音。"""

ALERT_FILE = os.path.join(BASE_DIR, "金水谣数据", "log", "健康告警.md")
LASTRUN_FILE = os.path.join(BASE_DIR, "金水谣数据", "log", "scheduler_lastrun.json")
SCHED_CFG = os.path.join(BASE_DIR, "config", "scheduler.json")
AI_DECISIONS = os.path.join(BASE_DIR, "金水谣数据", "log", "ai_decisions.md")
# 单一真源：决策卡阈值以门禁为准，此处不另写一份（两份数字迟早会漂移）
try:
    from tools.check_consistency import AI_DECISION_STALE_DAYS  # noqa: E402
except Exception:  # 门禁模块不可用时降级，但绝不静默
    AI_DECISION_STALE_DAYS = 14


def _days_since(ts):
    if not ts:
        return None
    return (time.time() - ts) / 86400.0


def check_assets():
    """① 派生资产长期未构建"""
    out = []
    for name, path, dep in ASSETS:
        if name in OPTIONAL_ASSETS:
            continue
        if os.path.isdir(path):
            ts = None
            for root, _d, files in os.walk(path):
                for f in files:
                    t = _mtime(os.path.join(root, f))
                    if t and (ts is None or t > ts):
                        ts = t
        else:
            ts = _mtime(path)
        if ts is None:
            out.append({"item": "资产缺失", "name": name,
                        "detail": "文件/目录不存在：%s" % path,
                        "how": "重跑对应的构建脚本（见 staleness_check 的依赖说明：%s）" % dep})
            continue
        d = _days_since(ts)
        if d is not None and d > ASSET_STALE_DAYS:
            out.append({"item": "资产长期未构建", "name": name,
                        "detail": "已 %.0f 天未更新（阈值 %d 天）" % (d, ASSET_STALE_DAYS),
                        "how": "重跑对应构建脚本即可变绿"})
    return out


def _task_intervals():
    """读取调度器任务的间隔配置（分钟）"""
    cfg = {}
    try:
        if os.path.isfile(SCHED_CFG):
            with open(SCHED_CFG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
    except Exception:
        cfg = {}
    return {k: v for k, v in cfg.items() if isinstance(v, (int, float)) and v > 0}


def check_scheduler():
    """② 调度器任务长期未成功执行（含从未执行过）"""
    out = []
    intervals = _task_intervals()
    try:
        if not os.path.isfile(LASTRUN_FILE):
            return [{"item": "调度器无执行记录", "name": "scheduler_lastrun.json",
                     "detail": "从未记录到任何任务成功执行（可能服务刚启动或从未跑过长任务）",
                     "how": "服务启动后长任务会自动补跑（JS-20260925-04）；持续为空则需人工核查"}]
        with open(LASTRUN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            # 文件存在但一条记录都没有 = 长任务一次都没成功执行过，必须报出来
            return [{"item": "调度器无执行记录", "name": "scheduler_lastrun.json",
                     "detail": "文件存在但为空：长周期任务从未成功执行过",
                     "how": "服务启动后会自动补跑（JS-20260925-04）；持续为空需人工核查"}]
    except Exception as e:
        return [{"item": "调度器记录读取失败", "name": LASTRUN_FILE,
                 "detail": "解析异常：%s" % e, "how": "删除该文件让系统重新生成"}]

    for name, iso in (data or {}).items():
        try:
            dt = datetime.fromisoformat(iso)
            days = (datetime.now() - dt).days
        except Exception:
            out.append({"item": "执行时间无法解析", "name": name,
                        "detail": "记录值 %r 不是合法时间" % iso,
                        "how": "删除该条记录，下次成功执行会重新写入"})
            continue
        interval_min = intervals.get(name)
        if not interval_min:
            continue
        limit_days = interval_min / 1440.0 * TASK_LATE_FACTOR
        if days > limit_days:
            out.append({"item": "任务长期未执行", "name": name,
                        "detail": "已 %d 天未成功执行（间隔 %s 分钟 × %d 倍容错 = %.1f 天）"
                                  % (days, interval_min, TASK_LATE_FACTOR, limit_days),
                        "how": "让服务常驻后会自动补跑；或用启动金水谣助手.bat 重启服务"})
    return out


def check_decisions():
    """③ AI 决策卡断档"""
    try:
        if not os.path.isfile(AI_DECISIONS):
            return [{"item": "决策卡文件缺失", "name": "ai_decisions.md",
                     "detail": "文件不存在", "how": "补写一张决策卡"}]
        with open(AI_DECISIONS, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        import re
        dates = re.findall(r"^###\s*(\d{4}-\d{2}-\d{2})", text, re.M)
        if not dates:
            return [{"item": "决策卡无有效标题", "name": "ai_decisions.md",
                     "detail": "解析不出任何 `### YYYY-MM-DD` 标题",
                     "how": "按十字段格式补写一张决策卡"}]
        last = max(dates)
        d = (datetime.now() - datetime(*[int(x) for x in last.split("-")])).days
        if d > AI_DECISION_STALE_DAYS:
            return [{"item": "决策卡断档", "name": "ai_decisions.md",
                     "detail": "已 %d 天无新增（最新 %s，阈值 %d 天）"
                               % (d, last, AI_DECISION_STALE_DAYS),
                     "how": "补写一张决策卡即可变绿"}]
        return []
    except Exception as e:
        return [{"item": "决策卡检查异常", "name": "ai_decisions.md",
                 "detail": "%s: %s" % (type(e).__name__, e), "how": "人工核查文件"}]


def collect():
    alerts = []
    for fn in (check_assets, check_scheduler, check_decisions):
        try:
            alerts.extend(fn())
        except Exception as e:  # 单个检查器崩了必须报出来，不能静默吞掉
            alerts.append({"item": "检查器异常", "name": fn.__name__,
                           "detail": "%s: %s" % (type(e).__name__, e),
                           "how": "修复该检查器"})
    return alerts


def render(alerts):
    lines = ["# 金水谣 · 健康告警", "",
             "> 由 `tools/health_watch.py` 自动生成，**只读检查结果**。",
             "> 原则：只报「能变绿」的项——每条都给了处置动作；",
             "> 如果某条长期无法变绿，说明阈值需要调整，而不是继续堆着。", "",
             "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "- 告警条数：**%d**" % len(alerts), ""]
    if not alerts:
        lines += ["## ✅ 全部健康", "", "三项检查（派生资产 / 调度器任务 / 决策卡）均在阈值内。", ""]
        return "\n".join(lines)
    lines += ["| 类别 | 对象 | 现状 | 如何变绿 |", "|---|---|---|---|"]
    for a in alerts:
        lines.append("| %s | `%s` | %s | %s |" % (a["item"], a["name"], a["detail"], a["how"]))
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="金水谣健康看门狗")
    ap.add_argument("--quiet", action="store_true", help="只写文件，不打印")
    args = ap.parse_args(argv)

    alerts = collect()
    text = render(alerts)
    try:
        os.makedirs(os.path.dirname(ALERT_FILE), exist_ok=True)
        with open(ALERT_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print("[健康看门狗] 告警文件写入失败: %s" % e)
    if not args.quiet:
        print(text)
    return 1 if alerts else 0


if __name__ == "__main__":
    sys.exit(main())
