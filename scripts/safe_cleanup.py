#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【道衍推导·JS-20260727-24】
  阴阳：阳=清理(主动减负)；阴=七类细分+三级闸门+SALVAGE(守底，绝不误删独有)。
  天地人：天=规划"先扫后删"；地=隔离(仓库外salvage兜底)；人=复盘(误删可找回)。
  知止：独有/活跃/未提交文件绝不经--confirm-unique确认不删；绝不宽指令整目录rm。

safe_cleanup.py — 金水谣文件清理安全框架 (JS-20260727-14)
========================================================
彻底取代"宽指令 rm 整目录"式的粗糙清理。

事故复盘（为什么要这个脚本）：
  一次常规清理中，某个会话把"清理金水谣数据/"理解成整目录 rm，
  没区分独有文档 / 运行时杂物 / 活跃文档，导致一份从未提交 git 的
  独有手册被循环删除、永久丢失。根因 = 删除环节"没细致划分 + 无闸门 + 无兜底"。

本脚本用四道保险根除该漏洞：
  ① 只读扫描先行 — 绝不先删，先看清再决定。
  ② 七类精细划分 — 每文件归入一类，区分价值高低。
  ③ SALVAGE 兜底 — 删前把拟删文件全拷到仓库外保险目录(时间戳)，循环删/误删都能找回。
  ④ 三级闸门 — 低风险自动(需--apply)；中风险需--apply；高风险(独有/活跃/未提交)需--confirm-unique显式确认。

七类定义：
  A runtime_junk  运行时杂物(*.log / *_audit.log* / _kb_backup_*.json / watchdog* / *.bak.* / video_cache)
                  → 已被 gitignore，删了不影响库。闸门=自动(需--apply)。
  B conflict_res  冲突残留(*冲突* / *.orig / *.rej / *.mine / *.theirs)
                  → 已被 gitignore，合并残留。闸门=自动(需--apply)。
  C dead          死文件：被 git 跟踪、全仓零引用、无权威副本。
                  → 如陈旧重复 ai_decisions.md。闸门=需--apply(仍先salvage)。
  D duplicate     冗余副本：仓库内存在同名权威文件(另一处)。
                  → 删非权威副本。闸门=需--apply(确认权威源完好)。
  E unique_doc    独有文档：人读知识(.md/.html)，无引用、无权威副本、非杂物。
                  → 高价值，误删难恢复。闸门=FORBIDDEN，除非 --confirm-unique。
  F active_ref    活跃引用：被代码/索引引用。
                  → 系统依赖，删了会崩。闸门=FORBIDDEN，除非 --confirm-unique。
  G untracked_new 未提交新文件：git 未跟踪且未忽略。
                  → 可能独有/可能垃圾，无法判断。闸门=FORBIDDEN，除非 --confirm-unique。

安全硬约束（任何模式都生效）：
  - 目标必须在 git 仓库内（禁止清系统/个人目录）。
  - 绝不触碰 .git/ 本身。
  - 不递归 rm：只逐文件删除"已分类且已通过闸门"的项，结构上杜绝整目录误删。
  - 默认 DRY-RUN：不传 --apply 只打印分类与计划，零副作用。

用法：
  py -3.14 scripts/safe_cleanup.py <path>                      # 只读分类报告(默认)
  py -3.14 scripts/safe_cleanup.py <path> --apply              # 执行低风险+中风险删除
  py -3.14 scripts/safe_cleanup.py <path> --apply --confirm-unique  # 含高风险的独有/活跃/未提交
  py -3.14 scripts/safe_cleanup.py <path> --json               # 机器可读输出
退出码：0=按计划完成/无删除项；2=有高风险项被拒绝(需--confirm-unique)；3=安全硬约束违规。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

# ---------- 路径锚点 ----------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))  # 模型/
SALVAGE_BASE = os.path.abspath(os.path.join(REPO_ROOT, "..", "_cleanup_salvage"))  # 仓库外

# ---------- 七类元信息 ----------
CATEGORIES = {
    "runtime_junk": {"tier": "auto",     "label": "运行时杂物",   "risk": "低"},
    "conflict_res": {"tier": "auto",     "label": "冲突残留",     "risk": "低"},
    "dead":         {"tier": "apply",    "label": "死文件",       "risk": "中"},
    "duplicate":    {"tier": "apply",    "label": "冗余副本",     "risk": "中"},
    "unique_doc":   {"tier": "confirm",  "label": "独有文档",     "risk": "高"},
    "active_ref":   {"tier": "confirm",  "label": "活跃引用",     "risk": "高"},
    "untracked_new":{"tier": "confirm",  "label": "未提交新文件", "risk": "高"},
}

