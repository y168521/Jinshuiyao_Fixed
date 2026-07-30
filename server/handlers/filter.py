# -*- coding: utf-8 -*-
"""金水谣系统 - 缩水过滤 API

路由：
  POST /api/filter/smart — 应用 SmartFilter 进行智能缩水过滤
"""
import json
import os
import itertools
import urllib.parse
from ..config import BASE_DIR
from ..utils import log


def handle_smart_filter(handler):
    """POST /api/filter/smart — 智能缩水过滤

    Request body (JSON):
        lot_type: str          彩种名称
        red_nums: list[int]    待选红球号码
        blue_nums: list[int]   待选蓝球号码 (可选)
        rules: dict            规则开关及参数 (可选)
            odd_even: {enabled, extreme_only}
            big_small: {enabled, extreme_only}
            sum: {enabled, min, max}
            span: {enabled, min, max}
            consecutive: {enabled, max_consec}
            tail: {enabled, max_same_tail}
            zone: {enabled}
            cold_hot: {enabled, max_cold, min_hot}
        tolerance: int         可容忍的违规规则数 (默认 0)
        max_combos: int        最多生成组合数 (默认 5000)

    Returns:
        before: int             过滤前注数
        after: int              过滤后注数
        combos: list[list]      过滤后的组合
        details: dict           各规则扣分明细
    """
    body = handler._read_body()
    if not body:
        handler._send_json({"error": "请求体为空"}, 400)
        return

    try:
        params = json.loads(body)
    except json.JSONDecodeError:
        handler._send_json({"error": "JSON 格式错误"}, 400)
        return

    lot_type = params.get("lot_type", "")
    red_nums = params.get("red_nums", [])
    blue_nums = params.get("blue_nums", [])
    rules_config = params.get("rules", {})
    tolerance = params.get("tolerance", 0)
    max_combos = min(params.get("max_combos", 5000), 50000)

    if not lot_type or not red_nums:
        handler._send_json({"error": "缺少必要参数: lot_type, red_nums"}, 400)
        return

    # 确定 k 值
    from config import LOTTERY_RULES
    lot_cfg = LOTTERY_RULES.get(lot_type, {})
    red_count = lot_cfg.get("red", 6)

    if len(red_nums) < red_count:
        handler._send_json({"error": f"红球至少需要 {red_count} 个号码"}, 400)
        return

    # 加载历史数据
    history = []
    data_path = os.path.join(BASE_DIR, '金水谣数据', 'lot_data', f'{lot_type}.json')
    if os.path.isfile(data_path):
        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log(f"[filter] 加载历史数据失败: {e}")

    # 生成所有组合
    all_combos = list(itertools.combinations(red_nums, red_count))
    if len(all_combos) > max_combos:
        log(f"[filter] 组合数 {len(all_combos)} 超过上限 {max_combos}，截断")
        all_combos = all_combos[:max_combos]

    before = len(all_combos)

    # 应用 SmartFilter
    try:
        from filters.smart_filter import SmartFilter
        sf = SmartFilter(history, lot_type)
    except Exception as e:
        log(f"[filter] SmartFilter 初始化失败: {e}")
        handler._send_json({"error": f"过滤器初始化失败: {str(e)}"}, 500)
        return

    passed_combos = []
    all_details = []

    for combo in all_combos:
        score_detail = sf.get_score(combo)
        total_score = score_detail.get("total", 0)
        # 检查是否在容错范围内
        rule_violations = sum(1 for k, v in score_detail.items()
                              if k != "total" and isinstance(v, (int, float)) and v > 0)
        if total_score <= sf.SCORE_THRESHOLD or rule_violations <= tolerance:
            passed_combos.append(list(combo))
            all_details.append(score_detail)

    after = len(passed_combos)

    # 构建汇总
    detail_summary = {}
    for sd in all_details[:100]:
        for k, v in sd.items():
            if k not in detail_summary:
                detail_summary[k] = {"min": v, "max": v, "avg": v, "count": 1}
            else:
                ds = detail_summary[k]
                ds["min"] = min(ds["min"], v)
                ds["max"] = max(ds["max"], v)
                ds["avg"] = (ds["avg"] * ds["count"] + v) / (ds["count"] + 1)
                ds["count"] += 1

    result = {
        "before": before,
        "after": after,
        "passed": passed_combos[:200],  # 只返回前200个
        "total_passed": after,
        "filter_rate": round((before - after) / before * 100, 1) if before > 0 else 0,
        "detail_summary": detail_summary,
    }

    # 蓝球
    if blue_nums:
        result["blue_nums"] = blue_nums

    handler._send_json(result, 200)
