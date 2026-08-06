#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session_coordinator.py — 多会话 / 多 AI 接力的「同频·共识」协调器
=====================================================================
道衍推导（JS-20260727-17）：
  阴阳两仪：阳 = 并发协作（多个会话并行干活）；阴 = 互斥租约（改共享知识前先占锁）。
            → 无阴之阳 = 并发互删 / 互覆盖（本次循环删目录 + 日志被截短事故的根）。
  天地人三才：
    天 = 前瞻规划：本协议本身就是「改共享知识必须先达成共识」的规划（为之于未有）。
    地 = 执行隔离：文件级 advisory lease，把共享可变文件圈进保护范围（隔）。
    人 = 复盘迭代：心跳超时自愈 + 看板可见，谁在干啥一目了然（反事实自检）。
  知止：被保护的知识文件（总索引 / 决策卡 / 日志 / MEMORY）绝不允许无锁裸写。

设计：轻量文件租约（advisory lease），零新依赖、不依赖中心服务。
      nutstore 跨设备同步下，这是现实最稳的「尽力共识」；配合 append-only 纪律（#2）逼近强一致。
局限（诚实声明）：文件租约不能 100% 消除网络分区下的同时写；
      故「占锁 + append-only + 心跳自愈」三层组合，把冲突概率压到极低，且冲突可被发现、可回滚。
=====================================================================
"""
import argparse
import json
import os
import sys
import time
import ctypes
import platform
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent          # Jinshuiyao_Fixed/scripts -> 模型/
CLAIM_PATH = REPO_ROOT / ".workbuddy" / "session_claim.json"

STALE_SECS = 1800                            # 30 分钟无心跳 = 过期，可被抢（防死锁占坑）
# 陈旧锁快速接管阈值（JS-20260730-04 P2-4）：正常持有者每次写前都会 acquire/
# heartbeat 刷新心跳，600s 无心跳即为异常滞留（曾发生 brain_state.json 被持锁
# 1104s 未释放、卡住后续写入）。不影响正常短锁（短锁心跳新鲜，不会触发）。
STALE_TAKEOVER_SECS = 600
DEFAULT_HOLDER = f"{platform.node()}@{os.getpid()}"

# 受保护的共享知识文件：改前必须占锁共识（知止）
# JS-20260806-02 补全：纳入 经验收集箱/AI协作交接中心/金水谣_契（与 closeout_gate 三件套 + 契 对齐）
PROTECTED_REL = [
    "工作留痕总索引.md",
    "Jinshuiyao_Fixed/金水谣数据/log/ai_decisions.md",
    "Jinshuiyao_Fixed/金水谣数据/log/经验收集箱.md",
    "AI协作交接中心.md",
    "金水谣_契.md",
    ".workbuddy/memory/MEMORY.md",
]


def protected_files():
    files = [REPO_ROOT / p for p in PROTECTED_REL]
    today = datetime.now().strftime("%Y-%m-%d")
    files.append(REPO_ROOT / ".workbuddy" / "memory" / f"{today}.md")
    return [f for f in files if f.exists()]


def _pid_alive(pid):
    """跨平台判断进程是否存活（Windows 用 ctypes，Unix 用 os.kill 0）。"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if platform.system() == "Windows":
        try:
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_INFORMATION = 0x0400
            h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if h == 0:
                return False
            ec = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(h, ctypes.byref(ec))
            kernel32.CloseHandle(h)
            return ec.value == 259          # STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _now():
    return time.time()


