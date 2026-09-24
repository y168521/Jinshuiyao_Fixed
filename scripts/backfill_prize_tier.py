# -*- coding: utf-8 -*-
"""历史预测「官方奖级回填」一次性脚本（JS-20260924-34）

## 为什么要做
`utils/lottery_prize.py` 上线前的复盘记录只有 `hits`（号码重合数），
**没有任何一条**记录「按官方规则到底中奖没有」。而这两套口径是双向错位的
（实测：双色球中 1 红没中蓝 → 系统算命中、官方无奖；只中蓝球 → 系统算未中、
官方六等奖 5 元）。所以历史复盘数据无法回答「真实中奖情况」这个问题。

本脚本做的事（只补事实，不改既有口径）：
  1. 对每条**已有 actual（开奖号）**的记录，按官方规则判定中奖；
  2. 写入 `prize_tier`（奖级名或 None）与 `prize_status`（win/lose/not_applicable/…）；
  3. **不动** `hits` / `hit_type` / `coverage` / `reviewed` 任何既有字段 ——
     用户已拍板走「并存」方案：hits 继续供学习与既有统计，prize_tier 另开一列。

## 安全设计
  - **默认只读演练（dry-run）**，不写任何文件；加 `--apply` 才写盘。
  - 写盘前**先备份**到 `predictions.json.bak_prizetier`。
  - 写盘走项目标准原子写 `utils.safe_json.safe_write_json`。
  - **幂等**：重复执行第二次为 0 变化（已在副本上验证）。
  - 没有 actual 的记录（未开奖）**跳过**并计数 —— 开奖号都拿不到就无从判定。

用法:
  python scripts/backfill_prize_tier.py             # 只读演练
  python scripts/backfill_prize_tier.py --apply     # 真正写盘
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.lottery_prize import judge_prize  # noqa: E402
from utils.safe_json import safe_write_json  # noqa: E402

PRED_FILE = os.path.join(BASE_DIR, "金水谣数据", "predictions.json")
BACKUP_FILE = PRED_FILE + ".bak_prizetier"


def main(apply: bool = False):
    with io.open(PRED_FILE, encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        print("[backfill-prize] 数据格式异常，终止")
        return 1

    filled = changed = skipped = 0
    tier_counter = Counter()
    status_counter = Counter()

    for r in rows:
        actual = r.get("actual")
        if not actual:
            skipped += 1
            continue
        res = judge_prize(r.get("lot", ""), r.get("nums", ""), actual)
        tier = res.get("tier")
        status = res.get("status")
        tier_counter[tier or "（未中奖）"] += 1
        status_counter[status] += 1
        if r.get("prize_status") != status or r.get("prize_tier") != tier:
            changed += 1
        if "prize_tier" not in r:
            filled += 1
        r["prize_tier"] = tier
        r["prize_status"] = status

    print("[backfill-prize] 总条数=%d 将写prize_tier=%d 变化=%d 跳过(无开奖号)=%d"
          % (len(rows), len(rows) - skipped, changed, skipped))
    print("[backfill-prize] status分布: %s" % dict(status_counter))
    print("[backfill-prize] 中奖奖级分布: %s"
          % dict(sorted(tier_counter.items(), key=lambda kv: -kv[1])))

    if not apply:
        print("[backfill-prize] 模式: 只读演练(未改任何文件)")
        return 0

    try:
        import shutil
        shutil.copy2(PRED_FILE, BACKUP_FILE)
        print("[backfill-prize] 已备份 -> %s" % BACKUP_FILE)
    except Exception as e:
        print("[backfill-prize] 备份失败，终止: %s" % e)
        return 1
    safe_write_json(PRED_FILE, rows)
    print("[backfill-prize] 写盘完成: {'filled': %d, 'changed': %d, 'skipped': %d}"
          % (filled, changed, skipped))
    print("[backfill-prize] 模式: 写盘(--apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
