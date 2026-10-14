# -*- coding: utf-8 -*-
"""当日购票记账 CLI —— 薄封装，只调 `utils/purchase_log.py`（唯一写入端点）。

背景：JS-20261012-13 决策「条件加」+ JS-20261015-01 落地。
定位：**只记账，不预测**。本工具的数据禁止用于选号/权重/杀号。

用法
----
    # 记录一笔购票（未中奖）
    py -3.14 tools/purchase_log.py --record --lot 双色球 --period 2026116 --amount 4 --count 2

    # 明确记录「今天没买」
    py -3.14 tools/purchase_log.py --record --lot 双色球 --period 2026116 --no-buy

    # 补记兑奖所得
    py -3.14 tools/purchase_log.py --set-payout --lot 双色球 --period 2026116 --payout 10

    # 查看汇总（含与官方返奖率对照）
    py -3.14 tools/purchase_log.py --summary
    py -3.14 tools/purchase_log.py --summary --lot 双色球

    # 删除行使（PIPL 第 47 条）：清空全部，或仅清 N 天前
    py -3.14 tools/purchase_log.py --clear
    py -3.14 tools/purchase_log.py --clear --older-than-days 90

退出码：0 成功 / 2 参数错误。

扩展点：新增子命令 = 新增一个 `_cmd_xxx(ap, args)` + 在 `main()` 加一行分派。
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.purchase_log import record, summary, clear, get  # noqa: E402


def build_parser():
    """构造参数解析器（与执行逻辑解耦，便于单测复用）。"""
    ap = argparse.ArgumentParser(description="当日购票记账（诚实记账层，绝不参与选号）")
    ap.add_argument("--record", action="store_true", help="记录一条购票流水")
    ap.add_argument("--set-payout", action="store_true", help="补记某期的兑奖所得")
    ap.add_argument("--summary", action="store_true", help="查看汇总统计")
    ap.add_argument("--clear", action="store_true", help="清空流水（行使删除权）")
    ap.add_argument("--lot", help="彩种名，如 双色球 / 大乐透")
    ap.add_argument("--period", help="期号，如 2026116")
    ap.add_argument("--amount", type=float, help="实际投入金额（元）")
    ap.add_argument("--count", type=int, help="购买注数")
    ap.add_argument("--payout", type=float, help="实际兑奖所得（元）；未中奖填 0")
    ap.add_argument("--note", help="备注")
    ap.add_argument("--no-buy", action="store_true",
                    help="明确记录「当日未购票」（缺省语义需要，禁止省略）")
    ap.add_argument("--older-than-days", type=int, help="配合 --clear：仅删除超过 N 天的条目")
    ap.add_argument("--file", help="覆盖记账文件路径（测试/隔离用扩展点）")
    return ap


def _entry_from_args(args):
    """把 CLI 参数组装成记账条目。缺省语义集中在一处，改口径只动这个函数。"""
    entry = {"lot": args.lot, "period": args.period, "purchased": not args.no_buy}
    if args.amount is not None:
        entry["purchase_amount"] = args.amount
    if args.count is not None:
        entry["purchase_count"] = args.count
    entry["payout"] = args.payout if args.payout is not None else 0.0
    if args.note:
        entry["purchase_note"] = args.note
    return entry


def _report_dropped(dropped):
    if dropped:
        print("  已剔除字段: %s（红线/派生，未落库）" % ", ".join(dropped))


def _print_summary(s):
    print("── 购票记账汇总 ──")
    print("范围      : %s" % s["lot"])
    print("记录条数  : %d（其中已购票 %d）" % (s["records"], s["bought"]))
    print("实际投入  : %.2f 元" % s["spend"])
    print("实际返还  : %.2f 元" % s["payout"])
    print("净盈亏    : %.2f 元" % s["net"])
    if s["ratio"] is None:
        print("实际返还率: 暂无样本（投入为 0 或无记录）")
    else:
        print("实际返还率: %.2f%%" % (s["ratio"] * 100))
        if s["official_ratio"]:
            off = s["official_ratio"]
            print("官方奖金池: %.2f%%" % (off * 100))
            if s["ratio"] > off * 1.15:
                print("⚠️ 实际返还率显著高于官方奖金池比例，多半是投入漏记或弃奖未记，请核对录入")


def _cmd_record(ap, args):
    """--record：记一条购票流水（未给兑奖额 ⇒ payout=0，未中奖记 0 不得留空）。"""
    if not args.lot or not args.period:
        ap.error("--record 需要 --lot 与 --period")
    try:
        clean, dropped = record(_entry_from_args(args))
    except ValueError as e:
        print("✗ 拒绝录入: %s" % e)
        return 2
    net = (clean.get("payout") or 0.0) - (clean.get("purchase_amount") or 0.0)
    print("✓ 已记录 %s %s（投入 %s 元 / 返还 %s 元 / 净 %+.2f 元）" % (
        clean["lot"], clean["period"],
        clean.get("purchase_amount", "未填"),
        clean.get("payout", 0.0), net,
    ))
    _report_dropped(dropped)
    return 0


def _cmd_set_payout(ap, args):
    """--set-payout：补记某期兑奖所得（无旧记录时自动补 purchased=True）。"""
    if not args.lot or not args.period or args.payout is None:
        ap.error("--set-payout 需要 --lot、--period、--payout")
    old = get(args.lot, args.period)
    merged = dict(old or {"lot": args.lot, "period": args.period})
    merged["payout"] = args.payout
    if old is None:
        merged["purchased"] = True
    clean, dropped = record(merged)
    print("✓ 已补记兑奖 %s %s = %.2f 元" % (clean["lot"], clean["period"], clean["payout"]))
    _report_dropped(dropped)
    return 0


def main(argv=None):
    """薄调度：解析参数 → 分派到 `_cmd_*` → 返回退出码。"""
    ap = build_parser()
    args = ap.parse_args(argv)

    if args.file:
        import utils.purchase_log as _mpl
        _mpl.PURCHASE_LOG_PATH = args.file

    if args.record:
        return _cmd_record(ap, args)
    if args.set_payout:
        return _cmd_set_payout(ap, args)
    if args.summary:
        _print_summary(summary(args.lot))
        return 0
    if args.clear:
        print("✓ 已删除 %d 条" % clear(args.older_than_days))
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