RISK_ORDER = {"低": 0, "中": 1, "高": 2}

# ---------- 杂物/冲突正则 ----------
RUNTIME_RE = re.compile(
    r"(\.log$|\.logl$|\.bak\.\d+$|_audit\.log|watchdog|"
    r"_kb_backup_.*\.json$|video_cache|__pycache__|\.tmp$|~$)"
)
CONFLICT_RE = re.compile(r"(冲突|\.orig$|\.rej$|\.mine$|\.theirs$|MERGE_)")


# ---------- git 辅助 ----------
def _run(cmd, cwd):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
        return (p.returncode, p.stdout or "", p.stderr or "")
    except Exception as e:  # noqa
        return (-1, "", str(e))


def is_tracked(repo, rel):
    rc, _, _ = _run(["git", "ls-files", "--error-unmatch", "--", rel], repo)
    return rc == 0


def is_ignored(repo, rel):
    rc, _, _ = _run(["git", "check-ignore", "-q", "--", rel], repo)
    return rc == 0


def find_references(repo, stem, exclude_rel):
    """全仓搜 stem 是否出现在代码/文档引用里（排除自身与 obsidian-vault 副本）。"""
    rc, out, _ = _run(["git", "grep", "-l", "--untracked", stem], repo)
    if rc != 0 or not out.strip():
        return []
    hits = []
    for line in out.splitlines():
        path = line.split(":", 1)[0] if ":" in line else line
        if path == exclude_rel:
            continue
        if "obsidian-vault" in path:
            continue
        hits.append(path)
    return hits


def find_duplicates(repo, basename, exclude_rel):
    rc, out, _ = _run(["git", "ls-files"], repo)
    if rc != 0:
        return []
    return [f for f in out.splitlines()
            if os.path.basename(f) == basename and f != exclude_rel]


# ---------- 分类核心 ----------
def classify_file(repo, abs_path, rel):
    name = os.path.basename(abs_path)
    stem = os.path.splitext(name)[0]
    tracked = is_tracked(repo, rel)
    ignored = is_ignored(repo, rel)

    # 1) 冲突残留
    if CONFLICT_RE.search(name):
        return "conflict_res", "匹配冲突残留命名", []
    # 2) 运行时杂物
    if RISK_ORDER and RUNTIME_RE.search(name):
        return "runtime_junk", "匹配运行时杂物命名", []
    # 3) 活跃引用（被代码/索引引用 → 最高保护）
    refs = find_references(repo, stem, rel)
    if refs:
        return "active_ref", f"被引用: {', '.join(refs[:3])}{'…' if len(refs) > 3 else ''}", refs
    # 4) 冗余副本（仓库内有同名权威文件）
    dups = find_duplicates(repo, name, rel)
    if dups:
        return "duplicate", f"存在权威副本: {', '.join(dups[:3])}", dups
    # 5) 未提交新文件（未跟踪且未忽略）
    if not tracked and not ignored:
        return "untracked_new", "git 未跟踪且未忽略，价值未知", []
    # 6) 独有文档（人读知识，零引用，无副本，非杂物）
    if name.lower().endswith((".md", ".html", ".txt", ".docx", ".pdf")) and tracked:
        return "unique_doc", "人读知识文档，零引用且无副本", []
    # 7) 死文件（跟踪、零引用、无副本、非上述）
    if tracked:
        return "dead", "git 跟踪但全仓零引用、无副本", []
    # 兜底
    return "untracked_new", "未分类→按高风险未提交处理", []


