# -*- coding: utf-8 -*-
"""金水谣系统 - 彩票数据源健康可观测 API（S6）

路由：
  GET /api/lottery/sources-health  — 各数据源熔断状态 + 最后成功/失败时间 + 各彩种数据新鲜度

解决痛点（逆向推导必做项）：数据源「悄悄挂了无人知」——
此前源失败只在 fetcher 内部 last_error 短暂留存，Web UI/运维无任何可观测出口，
导致用户截图所见的 500/404 长期无人定位。本端点把熔断器状态、成功/失败时间戳、
各彩种本地数据陈旧度一次性暴露，供面板/告警消费。
"""
import os
import time

from ..config import BASE_DIR, HTML_DIR
from ..utils import log


def handle_sources_health_page(handler):
    """GET /lottery-sources-health — 返回数据源健康仪表盘 HTML 页面。"""
    page = os.path.join(HTML_DIR, 'lottery-sources-health.html')
    if os.path.isfile(page):
        try:
            with open(page, 'r', encoding='utf-8') as f:
                content = f.read()
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/html; charset=utf-8')
            handler.end_headers()
            handler.wfile.write(content.encode('utf-8'))
            return
        except Exception as e:
            log(f'[lottery-sources-health-page] 读取页面失败: {e}')
    handler._send_json({"ok": False, "error": "仪表盘页面不存在"}, 404)


def handle_sources_health(handler):
    """GET /api/lottery/sources-health — 数据源健康 + 数据新鲜度快照

    返回格式:
    {
        "ok": true,
        "generated_at": 1750000000.0,
        "sources": [
            {
                "source": "CWL", "state": "closed",
                "failure_count": 0, "total_success": 12, "total_failure": 0,
                "last_failure": null, "last_ok_ts": 1750000000.0, "last_fail_ts": null
            }, ...
        ],
        "lotteries": [
            {"name": "双色球", "data_age_min": 35, "stale": false}, ...
        ]
    }
    """
    try:
        from fetchers.fetcher import get_fetcher
        from config import DATA_SAVE, LOT_ALL

        fetcher = get_fetcher()
        sources = fetcher.get_sources_health()

        # 各彩种本地数据新鲜度（按数据文件 mtime 计算）
        lotteries = []
        now = time.time()
        for name in LOT_ALL:
            path = os.path.join(DATA_SAVE, f"{name}.json")
            if os.path.exists(path):
                age_min = int((now - os.path.getmtime(path)) / 60)
                # 超过 24h 视为陈旧（每日开奖彩种应 <24h 更新）
                lotteries.append({"name": name, "data_age_min": age_min, "stale": age_min > 1440})
            else:
                lotteries.append({"name": name, "data_age_min": None, "stale": True})

        handler._send_json({
            "ok": True,
            "generated_at": now,
            "sources": sources,
            "lotteries": lotteries,
        })
    except Exception as e:
        log(f'[lottery-sources-health] 获取数据源健康失败: {e}')
        handler._send_json({"ok": False, "error": f"获取数据源健康失败: {e}", "sources": [], "lotteries": []}, 500)


def handle_reference(handler):
    """GET /api/lottery/reference?lot=福彩3D — 多维参考特征 + SQI（不生成号码）

    返回 福彩3D/排列三 的描述性统计（遗漏/冷热/振幅/奇偶/大小/区间/和值/跨度）
    与重算后的 SQI。诚实：这些仅反映分布与信号清晰度，非中奖概率。
    """
    try:
        from urllib.parse import parse_qs
        from models.lottery_data import Data
        from engines.feature_engine import analyze as feat
        from engines.prediction_service import PredictionService

        qs = parse_qs(handler.path.split('?', 1)[-1])
        lot = qs.get('lot', ['福彩3D'])[0]
        if lot not in ('福彩3D', '排列三'):
            handler._send_json({"ok": False, "error": "暂仅支持福彩3D/排列三"}, 400)
            return

        arr = Data.load(lot)
        rf = feat(lot, arr)
        svc = PredictionService(on_log=None)
        states = {"hurst": True, "morph": True, "antikill": True,
                  "correlation": True, "cold_tunnel": True, "killcheck": True}
        sqi = svc._compute_signal_quality(lot, arr, 0.5, {}, set(), None, None,
                                          {"cards_used": 0}, False, states, rf)
        handler._send_json({"ok": True, "lot": lot, "ref_features": rf, "confidence": sqi}, 200)
    except Exception as e:
        handler._send_json({"ok": False, "error": str(e)}, 500)


def handle_math_model(handler):
    """GET /api/lottery/math-model?lot=大乐透[&methods=combinatorics,stats][&budget=149]

    数学模型候选集生成：组合数学缩水 + 统计推断 + 蒙特卡洛证伪 + 时间序列 + 误差校准。
    诚实：仅用于历史筛选、纪律化缩水、策略证伪，不预测中奖；输出为候选集·非购买建议。
    """
    try:
        from urllib.parse import parse_qs
        from engines.math_selector import run_math_model

        qs = parse_qs(handler.path.split('?', 1)[-1])
        lot = qs.get('lot', ['大乐透'])[0]
        methods = qs.get('methods', [None])[0]
        methods = [m.strip() for m in methods.split(',')] if methods else None
        budget_s = qs.get('budget', ['149'])[0]
        try:
            budget = int(budget_s)
        except Exception:
            budget = 149
        if lot not in ('双色球', '大乐透', '福彩3D', '排列三', '七乐彩', '七星彩', '快乐8'):
            handler._send_json({"ok": False, "error": "暂不支持该彩种"}, 400)
            return
        data = run_math_model(lot, methods=methods, budget=budget)
        # 大盘彩诚实降级警示透出（config.DEGRADED_LOTS，JS-20260727 缺口#3）
        try:
            from config import DEGRADED_LOTS
            if lot in DEGRADED_LOTS:
                data["honest_warning"] = DEGRADED_LOTS[lot]
        except Exception:
            pass
        handler._send_json(data, 200 if data.get("ok") else 500)
    except Exception as e:
        handler._send_json({"ok": False, "error": str(e)}, 500)
