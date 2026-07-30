#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金水谣 · 操作留痕引擎
===================
自动记录所有重要操作，链式hash防篡改。

日志位置: 金水谣数据/log/审计轨迹.jsonl

事件类型:
  session_start  - 开工（ops.py --start）
  session_close  - 收工（ops.py --close）
  commit         - 提交（pre-commit hook）
  audit_pass     - gate.py --audit 通过
  audit_fail     - gate.py --audit 拦截
  gate_pass      - closeout_gate.py 通过
  gate_fail      - closeout_gate.py 拦截
  bypass         - 检测到 git --no-verify
  milestone      - 里程碑（手工标记）

用法:
  from tools.audit_trail import log_event, get_today_events, compliance_report

  log_event("commit", detail="更新彩票分析", files=["a.py","b.py"])
  events = get_today_events()
  report = compliance_report()
"""

import os
import json
import hashlib
import datetime
import subprocess
import sys

# GBK 安全输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
MODEL_DIR = os.path.dirname(ROOT_DIR)
LOG_DIR = os.path.join(ROOT_DIR, "金水谣数据", "log")
LOG_PATH = os.path.join(LOG_DIR, "审计轨迹.jsonl")
ZERO_HASH = "0" * 64

REPLAY_FILE = os.path.join(LOG_DIR, "审计轨迹回放.md")


def _ensure_log_dir():
    if not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)


def _get_last_hash():
    if not os.path.isfile(LOG_PATH):
        return ZERO_HASH
    try:
        with open(LOG_PATH, "rb") as f:
            for line in f:
                pass
            if line:
                entry = json.loads(line)
                return entry.get("hash", ZERO_HASH)
        return ZERO_HASH
    except Exception:
        return ZERO_HASH


def _calc_hash(prev_hash, entry_dict):
    raw = json.dumps(entry_dict, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256((prev_hash + raw).encode("utf-8")).hexdigest()


def _get_git_user():
    try:
        name = subprocess.check_output(
            ["git", "config", "user.name"], text=True
        ).strip()
        return name
    except Exception:
        return "未知"


def _get_git_commit_hash():
    try:
        h = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
        return h
    except Exception:
        return None


def log_event(event, detail="", files=None, milestone_category=""):
    _ensure_log_dir()
    prev_hash = _get_last_hash()
    now = datetime.datetime.now()
    entry = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "user": _get_git_user(),
        "event": event,
        "detail": detail,
        "files": files or [],
        "commit_hash": _get_git_commit_hash() or "",
        "milestone_category": milestone_category,
        "prev_hash": prev_hash,
    }
    entry["hash"] = _calc_hash(prev_hash, entry)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _read_all():
    if not os.path.isfile(LOG_PATH):
        return []
    entries = []
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def verify_chain():
    """验证 hash 链完整性，返回 (ok, broken_at)"""
    entries = _read_all()
    if not entries:
        return True, None
    prev = ZERO_HASH
    for i, e in enumerate(entries):
        expected = _calc_hash(prev, {k: v for k, v in e.items() if k != "hash"})
        if e.get("hash") != expected:
            return False, i
        prev = e["hash"]
    return True, None


def get_today_events():
    today = datetime.date.today().isoformat()
    entries = _read_all()
    return [e for e in entries if e.get("date") == today]


def get_date_events(date_str):
    entries = _read_all()
    return [e for e in entries if e.get("date") == date_str]


def get_recent_events(n=20):
    entries = _read_all()
    return entries[-n:]


def compliance_report(date_str=None):
    """生成全中文合规报告"""
    if not date_str:
        today = datetime.date.today().isoformat()
    else:
        today = date_str
    events = get_date_events(today) if date_str else get_today_events()
    user = _get_git_user()

    lines = [
        f"## 合规报告 — {today}",
        f"操作人: {user}",
        "",
    ]

    has_start = any(e["event"] == "session_start" for e in events)
    has_close = any(e["event"] == "session_close" for e in events)
    commits = [e for e in events if e["event"] == "commit"]
    gates = [e for e in events if e["event"] in ("gate_pass", "gate_fail")]
    audits = [e for e in events if e["event"] in ("audit_pass", "audit_fail")]
    bypasses = [e for e in events if e["event"] == "bypass"]

    lines.append("### 📋 今日流程")
    lines.append("")
    lines.append(f"- 开工令: {'[OK] 已执行' if has_start else '[!!] 未执行'}")
    lines.append(f"- 提交次数: {len(commits)} 次")
    lines.append(f"- 收工令: {'[OK] 已执行' if has_close else '[!!] 未执行'}")
    lines.append("")

    if bypasses:
        lines.append(f"### 违规绕过 ({len(bypasses)} 次)")
        lines.append("")
        for b in bypasses:
            lines.append(f"- {b['ts']} — {b['detail']}")
        lines.append("")

    if audits:
        fails = [a for a in audits if a["event"] == "audit_fail"]
        passes = [a for a in audits if a["event"] == "audit_pass"]
        lines.append(f"### 审查记录")
        lines.append("")
        lines.append(f"- gate.py --audit: {len(passes)} 次通过, {len(fails)} 次拦截")
        if fails:
            for f_ in fails:
                lines.append(f"  - [FAIL] {f_['ts']} — {f_['detail']}")
        lines.append("")

    if gates:
        g_fails = [g for g in gates if g["event"] == "gate_fail"]
        g_passes = [g for g in gates if g["event"] == "gate_pass"]
        lines.append(f"### 收工门禁")
        lines.append("")
        lines.append(f"- closeout_gate: {len(g_passes)} 次通过, {len(g_fails)} 次拦截")
        lines.append("")

    lines.append("---")
    ok = has_start and has_close and len(g_fails) == 0 if gates else (has_start or True)
    if has_start and has_close and (not gates or g_fails == 0):
        lines.append("**[OK] 结论: 今日流程完整，无违规**")
    elif has_start and not has_close:
        lines.append("**[WARN] 结论: 已开工但未收工，请在收工前执行 ops.py --close**")
    else:
        lines.append("**[WARN] 结论: 流程不完整，请检查上述标记项**")

    return "\n".join(lines)


def write_replay():
    """写一个纯中文的当日回放到 审计轨迹回放.md"""
    events = get_today_events()
    if not events:
        text = f"# 今日操作回放 — {datetime.date.today().isoformat()}\n\n今日暂无操作记录。\n"
    else:
        text = [
            f"# 今日操作回放 — {datetime.date.today().isoformat()}",
            "",
        ]
        user = events[0].get("user", "未知")
        text.append(f"操作人: {user}")
        text.append("")
        text.append("## 📜 操作时间线")
        text.append("")
        icons = {
            "session_start": "🚀",
            "session_close": "🏁",
            "commit": "📝",
            "audit_pass": "✅",
            "audit_fail": "❌",
            "gate_pass": "✅",
            "gate_fail": "❌",
            "bypass": "⚠️",
            "milestone": "🏆",
        }
        for e in events:
            icon = icons.get(e["event"], "•")
            detail = e.get("detail", "")
            files = e.get("files", [])
            line = f"{icon} **{e['time']}** — {e['event']}: {detail}"
            text.append(line)
            if files:
                text.append(f"   └ 文件: {', '.join(files[:5])}")
        text.append("")
        text.append("---")
        text.append("")
        text.append(compliance_report())
    _ensure_log_dir()
    with open(REPLAY_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(text) if isinstance(text, list) else text)


def replay_today():
    """打印今日操作时间线到控制台"""
    events = get_today_events()
    if not events:
        print("今日暂无操作记录。")
        return
    print(f"\n{'='*60}")
    print(f"  今日操作时间线 — {datetime.date.today().isoformat()}")
    print(f"{'='*60}")
    user = events[0].get("user", "未知")
    print(f"  操作人: {user}")
    print(f"{'─'*60}")
    icons = {
        "session_start": "🚀",
        "session_close": "🏁",
        "commit": "📝",
        "audit_pass": "✅",
        "audit_fail": "❌",
        "gate_pass": "✅",
        "gate_fail": "❌",
        "bypass": "⚠️",
        "milestone": "🏆",
    }
    for e in events:
        icon = icons.get(e["event"], "•")
        detail = e.get("detail", "")
        files = e.get("files", [])
        icon_asc = {"🚀":"[START]", "🏁":"[CLOSE]", "📝":"[COMMIT]",
                     "✅":"[PASS]", "❌":"[FAIL]", "⚠️":"[WARN]", "🏆":"[MILESTONE]"}
        i = icon_asc.get(icon, icon)
        print(f"  {i} {e['time']} — {detail}")
        if files:
            print(f"     + 文件: {', '.join(files[:3])}")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="金水谣操作留痕引擎")
    parser.add_argument("--log", nargs="+", help="记录事件: --log <event> <detail>")
    parser.add_argument("--compliance", action="store_true", help="生成今日合规报告")
    parser.add_argument("--replay", action="store_true", help="查看今日操作时间线")
    parser.add_argument("--verify", action="store_true", help="验证 hash 链完整性")
    args, extra = parser.parse_known_args()

    if args.log:
        event = args.log[0]
        detail = " ".join(args.log[1:]) if len(args.log) > 1 else ""
        log_event(event, detail)
        print(f"[audit] 已记录: {event} — {detail}")

    if args.compliance:
        print(compliance_report())

    if args.replay:
        replay_today()

    if args.verify:
        ok, broken = verify_chain()
        if ok:
            print("[audit] [OK] Hash 链完整，日志未被篡改")
        else:
            print(f"[audit] [FAIL] Hash 链在第 {broken} 条断裂，日志可能被篡改！")

    if not any([args.log, args.compliance, args.replay, args.verify]):
        parser.print_help()