# ---------- 收集目标 ----------
def collect_targets(target_abs):
    items = []
    if os.path.isfile(target_abs):
        items.append(target_abs)
    elif os.path.isdir(target_abs):
        for root, dirs, files in os.walk(target_abs):
            # 绝不进 .git
            dirs[:] = [d for d in dirs if d != ".git"]
            for f in files:
                items.append(os.path.join(root, f))
    return items


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser(description="金水谣安全删除框架（精细划分+闸门+兜底）")
    ap.add_argument("path", help="目标文件或目录（必须在 git 仓库内）")
    ap.add_argument("--apply", action="store_true", help="执行删除（默认仅 dry-run 报告）")
    ap.add_argument("--confirm-unique", action="store_true",
                    help="允许删除高风险类(独有/活跃/未提交)，需同时有 --apply")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    target_abs = os.path.abspath(args.path)

    # === 安全硬约束 ===
    if not os.path.exists(target_abs):
        print(f"[安全] 路径不存在: {target_abs}", file=sys.stderr)
        return 3
    # 必须在仓库内
    try:
        rel0 = os.path.relpath(target_abs, REPO_ROOT)
    except ValueError:
        rel0 = ".."
    if rel0.startswith("..") or rel0.startswith("\\") or (
        os.path.splitdrive(target_abs)[0].upper() != os.path.splitdrive(REPO_ROOT)[0].upper()
    ):
        print(f"[安全] 拒绝：目标在仓库外（{target_abs}），禁止清理系统/个人目录。", file=sys.stderr)
        return 3
    # 不碰 .git
    if ".git" in [p for p in rel0.split(os.sep)]:
        print("[安全] 拒绝：目标位于 .git/ 内。", file=sys.stderr)
        return 3

    targets = collect_targets(target_abs)
    results = []
    for ab in targets:
        rel = os.path.relpath(ab, REPO_ROOT).replace(os.sep, "/")
        cat, reason, refs = classify_file(REPO_ROOT, ab, rel)
        results.append({
            "rel": rel,
            "cat": cat,
            "cat_label": CATEGORIES[cat]["label"],
            "tier": CATEGORIES[cat]["tier"],
            "risk": CATEGORIES[cat]["risk"],
            "reason": reason,
            "refs": refs,
            "exists": os.path.exists(ab),
        })

    # 排序：风险高→低，便于审阅
    results.sort(key=lambda r: (-RISK_ORDER[r["risk"]], r["cat"], r["rel"]))

    # === DRY-RUN 报告 ===
    if not args.apply:
        if args.json:
            print(json.dumps({"mode": "dry-run", "target": target_abs,
                              "files": results}, ensure_ascii=False, indent=2))
        else:
            print(f"═══ 安全删除 · DRY-RUN（仅报告，未删除）═══")
            print(f"目标: {target_abs}")
            print(f"扫描文件数: {len(results)}")
            print(f"{'分类':<10}{'风险':<4}{'文件':<50}{'判定依据'}")
            print("─" * 100)
            for r in results:
                print(f"{r['cat_label']:<10}{r['risk']:<4}{r['rel'][:48]:<50}{r['reason'][:40]}")
            print("─" * 100)
            high = [r for r in results if r["tier"] == "confirm"]
            mid = [r for r in results if r["tier"] == "apply"]
            low = [r for r in results if r["tier"] == "auto"]
            print(f"高风险(需--confirm-unique): {len(high)}  中风险(需--apply): {len(mid)}  低风险(自动): {len(low)}")
            print("下一步: 低风险→ `safe_cleanup.py <path> --apply`；中风险同上；高风险加 `--confirm-unique`。")
        return 0

    # === APPLY：先 SALVAGE 兜底，再按闸门删 ===
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    salvage_dir = os.path.join(SALVAGE_BASE, ts)
    os.makedirs(salvage_dir, exist_ok=True)

    deleted, refused, salvaged = [], [], []
    for r in results:
        ab = os.path.join(REPO_ROOT, r["rel"])
        if not os.path.exists(ab):
            continue
        tier = r["tier"]
        # 闸门判定
        if tier == "confirm" and not args.confirm_unique:
            refused.append(r)
            continue
        # SALVAGE：删前必拷到仓库外保险目录
        dst = os.path.join(salvage_dir, r["rel"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copy2(ab, dst)
            salvaged.append(r["rel"])
        except Exception as e:  # noqa
            print(f"[警告] salvage 失败 {r['rel']}: {e}", file=sys.stderr)
            refused.append(r)
            continue
        # 删除（tracked 用 git rm，否则直接删）
        try:
            if is_tracked(REPO_ROOT, r["rel"]):
                _run(["git", "rm", "-q", "--", r["rel"]], REPO_ROOT)
            else:
                os.remove(ab)
            deleted.append(r["rel"])
        except Exception as e:  # noqa
            print(f"[警告] 删除失败 {r['rel']}: {e}", file=sys.stderr)
            refused.append(r)

    # === 验证报告 ===
    print(f"═══ 安全删除 · 执行完成 ═══")
    print(f"保险副本: {salvage_dir}  (已存 {len(salvaged)} 份，循环删/误删可在此找回)")
    print(f"已删除: {len(deleted)}")
    for d in deleted:
        print(f"  ✂ {d}")
    if refused:
        print(f"已拒绝(高风险未确认): {len(refused)}")
        for r in refused:
            print(f"  🛡 {r['rel']}  [{r['cat_label']}]")
    # 删后重扫：确认被删项确实消失
    still_there = [r["rel"] for r in results if r["rel"] in deleted and os.path.exists(os.path.join(REPO_ROOT, r["rel"]))]
    if still_there:
        print(f"[异常] 以下计划删除项仍存在于磁盘: {still_there}")
    print("提示: 已删除的 tracked 文件需 `git commit` 入库；建议单独提交、勿与独有文档删除混批。")
    return 2 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
