# -*- coding: utf-8 -*-
"""彩票回测逻辑 —— 从 BacktestEngine 抽出的彩票相关方法"""
import re
import logging

logger = logging.getLogger(__name__)


def parse_numbers(nums_str):
    """解析号码字符串为数字列表"""
    if not nums_str:
        return []
    return [int(x) for x in re.findall(r'\d+', str(nums_str))]


def split_balls(nums_str):
    """将 '1,2,3+4' 拆成 (红球列表, 蓝球列表)；无'+'时蓝球为空。"""
    s = str(nums_str or "").strip()
    if "+" in s:
        parts = s.split("+")
        reds = [int(x) for x in re.findall(r"\d+", parts[0])]
        blues = [int(x) for x in re.findall(r"\d+", parts[1])] if len(parts) > 1 else []
        return reds, blues
    return [int(x) for x in re.findall(r"\d+", s)], []


def evaluate_hit(lot, pred_str, actual_str, min_hit):
    """按彩种计算是否命中，返回 (is_hit, tier_label)。

    - 3D/七星彩：位置完全匹配=直选；顺序无关多重集匹配=组选。
    - 双色球/大乐透/七乐彩：按红球交集数判奖级，min_hit 为小奖红球阈值。
    - 快乐8：按选中号交集数判奖级。
    """
    if not pred_str or not actual_str:
        return False, ""
    lot = lot or ""
    if lot in ("福彩3D", "排列三", "七星彩"):
        pred_digits = parse_numbers(pred_str)
        act_digits = parse_numbers(actual_str)
        if not pred_digits or not act_digits:
            return False, ""
        if pred_digits == act_digits:
            return True, "直选"
        if sorted(pred_digits) == sorted(act_digits):
            return True, "组选"
        return False, ""

    pred_reds, pred_blues = split_balls(pred_str)
    act_reds, act_blues = split_balls(actual_str)
    red_common = len(set(pred_reds) & set(act_reds))
    blue_common = len(set(pred_blues) & set(act_blues))
    if red_common >= min_hit:
        tier = f"{red_common}红" + (f"+{blue_common}蓝" if blue_common else "")
        return True, tier
    return False, f"{red_common}红"


def run_lottery(engine, history_data, predictor_func, **kwargs):
    """执行彩票预测回测

    Args:
        engine: BacktestEngine 实例
        history_data: [{"period": int, "nums": str, "time": str}, ...]
        predictor_func: 预测函数 func(history_so_far, lot=...) -> predictions
        **kwargs: lot, top_n, window_size, min_periods, min_hit, odds

    Returns:
        dict: 回测结果报告
    """
    engine.reset()
    lot = kwargs.get("lot", "未知彩种")
    top_n = kwargs.get("top_n", 5)
    window_size = kwargs.get("window_size", 50)
    min_periods = kwargs.get("min_periods", 10)
    min_hit = kwargs.get("min_hit", 3)

    hits = 0
    total = 0
    hit_records = []

    for i in range(min_periods, len(history_data)):
        train_data = history_data[max(0, i - window_size):i]
        actual = history_data[i]

        try:
            predictions = predictor_func(train_data, lot=lot)
        except Exception as e:
            logger.error("预测失败 period=%s: %s", actual.get("period"), e)
            continue

        actual_str = actual.get("nums", "")
        for pred in predictions[:top_n]:
            pred_str = pred.get("nums", "") if isinstance(pred, dict) else str(pred)
            is_hit, tier = evaluate_hit(lot, pred_str, actual_str, min_hit)
            total += 1
            if is_hit:
                hits += 1
                hit_records.append({
                    "period": actual.get("period"),
                    "tier": tier,
                    "prediction": pred_str,
                    "actual": actual_str,
                })

    hit_rate = hits / total if total > 0 else 0
    return {
        "type": "lottery",
        "lot": lot,
        "total_tests": total,
        "hits": hits,
        "hit_rate": round(hit_rate, 4),
        "profit_ratio": round(hit_rate * kwargs.get("odds", 1) - 1, 4),
        "hit_records": hit_records[-20:],
        "summary": f"{lot} 回测 {total} 期，命中 {hits} 次，命中率 {hit_rate:.2%}",
    }