def _read_claim():
    if not CLAIM_PATH.exists():
        return None
    try:
        return json.loads(CLAIM_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_claim(claim):
    CLAIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLAIM_PATH.write_text(json.dumps(claim, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_claim():
    if CLAIM_PATH.exists():
        try:
            CLAIM_PATH.unlink()
        except Exception:
            pass


def acquire(intent, holder=DEFAULT_HOLDER, stale_secs=STALE_SECS, wait_secs=0, poll=2):
    """占锁。空闲/过期/持有者已死 → 抢到；被他者活占且未到等待上限 → 抛错。"""
    deadline = _now() + max(0, wait_secs)
    while True:
        claim = _read_claim()
        if claim is None:
            new = _fresh_claim(holder, intent)
            _write_claim(new)
            return new
        is_mine = claim.get("holder") == holder
        lock_age = _now() - claim.get("heartbeat", 0)
        stale = lock_age > stale_secs
        if is_mine:
            claim["heartbeat"] = _now()
            claim["intent"] = intent
            _write_claim(claim)
            return claim
        # 陈旧锁自动过期（JS-20260730-04 P2-4）：
        #  1) 同机持有进程已死 → 立即接管（仅当 holder 主机名 == 本机，
        #     防止 nutstore 跨设备同步下误判他机存活进程为死锁）；
        #  2) 心跳超过快速接管阈值（600s）→ 视为异常滞留，接管；
        #  3) 心跳超过 STALE_SECS（30min）→ 原有自愈逻辑。
        holder_host = str(claim.get("holder", "")).rsplit("@", 1)[0]
        same_host = holder_host == platform.node()
        holder_dead = same_host and not _pid_alive(claim.get("pid"))
        if stale or holder_dead or lock_age > STALE_TAKEOVER_SECS:
            new = _fresh_claim(holder, intent)
            _write_claim(new)
            return new
        if _now() >= deadline:                 # 被他者新鲜持有，等不及
            raise RuntimeError(
                f"无法占锁: 被 {claim['holder']} 持有 (intent={claim.get('intent')}, "
                f"锁龄={int(_now()-claim.get('heartbeat',0))}s)"
            )
        time.sleep(poll)


def _fresh_claim(holder, intent):
    return {
        "holder": holder,
        "pid": os.getpid(),
        "intent": intent,
        "acquired_at": datetime.now().isoformat(timespec="seconds"),
        "heartbeat": _now(),
        "protected": [str(f) for f in protected_files()],
    }


def release(holder=DEFAULT_HOLDER, force=False):
    claim = _read_claim()
    if claim is None:
        return True
    if force or claim.get("holder") == holder:
        _clear_claim()
        return True
    return False


def heartbeat(holder=DEFAULT_HOLDER):
    claim = _read_claim()
    if claim and claim.get("holder") == holder:
        claim["heartbeat"] = _now()
        _write_claim(claim)
        return True
    return False


def status():
    claim = _read_claim()
    if not claim:
        return ("【同频看板】当前无会话占锁，可自由开工（但改受保护文件前仍需 acquire 占锁共识）。")
    age = int(_now() - claim.get("heartbeat", 0))
    stale = age > STALE_SECS
    return (
        f"【同频看板】持有者={claim['holder']} | pid={claim.get('pid')} | "
        f"意图={claim.get('intent')} | 锁龄={age}s{' [过期]' if stale else ''} | "
        f"保护文件={len(claim.get('protected', []))} 份"
    )


def main():
    ap = argparse.ArgumentParser(description="多会话同频·共识协调器（advisory lease + 看板）")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    a_acq = sub.add_parser("acquire")
    a_acq.add_argument("--intent", required=True, help="本次要做什么，例如 '编辑总索引'")
    a_acq.add_argument("--holder", default=DEFAULT_HOLDER, help="会话标识，默认 主机@pid")
    a_acq.add_argument("--wait", type=int, default=0, help="抢不到时最多等待秒数")
    a_rel = sub.add_parser("release")
    a_rel.add_argument("--holder", default=DEFAULT_HOLDER)
    a_rel.add_argument("--force", action="store_true", help="强制释放（无论持有者是谁）")
    a_hb = sub.add_parser("heartbeat")
    a_hb.add_argument("--holder", default=DEFAULT_HOLDER)
    sub.add_parser("protect")              # 列出受保护文件
    args = ap.parse_args()

    if args.cmd == "status":
        print(status())
    elif args.cmd == "acquire":
        try:
            acquire(args.intent, args.holder, wait_secs=args.wait)
            print("占锁成功 →", status())
        except RuntimeError as e:
            print("占锁失败 →", e)
            sys.exit(1)
    elif args.cmd == "release":
        print("释放结果:", release(args.holder, force=getattr(args, "force", False)))
    elif args.cmd == "heartbeat":
        print("心跳刷新:", heartbeat(args.holder))
    elif args.cmd == "protect":
        for f in protected_files():
            print(f)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
