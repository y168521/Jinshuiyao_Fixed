# -*- coding: utf-8 -*-
"""复盘结果回写单一真源（JS-20260924-32）

背景（真实缺陷，实测取证 2026-09-24）：predictions.json 3228 条里有 **30 条
reviewed=True 却没有 actual（开奖号）**，且全部生成于 2026-09-23 —— 每天新增一批。

根因：彩票复盘有三条代码路径各自手写回写字段，
  1. domains/lottery/domain.py  LotteryDomain.review()
  2. core/infra/scheduler.py    TaskScheduler._task_auto_review()   ← 自动复盘，每天跑
  3. gui/main_window.py         _review_job()
JS-20260921-03 只修了第 1 条（补回 actual），第 2、3 条是同类项被漏掉 →
自动复盘每天跑一次，就每天新增约 30 条「已复盘、有命中数、但查不到开奖号」的记录，
历史命中事后无法重算核对。

修复：所有路径统一调用 stamp_review()，字段集合在一处定义；并由
tests/unit/test_review_writeback_single_source.py 的 AST 闸禁止再直接写
pred["reviewed"]（同类项全量为零）。

用法：
    stamp_review(pred, actual="01,02,03,04,05,06+07", draw_date="2026-09-23",
                 hits=3, hit_type="组选", coverage=0.5)

约定：参数默认 None 表示「调用方未提供该字段」→ **跳过不写**，绝不用 None
覆盖已有值（历史修补脚本补过的 actual 不能被后来的复盘抹掉）。
"""

# 复盘回写的完整字段集合（新增字段必须在此登记，否则各路径会再次出现漏项）
# prize_tier / prize_status：官方奖级判定结果（JS-20260924-34），与 hits（号码重合数）
# 是两套并存口径 —— hits 供学习与既有统计，prize_tier 才是「官方到底中奖没有」。
REVIEW_FIELDS = ("actual", "draw_date", "reviewed", "hits", "hit_type", "coverage",
                 "prize_tier", "prize_status")

# 官方奖级判定失败时的兜底状态（区别于「未中奖」——规则读不到 ≠ 没中奖）
PRIZE_STATUS_ERROR = "error"


def stamp_review(pred, actual=None, draw_date=None, hits=None,
                 hit_type=None, coverage=None):
    """把一次复盘的结果写回预测记录 —— 复盘字段回写的唯一落点

    Args:
        pred: 预测记录 dict（原地修改）
        actual: 开奖号码字符串；必须回存，否则历史命中事后无法重算
        draw_date: 开奖日期字符串
        hits: 命中号码数（口径由调用方决定，本函数不做计算）
        hit_type: 命中类型（未中/组选/直选）
        coverage: 复式覆盖度 = 命中号码数 / 开奖号码总数

    Returns:
        dict: 传入的 pred（便于链式使用）

    Note:
        传 None 的字段跳过不写。命中数的计算口径不在本函数内统一 ——
        domains 走 utils.number_utils.count_match，scheduler / GUI 另有既存口径，
        统一口径属独立议题，未在这里顺手改动（避免历史统计口径突变）。
    """
    if not isinstance(pred, dict):
        raise TypeError("stamp_review 需要 dict，收到 %r" % type(pred).__name__)

    # reviewed / hits 是复盘的必要结果：未提供时兜底为 True / 0，
    # 避免调用方漏传导致「命中数缺失但标记为已复盘」的静默错误
    pred["reviewed"] = True
    pred["hits"] = 0 if hits is None else hits

    if actual is not None:
        pred["actual"] = actual
        _stamp_official_prize(pred, actual)
    if draw_date is not None:
        pred["draw_date"] = draw_date
    if hit_type is not None:
        pred["hit_type"] = hit_type
    if coverage is not None:
        pred["coverage"] = coverage
    return pred


def _stamp_official_prize(pred, actual):
    """回填官方奖级判定结果（JS-20260924-34）

    放在这里是刻意的：三条复盘路径（domains / scheduler 自动 / GUI 手动）**都已经**
    调用 stamp_review，在此补算即可全覆盖，不必改三处。

    判定失败（规则缺失/玩法不适用/异常）一律写 status 而不猜奖级——
    「规则读不到」绝不等于「没中奖」，两者必须可区分。
    """
    try:
        from utils.lottery_prize import judge_prize
        res = judge_prize(pred.get("lot", ""), pred.get("nums", ""), actual)
    except Exception:
        res = None
    if not isinstance(res, dict):
        pred["prize_tier"] = None
        pred["prize_status"] = PRIZE_STATUS_ERROR
        return pred
    pred["prize_tier"] = res.get("tier")
    pred["prize_status"] = res.get("status") or PRIZE_STATUS_ERROR
    return pred
