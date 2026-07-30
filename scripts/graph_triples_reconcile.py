# -*- coding: utf-8 -*-
"""GraphRAG 三元组一致性调和 (graph_triples_reconcile.py)
==========================================================

定期重算 knowledge/graph_triples.json 的顶层 sources 派生字段，
与现有 sources 比对；发现失配则原子修正写回。

设计对齐项目铁律与经验底座（见 金水谣数据/自动化Skill经验底座_成败案例库.md）：
  - F9：知识库清理致不一致（sources 失配）→ 写共享 JSON 先重算派生字段；加锁。
  - MEMORY 第4条：sources 必须由 triples 派生；写入复用共享 _TRIPLE_STORE_LOCK，
    且用 os.replace 原子写防半写。
  - 维度二 GraphRAG 衰减修复：定期调和，防长周期（如第100天）漂移。

本脚本**复用** knowledge/triple_store 的 load_triple_store / recompute_sources /
save_triple_store，与 server 写库走同一套基础设施，遵循同一铁律。

安全模型（很重要，避免"越修越坏"）：
  1. 默认只读检查，仅生成报告；加 --fix 才在失配时原子修正写回。
  2. --fix 仅在「triples 非空 且 仅 sources 失配」时写回，绝不因 triples 为空而清空库。
     （空库是健康空库或 load 回退空库，reconcile 不应覆盖）。
  3. --fix 写回前先备份当前文件为 graph_triples.json.reconcile.bak。
  4. 修正窗口极小：fix 时重新 load 最新 → 立即 save（save 内部 recompute + 原子 os.replace），
     server 写路径自愈，下次写自动重算。
  5. 本项目 triple 写者仅为 server 单进程内多线程（已用进程内 _TRIPLE_STORE_LOCK 保护）；
     reconcile 作为低频外部维护，遵循「只读比对 + 必要时原子替换」即可。

用法：
  python graph_triples_reconcile.py            # 只读检查，生成 HTML/JSON 报告
  python graph_triples_reconcile.py --fix      # 失配时原子修正写回
  python graph_triples_reconcile.py --quiet    # 仅输出一行摘要（供自动化调度判读）

退出码：0 = 一致（健康）；1 = 发现失配（无论是否已修正，供调度判"需关注"）。
"""

import os
import sys
import json
import time
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)  # Jinshuiyao_Fixed
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from knowledge.triple_store import (
    load_triple_store,
    recompute_sources,
    save_triple_store,
    triple_store_path,
)

ROOT = os.path.dirname(PROJECT_ROOT)  # 模型/
REPORT_HTML = os.path.join(ROOT, "金水谣数据", "graph_triples_reconcile_report.html")
REPORT_JSON = os.path.join(ROOT, "金水谣数据", "graph_triples_reconcile_report.json")
HISTORY_FILE = os.path.join(ROOT, "金水谣数据", "log", "graph_triples_reconcile_history.json")
HISTORY_KEEP = 90


def log(msg):
    print("[{0}] {1}".format(time.strftime("%H:%M:%S"), msg))


def compute_expected(triples):
    """基于 triples 重新派生期望的 sources（不污染原 store）。"""
    probe = {"triples": list(triples)}
    recompute_sources(probe)
    return probe["sources"]


def diff_sources(current, expected):
    """比对 current / expected sources，返回失配明细列表。"""
    mismatches = []
    keys = set(current.keys()) | set(expected.keys())
    for k in sorted(keys):
        c = (current.get(k) or {}).get("triples", 0)
        e = (expected.get(k) or {}).get("triples", 0)
        if c != e:
            mismatches.append({"source": k, "current": c, "expected": e})
    return mismatches


