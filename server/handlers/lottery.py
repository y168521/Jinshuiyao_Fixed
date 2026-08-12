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

from ..config import HTML_DIR
from ..utils import log


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


def _load_lottery_body(handler, required=()):
    """POST body 解析 + 彩种校验（统一入口，W63补71 新增）。

    读取方式与 server/handlers/backtest.py 一致（headers + rfile.read），
    便于 FakeHandler 契约测试 mock。
    """
    import json
    from config import LOT_ALL

    cl = int(handler.headers.get('Content-Length', 0) or 0)
    raw = handler.rfile.read(cl).decode('utf-8', errors='replace') if cl else ''
    data = json.loads(raw) if raw else {}
    lot = str(data.get("lottery", "")).strip()
    if not lot:
        handler._send_json({"ok": False, "error": "缺少 lottery 参数"}, 400)
        return None
    if lot not in LOT_ALL:
        handler._send_json({"ok": False, "error": f"暂不支持彩种: {lot}", "supported": LOT_ALL}, 400)
        return None
    return data


def handle_omission_table(handler):
    """POST /api/lottery/omission-table — 交互式遗漏表格（真实数据，W63补71 接通）

    请求: {"lottery": "双色球"}（可选 count 限定分析期数）
    响应: {"ok": true, "data": [{number, current, max, avg, frequency, lastAppear, hotLevel}]}
    """
    try:
        from models.lottery_data import Data
        from engines.lottery_stats import omission_table

        data = _load_lottery_body(handler)
        if data is None:
            return
        history = Data.load(data["lottery"])
        handler._send_json({"ok": True, "lottery": data["lottery"], "data": omission_table(history, data["lottery"])})
    except Exception as e:
        log(f'[lottery-omission-table] 计算失败: {e}')
        handler._send_json({"ok": False, "error": f"遗漏表格计算失败: {e}"}, 500)


def handle_historical_same_period(handler):
    """POST /api/lottery/historical-same-period — 历史同期查询（真实数据，W63补71 接通）

    请求: {"lottery": "双色球", "date": "2026-08-11", "mode": "date"|"month"}
    响应: {"ok": true, "data": [{date, drawNum, reds, blues}]}
    """
    try:
        from models.lottery_data import Data
        from engines.lottery_stats import historical_same_period

        data = _load_lottery_body(handler)
        if data is None:
            return
        date_str = str(data.get("date", "")).strip()
        mode = str(data.get("mode", "date")).strip() or "date"
        if not date_str:
            handler._send_json({"ok": False, "error": "缺少 date 参数（格式 YYYY-MM-DD）"}, 400)
            return
        history = Data.load(data["lottery"])
        rows = historical_same_period(history, date_str, mode)
        handler._send_json({"ok": True, "lottery": data["lottery"], "mode": mode, "data": rows})
    except Exception as e:
        log(f'[lottery-historical-same-period] 计算失败: {e}')
        handler._send_json({"ok": False, "error": f"历史同期查询失败: {e}"}, 500)


def handle_number_follow_up(handler):
    """POST /api/lottery/number-follow-up — 号码跟随分析（真实数据，W63补71 接通）

    请求: {"lottery": "双色球", "gap": 1}
    响应: {"ok": true, "data": {前号i: {后号j: 概率}}}
    诚实：仅历史转移统计，非中奖预测。
    """
    try:
        from models.lottery_data import Data
        from engines.lottery_stats import number_follow_up

        data = _load_lottery_body(handler)
        if data is None:
            return
        gap = data.get("gap", 1)
        try:
            gap = int(gap)
        except Exception:
            gap = 1
        history = Data.load(data["lottery"])
        handler._send_json({
            "ok": True, "lottery": data["lottery"], "gap": gap,
            "data": number_follow_up(history, gap, data["lottery"]),
            "honest_note": "仅历史号码转移统计，非中奖概率",
        })
    except Exception as e:
        log(f'[lottery-number-follow-up] 计算失败: {e}')
        handler._send_json({"ok": False, "error": f"号码跟随计算失败: {e}"}, 500)


def handle_trend_classification(handler):
    """POST /api/lottery/trend-classification — 近期开奖序列（012路/质合/五行在前端本地分类）

    请求: {"lottery": "福彩3D", "count": 30}
    响应: {"ok": true, "data": [{drawNum, numbers}]}
    """
    try:
        from models.lottery_data import Data
        from engines.lottery_stats import trend_classification

        data = _load_lottery_body(handler)
        if data is None:
            return
        count = data.get("count", 30)
        try:
            count = int(count)
        except Exception:
            count = 30
        history = Data.load(data["lottery"])
        handler._send_json({"ok": True, "lottery": data["lottery"], "data": trend_classification(history, count)})
    except Exception as e:
        log(f'[lottery-trend-classification] 计算失败: {e}')
        handler._send_json({"ok": False, "error": f"走势分类计算失败: {e}"}, 500)
