# -*- coding: utf-8 -*-
"""JS-20261020 · 排列三/福彩3D 组选六复式5码 质量退化复现脚本（只读诊断）

用法：python tools/repro_3d_group6.py
输出：每个彩种跑 N 次生成，统计复式码数分布、重复码、组六展开注数是否等于 C(n,3)。
"""
import os
import random
import sys
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engines.format_gen import FormatGen  # noqa: E402

LOTS = ["福彩3D", "排列三"]


def make_history(n=40, seed=7):
    """合成历史开奖（nums 形如 "1,2,3" + period），用于驱动选号引擎。"""
    rng = random.Random(seed)
    return [{"nums": ",".join(str(rng.randint(0, 9)) for _ in range(3)),
             "period": 2026000 + i}
            for i in range(n)]


def parse_fushi(s):
    """复式字符串 → 数字列表（兼容 "01,02,03" 与 "[1,2,3]" 两种写法）。"""
    body = s.strip()
    if body.startswith("[") and body.endswith("]"):
        body = body[1:-1]
    return [int(x) for x in body.replace("，", ",").split(",") if x.strip() != ""]


def run_one(lot, history, seed):
    rng = random.Random(seed)
    hot = {d: rng.uniform(0.1, 1.0) for d in range(10)}
    kill = {rng.randint(0, 9) for _ in range(2)}
    play_plan = [{"type": "复式", "config": {"digit_count": 5}, "count": 1}]
    fg = FormatGen(lot=lot, kill=kill, hot=hot, history=history,
                   play_plan=play_plan, hot_window=10)
    res = fg.gen()
    fushi_list = res.get("复式") or []
    return fushi_list, res


def main():
    print("=" * 72)
    print("排列三 / 福彩3D 组选六复式5码 质量诊断")
    print("=" * 72)
    for lot in LOTS:
        history = make_history()
        sizes = {}
        bad = []
        for seed in range(30):
            fushi_list, _ = run_one(lot, history, seed)
            if not fushi_list:
                sizes["<空>"] = sizes.get("<空>", 0) + 1
                bad.append((seed, None, "未产出复式"))
                continue
            s = fushi_list[0]
            nums = parse_fushi(s)
            sizes[len(nums)] = sizes.get(len(nums), 0) + 1
            # 组六展开
            distinct = sorted(set(nums))
            if len(distinct) != len(nums):
                bad.append((seed, s, "码池内有重复数字: %s" % nums))
            combo_count = len(list(combinations(distinct, 3)))
            expected = len(list(combinations(range(len(distinct)), 3)))
            if combo_count != expected:
                bad.append((seed, s, "展开注数异常"))
            if len(nums) != 5:
                bad.append((seed, s, "码数不是5（实际%d）" % len(nums)))
        print("\n[%s] 复式码数分布：%s" % (lot, sizes))
        if bad:
            print("  异常样本（前5条）：")
            for seed, s, why in bad[:5]:
                print("    seed=%s 复式=%s → %s" % (seed, s, why))
        else:
            print("  30 次生成全部为 5 码、无重复、展开 C(5,3)=10 注")
    print("\n" + "=" * 72)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
