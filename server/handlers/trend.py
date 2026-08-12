# -*- coding: utf-8 -*-
"""金水谣系统 - 走势图数据 API

提供按彩种分片的走势图数据，支持懒加载和新鲜度标注。

路由：
  GET /api/trend/data?lot=福彩3D  — 指定彩种的走势数据（含新鲜度元数据）
  GET /api/trend/freshness        — 所有彩种数据新鲜度概览
"""
import os
import time
import urllib.parse

from ..config import BASE_DIR
from ..utils import log


def _get_generator():
    """惰性初始化 TrendGenerator 实例（避免模块加载时依赖数据目录）。"""
    from engines.trend_generator import TrendGenerator

    data_dir = os.path.join(BASE_DIR, '金水谣数据')
    return TrendGenerator(data_dir)


def handle_trend_data(handler, parsed):
    """GET /api/trend/data?lot=福彩3D — 单个彩种的走势数据。

    Query params:
        lot: 彩种名称（URL 编码），必填
    """
    params = urllib.parse.parse_qs(parsed.query)
    lot_list = params.get('lot', [])
    if not lot_list:
        handler._send_json({"error": "缺少参数 lot"}, 400)
        return

    lot_name = lot_list[0]
    try:
        gen = _get_generator()
        result = gen.generate_lot(lot_name)
        if result is None:
            handler._send_json({"error": f"彩种 '{lot_name}' 数据不存在或读取失败"}, 404)
            return
        handler._send_json(result, 200)
    except Exception as e:
        log(f"[trend] 走势数据生成异常 [lot={lot_name}]: {e}")
        handler._send_json({"error": f"走势数据生成失败: {str(e)}"}, 500)


def handle_trend_freshness(handler):
    """GET /api/trend/freshness — 所有彩种数据新鲜度概览。

    Returns:
        dict: {
            "lots": {
                "福彩3D": {
                    "generated_at": 1750000000.0,
                    "generated_at_str": "2026-07-23 21:00:00",
                    "period_count": 856,
                    "stale": false
                },
                ...
            },
            "server_time": 1750000000.0
        }
    """
    try:
        gen = _get_generator()
        lot_names = gen.get_all_lot_names()
        lots = {}
        for name in lot_names:
            try:
                result = gen.generate_lot(name)
                if result:
                    lots[name] = {
                        "generated_at": result["generated_at"],
                        "generated_at_str": result["generated_at_str"],
                        "period_count": result["period_count"],
                        "period_range": result["period_range"],
                        "stale": result.get("stale", False),
                    }
                else:
                    lots[name] = {"error": "数据加载失败"}
            except Exception as e:
                log(f"[trend] 新鲜度检查异常 [{name}]: {e}")
                lots[name] = {"error": str(e)}

        handler._send_json({
            "lots": lots,
            "server_time": time.time(),
        }, 200)
    except Exception as e:
        log(f"[trend] 新鲜度概览异常: {e}")
        handler._send_json({"error": f"新鲜度查询失败: {str(e)}"}, 500)
