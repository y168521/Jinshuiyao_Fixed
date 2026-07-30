#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb_append.py — 共享知识文件「占锁 + 仅追加」守护写入器。

道衍推导:
  阳 = 写(建知识) / 阴 = 占锁 + 禁覆盖(守)
  天 = 共识协议(改前占锁) / 地 = 文件隔离(受保护集) / 人 = append 自检(事后可追)
  知止 = 受保护文件禁无锁裸写 + 禁整文件覆盖(只许追加)

用法:
  # 1) 先占锁(同频共识)
  py session_coordinator.py acquire --intent "补决策卡" --holder MY_SESSION
  # 2) 再追加(本器)
  py kb_append.py --file <知识文件> --holder MY_SESSION --content "..." [--nl]
  py kb_append.py --file <知识文件> --holder MY_SESSION --from-stdin

退出码: 0=成功 2=未占锁/过期 3=目标不存在(禁止凭空造命门)
依赖: 必须先由 session_coordinator 占锁，且 holder 一致。
"""
import argparse
import json
import os
import sys
import time

# Jinshuiyao_Fixed/scripts → 模型/.workbuddy/session_claim.json
_CLAIM_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".workbuddy", "session_claim.json")
)
STALE_SECS = 120


def _read_claim():
    if not os.path.exists(_CLAIM_PATH):
        return None
    try:
        with open(_CLAIM_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="共享知识文件 占锁+仅追加 守护写入器")
    ap.add_argument("--file", required=True, help="目标知识文件(须已存在)")
    ap.add_argument("--holder", required=True, help="与 session_coordinator 占锁一致的会话名")
    ap.add_argument("--content", default=None, help="要追加的文本")
    ap.add_argument("--from-stdin", action="store_true", help="从 stdin 读内容")
    ap.add_argument("--nl", action="store_true", help="追加前加一空行分隔")
    args = ap.parse_args()

    # [阴门1] 占锁校验——无锁或持有者不符一律拒绝
    claim = _read_claim()
    if not claim or claim.get("holder") != args.holder:
        sys.stderr.write(
            f"❌ 未占锁或持有者不符: 需先 `session_coordinator acquire --holder {args.holder}`\n"
        )
        return 2
    if (time.time() - claim.get("heartbeat", 0)) > STALE_SECS:
        sys.stderr.write("❌ 锁已过期，请重新 acquire 再写\n")
        return 2

    # [阴门2] 文件必须已存在——禁止凭空创建命门文件(防覆盖式新建)
    target = os.path.abspath(args.file)
    if not os.path.exists(target):
        sys.stderr.write(f"❌ 目标不存在(禁止创建命门文件): {target}\n")
        return 3

    # [阳] 仅追加——绝不整文件覆盖
    text = args.content
    if args.from_stdin:
        text = sys.stdin.read()
    if text is None:
        text = ""
    block = ("\n" + text) if args.nl else text
    with open(target, "a", encoding="utf-8") as f:
        f.write(block)
    sys.stderr.write(f"✅ 已追加 {len(block)} 字符到 {os.path.relpath(target)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
