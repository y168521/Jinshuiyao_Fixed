# -*- coding: utf-8 -*-
"""金水谣 · 审查统一入口（全局唯一调度器 · 所有触发方式都走这里）

所有审查触发入口（pre-commit / CI/CD / AI手动 / 服务器启动 / API）都必须调用本脚本，
确保：① 5步Pipeline执行顺序一致 ② metrics自动同步 ③ 审查完自动学习
④ 历史记录统一归档 ⑤ dashboard 数据源统一。

用法：
  python tools/run_review.py --quick        # 快速模式（ruff+AST+smoke，约5s，pre-commit用）
  python tools/run_review.py --full          # 完整模式（+wrapup+learning，约3min，收工用）
  python tools/run_review.py --files a.py,b.py   # 只审查指定文件
  python tools/run_review.py --json           # 仅输出JSON（API用）
  python tools/run_review.py --no-learn       # 不触发自学习（快速排查用）
"""
import json
import os
import sys
import time
import argparse
import traceback

# ─── 项目根 ───
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ─── 数据目录 ───
_REVIEW_DATA_DIR = os.path.join(_PROJECT_ROOT, "金水谣数据", "review")
_METRICS_FILE = os.path.join(_REVIEW_DATA_DIR, "review_metrics.json")
_HISTORY_FILE = os.path.join(_REVIEW_DATA_DIR, "review_history.jsonl")
os.makedirs(_REVIEW_DATA_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 全局统一调度：5步 Pipeline + metrics同步 + 自学习 + 历史归档
# ---------------------------------------------------------------------------
def run_review(mode="quick", files=None, enable_learning=True, json_output=False, is_full_audit=False):
    """
    全局唯一审查入口。

    Args:
        mode: "quick"（3步，pre-commit用） / "full"（5步，收工用）
        files: 只审查指定文件列表（可选）
        enable_learning: 审查完是否自动学习
        json_output: 是否只输出JSON

    Returns:
        dict: 结构化审查结果
    """
    from tools.review_report import run_quick_review, run_full_review

    start_ts = time.time()
    review_id = time.strftime("%Y%m%d_%H%M%S")

    # ── Step A: 执行 Pipeline ──
    try:
        if mode == "full":
            report = run_full_review(files=files)
        else:
            report = run_quick_review(files=files)
    except Exception as e:
        report = {
            "review_id": review_id,
            "mode": mode,
            "status": "ERROR",
            "error": f"{type(e).__name__}: {str(e)}",
            "traceback": traceback.format_exc(),
            "steps": [],
            "summary": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
            "duration_ms": int((time.time() - start_ts) * 1000),
        }

    report["review_id"] = review_id
    report["mode"] = mode
    report["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["duration_ms"] = int((time.time() - start_ts) * 1000)

    # 汇总各步问题数
    summary = {"P0": 0, "P1": 0, "P2": 0, "P3": 0, "total": 0}
    for step in report.get("steps", []):
        for issue in step.get("issues", []):
            sev = issue.get("severity", "P3")
            if sev in summary:
                summary[sev] += 1
                summary["total"] += 1
    report["summary"] = summary
    report["passed"] = summary["P0"] == 0 and summary["P1"] == 0

    # ── Step B: 同步 metrics ──
    _sync_metrics(report, is_full_audit=is_full_audit)

    # ── Step C: 归档历史 ──
    _archive_history(report)

    # ── Step D: 自学习（审查完自动吃结果优化模式库）──
    if enable_learning and report.get("status") != "ERROR":
        try:
            _trigger_learning(report)
            report["learning_applied"] = True
        except Exception as e:
            report["learning_error"] = f"{type(e).__name__}: {str(e)}"

    return report


def _sync_metrics(report, is_full_audit=False):
    """审查结果自动写入 metrics（全局唯一数据源，dashboard 只读它）。

    is_full_audit=True 表示整仓扫描（无 --files/--diff-only/--pr）：其 summary 的
    P0/P1 是「全仓库问题快照」而非「本次增量」，累加进累计计数器会重复计数
    （同一批仓库问题每次全扫都被 +1，导致 p1_total 虚高，见 T7）。故整仓审计
    只记录频次/耗时，不累加问题数；仅 scoped/diff 审查（pre-commit/CI/PR）才累加。
    """
    metrics = _load_metrics()
    metrics["total_reviews"] = metrics.get("total_reviews", 0) + 1

    # 各优先级累计（仅 scoped/diff 审查累加；整仓审计的 summary 是全仓库快照，不累加）
    if not is_full_audit:
        for sev in ["P0", "P1", "P2", "P3"]:
            key = f"total_{sev.lower()}"
            metrics[key] = metrics.get(key, 0) + report.get("summary", {}).get(sev, 0)

    # 通过率
    if report.get("passed"):
        metrics["passed_reviews"] = metrics.get("passed_reviews", 0) + 1
    total = metrics["total_reviews"]
    metrics["pass_rate"] = round(metrics.get("passed_reviews", 0) / total * 100, 1) if total else 0.0

    # 周统计（用于趋势图）
    today = time.strftime("%Y-%m-%d")
    weekly = metrics.get("weekly_stats", [])
    if not weekly or weekly[-1].get("date") != today:
        weekly.append({
            "date": today,
            "reviews": 0,
            "p0_total": 0, "p1_total": 0,
            "passed": 0,
        })
    weekly[-1]["reviews"] += 1
    if not is_full_audit:
        weekly[-1]["p0_total"] += report.get("summary", {}).get("P0", 0)
        weekly[-1]["p1_total"] += report.get("summary", {}).get("P1", 0)
    if report.get("passed"):
        weekly[-1]["passed"] += 1
    # 只保留最近30天
    metrics["weekly_stats"] = weekly[-30:]

    # 平均耗时
    durations = metrics.get("durations_ms", [])
    durations.append(report.get("duration_ms", 0))
    metrics["durations_ms"] = durations[-100:]
    metrics["avg_duration_ms"] = int(sum(durations) / len(durations)) if durations else 0

    metrics["last_review_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    metrics["last_review_id"] = report.get("review_id")

    # dashboard 专用字段（保持与前端一致）
    s = report.get("summary", {})
    metrics["p0_count"] = metrics.get("total_p0", 0)
    metrics["p1_count"] = metrics.get("total_p1", 0)
    metrics["p2_count"] = metrics.get("total_p2", 0)
    metrics["p3_count"] = metrics.get("total_p3", 0)
    # 健康评分：P0扣30分、P1扣10分、P2扣1分、P3扣0.1分，满分100
    p0 = s.get("P0", 0)
    p1 = s.get("P1", 0)
    p2 = s.get("P2", 0)
    p3 = s.get("P3", 0)
    raw_score = 100 - p0 * 30 - p1 * 10 - p2 * 1 - p3 * 0.1
    metrics["health_score"] = max(0, min(100, round(raw_score, 1)))

    _save_metrics(metrics)


def _archive_history(report):
    """归档审查历史（JSONL 追加式，用于趋势分析和回溯）。"""
    s = report.get("summary", {})
    p0, p1, p2, p3 = s.get("P0", 0), s.get("P1", 0), s.get("P2", 0), s.get("P3", 0)
    # 健康评分（同上公式，保持一致）
    raw_score = 100 - p0 * 30 - p1 * 10 - p2 * 1 - p3 * 0.1
    health_score = max(0, min(100, round(raw_score, 1)))
    # 建议
    if p0 > 0:
        recommendation = "立即修复P0阻断问题"
    elif p1 > 0:
        recommendation = "优先修复P1高优问题"
    elif p2 > 20:
        recommendation = "建议清理P2格式问题"
    else:
        recommendation = "代码质量良好，保持关注"
    archive = {
        "review_id": report.get("review_id"),
        "mode": report.get("mode"),
        "started_at": report.get("started_at"),
        "timestamp": report.get("started_at"),
        "duration_ms": report.get("duration_ms"),
        "summary": s,
        "p0": p0, "p1": p1, "p2": p2, "p3": p3,
        "health_score": health_score,
        "recommendation": recommendation,
        "passed": report.get("passed"),
        "status": report.get("status"),
    }
    try:
        with open(_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(archive, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _trigger_learning(report):
    """审查完自动触发自学习——把本次问题和模式库做匹配，更新置信度。"""
    try:
        from tools.review_learning import ReviewLearning
    except ImportError:
        return

    learner = ReviewLearning()
    learner.metrics["total_reviews"] = learner.metrics.get("total_reviews", 0) + 1

    # 把本次发现的问题和模式库做匹配，命中的增加命中计数
    for step in report.get("steps", []):
        for issue in step.get("issues", []):
            rule = issue.get("rule", "")
            # 找匹配的模式
            for pid, pat in learner.patterns.items():
                if rule and rule in pat.get("code_pattern", ""):
                    pat["hit_count"] = pat.get("hit_count", 0) + 1
                    pat["last_hit_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                # 标题/描述关键词匹配
                title = issue.get("message", "")
                if title and title[:20] in pat.get("title", ""):
                    pat["hit_count"] = pat.get("hit_count", 0) + 1

    try:
        learner._save_patterns()
        learner._save_metrics()
    except Exception:
        pass


def _load_metrics():
    if not os.path.isfile(_METRICS_FILE):
        return {"total_reviews": 0, "passed_reviews": 0, "pass_rate": 0.0,
                "total_p0": 0, "total_p1": 0, "total_p2": 0, "total_p3": 0,
                "weekly_stats": [], "durations_ms": [], "avg_duration_ms": 0}
    try:
        with open(_METRICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"total_reviews": 0}


def _save_metrics(metrics):
    try:
        with open(_METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _print_human_report(report):
    """人类可读的审查结果输出。"""
    s = report.get("summary", {})
    status = "✅ PASS" if report.get("passed") else "❌ FAIL"
    print(f"\n{'='*60}")
    print(f"  金水谣审查结果 · {report.get('mode')}模式 · {status}")
    print(f"  Review ID: {report.get('review_id')}  耗时: {report.get('duration_ms')}ms")
    print(f"{'='*60}")
    print(f"  P0: {s.get('P0',0)}  P1: {s.get('P1',0)}  P2: {s.get('P2',0)}  P3: {s.get('P3',0)}  总计: {s.get('total',0)}")

    for step in report.get("steps", []):
        issues = step.get("issues", [])
        if not issues:
            print(f"  [{step.get('step')}] ✅ 无问题 ({step.get('duration_ms',0)}ms)")
            continue
        p0_count = sum(1 for i in issues if i.get("severity") == "P0")
        p1_count = sum(1 for i in issues if i.get("severity") == "P1")
        print(f"  [{step.get('step')}] ⚠️  {len(issues)}个问题 (P0={p0_count}, P1={p1_count})")
        for issue in issues[:5]:
            sev = issue.get("severity", "P3")
            emoji = {"P0": "🔴", "P1": "🟠", "P2": "🟡", "P3": "🟢"}.get(sev, "⚪")
            fname = issue.get("file", "")
            if fname and fname.startswith(_PROJECT_ROOT):
                fname = fname[len(_PROJECT_ROOT)+1:]
            print(f"    {emoji} {sev} {fname}:{issue.get('line','?')} — {issue.get('message','')[:60]}")
        if len(issues) > 5:
            print(f"    ... 还有 {len(issues)-5} 个问题")

    if report.get("learning_applied"):
        print(f"\n  🧠 自学习已触发：模式库置信度已更新")
    print(f"  📊 metrics已同步：金水谣数据/review/review_metrics.json")
    print(f"  📜 历史已归档：金水谣数据/review/review_history.jsonl")
    print(f"{'='*60}\n")


def _resolve_files(arg):
    """把 --files 的逗号分隔路径统一解析为绝对路径。

    调用方可能在仓库根或 Jinshuiyao_Fixed 下运行，而各 step 的 cwd 不一致
    （ruff→仓库根，semgrep/AST→_PROJECT_ROOT）。统一成绝对路径可避免错位。
    相对路径依次尝试：当前目录 / _PROJECT_ROOT / 仓库根，命中即返回。"""
    import os as _os
    out = []
    for f in arg.split(","):
        f = f.strip()
        if not f:
            continue
        if _os.path.isabs(f):
            out.append(f)
            continue
        cands = [
            _os.path.abspath(f),
            _os.path.join(_PROJECT_ROOT, f),
            _os.path.join(_os.path.dirname(_PROJECT_ROOT), f),
        ]
        for c in cands:
            if _os.path.exists(c):
                out.append(_os.path.abspath(c))
                break
        else:
            out.append(_os.path.abspath(f))  # 兜底，交给下层报错
    return out


def main():
    parser = argparse.ArgumentParser(description="金水谣审查统一入口")
    parser.add_argument("--quick", action="store_true", help="快速模式（ruff+AST+smoke）")
    parser.add_argument("--full", action="store_true", help="完整模式（+wrapup+learning）")
    parser.add_argument("--files", help="只审查指定文件，逗号分隔")
    parser.add_argument("--json", action="store_true", help="仅输出JSON")
    parser.add_argument("--no-learn", action="store_true", help="不触发自学习")
    parser.add_argument("--diff-only", action="store_true",
                        help="只审查当前分支相对base的diff（CI用，视为scoped审计，累加metrics）")
    parser.add_argument("--pr", type=int, default=None,
                        help="审查指定PR号（预留/CI用，视为scoped审计，累加metrics）")
    args = parser.parse_args()

    mode = "full" if args.full else "quick"
    files = _resolve_files(args.files) if args.files else None
    enable_learning = not args.no_learn
    # scoped = 仅审变更（pre-commit 暂存 / --diff-only / --pr）；否则为整仓审计（快照不累加）
    scoped = bool(files) or args.diff_only or (args.pr is not None)
    is_full_audit = not scoped

    report = run_review(mode=mode, files=files, enable_learning=enable_learning, is_full_audit=is_full_audit)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_human_report(report)

    # 有 P0 就返回非零（供 pre-commit/CI 判断）
    if report.get("summary", {}).get("P0", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