def build_html(report):
    status_cls = "ok" if report["healthy"] else "bad"
    status_label = "一致（健康）" if report["healthy"] else "失配（需关注）"
    op_label = report["operation"]

    rows = []
    for m in report["mismatches"]:
        rows.append(
            "<tr><td>{src}</td><td class='num'>{cur}</td><td class='num'>{exp}</td></tr>".format(
                src=m["source"], cur=m["current"], exp=m["expected"]
            )
        )
    mismatch_block = (
        "<p class='warn'>发现 {n} 处 sources 计数失配：</p>"
        "<table><thead><tr><th>来源 source</th><th>当前 triples</th><th>期望 triples</th></tr></thead>"
        "<tbody>{rows}</tbody></table>".format(n=len(report["mismatches"]), rows="".join(rows))
        if report["mismatches"]
        else "<p class='ok'>未检测到 sources 计数失配。</p>"
    )

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>GraphRAG 三元组一致性调和报告</title>
<style>
 body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:24px;color:#1a1a1a;background:#fff}}
 h1{{font-size:20px}} .meta{{color:#666;font-size:13px;margin-bottom:16px}}
 .status{{display:inline-block;padding:6px 14px;border-radius:6px;font-weight:600;color:#fff}}
 .ok{{background:#2e7d32}} .bad{{background:#d32f2f}}
 .card{{border:1px solid #e0e0e0;border-radius:8px;padding:16px;margin:14px 0}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left}}
 th{{background:#f5f5f5}} .num{{text-align:right;font-variant-numeric:tabular-nums}}
 .ok{{color:#2e7d32}} .warn{{color:#d32f2f;font-weight:600}}
 .note{{font-size:12px;color:#666;line-height:1.6}}
</style></head><body>
<h1>GraphRAG 三元组一致性调和报告</h1>
<div class="meta">生成时间：{ts} &nbsp;|&nbsp; 文件：{path}</div>
<div class="card">
  <p>三元组总数：<b>{nt}</b> &nbsp;|&nbsp; 当前 sources 数：<b>{ns_cur}</b> &nbsp;|&nbsp; 期望 sources 数：<b>{ns_exp}</b></p>
  <p>一致性状态：<span class="status {cls}">{label}</span></p>
  <p>本次操作：<b>{op}</b></p>
</div>
<div class="card">
  <h3>sources 比对</h3>
  {mismatch}
</div>
<div class="card note">
  <p>机制说明：sources 为 triples 的派生元数据（按 source 聚合三元组计数与抽取时间区间）。
  本脚本复用 knowledge/triple_store 的 recompute_sources + 原子 os.replace，与 server 写库同源。
  默认只读检查，仅 --fix 在「triples 非空且仅 sources 失配」时原子修正，绝不清空库。</p>
</div>
</body></html>
""".format(
        ts=report["generated_at"],
        path=report["path"],
        nt=report["triples_count"],
        ns_cur=report["current_sources_count"],
        ns_exp=report["expected_sources_count"],
        cls=status_cls,
        label=status_label,
        op=op_label,
        mismatch=mismatch_block,
    )


def main():
    ap = argparse.ArgumentParser(description="GraphRAG 三元组一致性调和")
    ap.add_argument("--fix", action="store_true", help="失配时原子修正写回（默认只读）")
    ap.add_argument("--quiet", action="store_true", help="仅输出一行摘要")
    args = ap.parse_args()

    path = triple_store_path()
    store = load_triple_store()
    triples = store.get("triples", []) or []
    current = store.get("sources", {}) or {}
    expected = compute_expected(triples)
    mismatches = diff_sources(current, expected)
    healthy = len(mismatches) == 0

    fixed = False
    if (not healthy) and args.fix:
        # 安全闸：仅在 triples 非空（原文库有数据）时修正，避免清空回退空库
        if len(triples) > 0:
            # 写前备份
            try:
                shutil.copy2(path, path + ".reconcile.bak")
            except OSError:
                pass
            # 重新 load 最新，缩短与 server 并发窗口，立即原子写回
            store = load_triple_store()
            save_triple_store(store)  # 内部 recompute_sources + os.replace
            fixed = True
            # 复检
            store2 = load_triple_store()
            mismatches_after = diff_sources(
                store2.get("sources", {}) or {},
                compute_expected(store2.get("triples", []) or []),
            )
            healthy = len(mismatches_after) == 0
        else:
            # 空库：不修正，标记异常供人工核查
            if not args.quiet:
                log("[WARN] triples 为空，疑似回退空库，跳过修正，请人工核查")

    operation = (
        "已原子修正写回（备份 graph_triples.json.reconcile.bak）"
        if fixed
        else ("只读检查（未修正）" if (not healthy) else "只读检查（一致，无需修正）")
    )

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "path": path,
        "triples_count": len(triples),
        "current_sources_count": len(current),
        "expected_sources_count": len(expected),
        "healthy": healthy,
        "mismatches": mismatches,
        "fixed": fixed,
        "operation": operation,
        "mode": "fix" if args.fix else "check",
    }

    # 写报告
    try:
        with open(REPORT_JSON, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        with open(REPORT_HTML, "w", encoding="utf-8") as f:
            f.write(build_html(report))
    except OSError as e:
        log("[ERR] 报告写入失败: %s" % e)

    # 历史
    try:
        hist = []
        if os.path.isfile(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                hist = json.load(f)
        hist.append({
            "ts": report["generated_at"],
            "triples": len(triples),
            "healthy": healthy,
            "mismatches": len(mismatches),
            "fixed": fixed,
            "mode": report["mode"],
        })
        hist = hist[-HISTORY_KEEP:]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
    except (OSError, json.JSONDecodeError):
        pass

    if not args.quiet:
        log("三元组 %d 条 | sources 当前 %d / 期望 %d | 失配 %d | %s" % (
            len(triples), len(current), len(expected), len(mismatches), operation))
        if mismatches:
            for m in mismatches[:20]:
                log("  失配: %s 当前=%s 期望=%s" % (m["source"], m["current"], m["expected"]))

    # 退出码：失配=1（供调度判"需关注"），一致=0
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
