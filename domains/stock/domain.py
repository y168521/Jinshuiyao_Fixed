# -*- coding: utf-8 -*-
"""股票子系统 - 金水谣内核适配层

A股预测与选股子系统：
  数据 → 技术指标引擎 → 趋势分析 → 选股过滤 → 信号生成

支持功能：
  - 多维度技术指标分析（MA/MACD/KDJ/RSI/布林带）
  - 趋势方向判断（短期/中期/长期）
  - 量价关系分析
  - 选股推荐与买卖信号
  - 组合风险监控

数据源：优先使用 akshare（免费A股数据），不可用时降级为模拟数据。
"""
import os
import json
import logging
from datetime import datetime, timedelta
from domains.base import DomainBase, project_data_dir
from core.context import run_in_subsystem

logger = logging.getLogger(__name__)


def _as_float(v, default=0.0):
    """统一把任意类型转 float，避免 .get() 结果为字符串/None 时 f-string 数值格式化报错。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class StockDomain(DomainBase):
    """A股预测子系统

    技术指标驱动的选股与趋势预测。
    """
    DOMAIN_ID = "stock"
    DESCRIPTION = "A股预测（技术指标 + 趋势分析 + 选股信号）"

    # 默认关注的A股指数和板块
    DEFAULT_INDEXES = ["sh000001", "sz399001", "sh000300"]  # 上证/深证/沪深300

    # 真实股票池（跨行业龙头，6位代码；fetcher._normalize_symbol 自动加 sh/sz 前缀）
    # 用于「股票筛选」功能，替换原先仅对 3 个指数排序的空壳逻辑
    DEFAULT_STOCK_POOL = [
        ("600519", "贵州茅台"), ("000858", "五粮液"), ("601318", "中国平安"),
        ("600036", "招商银行"), ("000333", "美的集团"), ("002594", "比亚迪"),
        ("300750", "宁德时代"), ("600276", "恒瑞医药"), ("601012", "隆基绿能"),
        ("000001", "平安银行"), ("600900", "长江电力"), ("601899", "紫金矿业"),
        ("002415", "海康威视"), ("600030", "中信证券"), ("601888", "中国中免"),
        ("603259", "药明康德"), ("688981", "中芯国际"), ("600887", "伊利股份"),
        ("601668", "中国建筑"), ("000651", "格力电器"), ("600009", "上海机场"),
        ("601398", "工商银行"), ("600585", "海螺水泥"), ("000725", "京东方A"),
    ]

    DEFAULT_PERIODS = {
        "short": 5,    # 短线：5日
        "medium": 20,  # 中线：20日
        "long": 60,    # 长线：60日
    }

    def __init__(self, config=None):
        super().__init__(config)
        self.data_dir = self.config.get("data_dir", project_data_dir("stock"))
        self._fetcher = None
        self._tech_engine = None
        self._trend_engine = None
        self._risk_monitor = None
        self._data_cache = {}  # {symbol: df}
        os.makedirs(self.data_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def setup(self):
        """加载股票引擎（优雅降级）"""
        try:
            # 尝试加载数据获取模块
            try:
                from domains.stock.fetcher import StockFetcher
                self._fetcher = StockFetcher()
                logger.info("股票数据获取模块已加载")
            except ImportError as e:
                logger.warning("股票数据获取模块未就绪（%s），以降级模式运行", e)
                self._fetcher = None

            # 尝试加载技术指标引擎
            try:
                from domains.stock.engines.tech_engine import TechnicalEngine
                self._tech_engine = TechnicalEngine()
                logger.info("技术指标引擎已加载")
            except ImportError as e:
                logger.warning("技术指标引擎未就绪（%s），以降级模式运行", e)
                self._tech_engine = None

            # 尝试加载趋势引擎
            try:
                from domains.stock.engines.trend_engine import TrendEngine
                self._trend_engine = TrendEngine()
                logger.info("趋势分析引擎已加载")
            except ImportError as e:
                logger.warning("趋势引擎未就绪（%s），以降级模式运行", e)
                self._trend_engine = None

            self._initialized = True
            logger.info("股票子系统初始化完成 (降级=%s)", self._fetcher is None)
            return True
        except Exception as e:
            logger.error("股票子系统初始化失败: %s", e)
            return False

    def teardown(self):
        """清理资源，保存缓存数据"""
        try:
            self._save_cache()
            self._initialized = False
            logger.info("股票子系统已关闭")
            return True
        except Exception as e:
            logger.error("股票子系统关闭失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # 核心流程
    # ------------------------------------------------------------------

    def fetch(self, symbols=None, period="daily", **kwargs):
        """抓取股票数据

        Args:
            symbols: 股票代码列表，None表示默认指数
            period: 周期 daily/weekly/monthly

        Returns:
            dict: {"success": bool, "data": {symbol: DataFrame}, "message": str}
        """
        target = symbols or self.DEFAULT_INDEXES
        results = {}
        mock_fallback = False

        try:
            if self._fetcher:
                for sym in target:
                    df = self._fetcher.get_history(sym, period=period)
                    if df is not None and not df.empty:
                        results[sym] = df
                        self._data_cache[sym] = df

            # 如果真实数据源未获取到任何数据，回退到模拟数据
            if not results:
                mock_fallback = True
                logger.info("真实数据源未返回数据，回退到模拟数据模式")
                for sym in target:
                    df = self._generate_mock_data(sym)
                    results[sym] = df
                    self._data_cache[sym] = df

            return {
                "success": True,
                "data": results,
                "message": f"获取 {len(results)}/{len(target)} 只股票数据",
                "mode": "mock" if mock_fallback else "real",
            }
        except Exception as e:
            logger.error("股票数据抓取失败: %s", e)
            return {"success": False, "data": {}, "message": str(e)}

    def analyze(self, data, symbols=None, **kwargs):
        """技术指标分析 + 趋势判断

        Args:
            data: fetch() 返回的数据字典 {symbol: DataFrame}
            symbols: 目标股票代码

        Returns:
            dict: 每只股票的指标分析结果
        """
        def _do_analyze():
            results = {}
            for sym, df in data.items():
                sym_result = {"symbol": sym, "indicators": {}, "trend": {}, "signals": []}

                # 技术指标计算
                if self._tech_engine:
                    sym_result["indicators"] = self._tech_engine.calculate(df)
                else:
                    sym_result["indicators"] = self._calc_basic_indicators(df)

                # 趋势判断
                if self._trend_engine:
                    sym_result["trend"] = self._trend_engine.judge(df, sym_result["indicators"])
                else:
                    sym_result["trend"] = self._judge_basic_trend(df, sym_result["indicators"])

                # 信号生成
                sym_result["signals"] = self._generate_signals(sym_result)
                results[sym] = sym_result

            return {
                "symbols": list(results.keys()),
                "results": results,
                "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "ok",
            }

        return run_in_subsystem("stock", _do_analyze)

    def generate(self, params=None, top_n=10, **kwargs):
        """生成选股推荐和买卖信号

        Args:
            params: analyze() 返回的分析结果
            top_n: 推荐数量

        Returns:
            dict: {"predictions": [...], "summary": str}
        """
        if not params or "results" not in params:
            return {
                "predictions": [],
                "summary": "无分析数据，无法生成推荐",
                "status": "no_data",
            }

        results = params["results"]
        scored = []

        for sym, r in results.items():
            score = self._score_stock(r)
            scored.append({
                "symbol": sym,
                "score": score,
                "trend": r.get("trend", {}),
                "signals": r.get("signals", []),
            })

        # 按评分排序
        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:top_n]

        predictions = []
        for item in top:
            trend = item["trend"]
            direction = trend.get("direction", "unknown")
            strength = trend.get("strength", 0)
            predictions.append({
                "symbol": item["symbol"],
                "action": "buy" if direction == "up" and strength > 60 else "hold" if direction == "up" else "watch",
                "confidence": min(100, max(0, item["score"])),
                "reason": f"趋势:{direction}, 强度:{strength:.1f}, 信号:{','.join(item['signals']) or '无'}",
            })

        summary = f"分析 {len(results)} 只股票，推荐 {len(predictions)} 只（前{top_n}）"
        return {
            "predictions": predictions,
            "summary": summary,
            "status": "ok",
            "domain_id": self.DOMAIN_ID,
        }

    def screen(self, pool=None, criteria=None, top_n=10, **kwargs):
        """股票筛选（多因子选股，集成 StockScreener）

        对股票池抓取真实数据（akshare 可用时）→ 技术指标分析 → 多因子评分
        → 评分排序返回。akshare 不可用时自动降级为模拟数据，筛选逻辑不变。

        Args:
            pool: [(code, name), ...] 或 [code, ...]；None 用 DEFAULT_STOCK_POOL
            criteria: 筛选条件 {"min_score": 50, "require_technical": True}
            top_n: 返回数量

        Returns:
            dict: {success, screened:[{symbol,name,total_score,factor_scores,...}],
                   total_pool, passed, factor_summary, mode, status}
        """
        try:
            if pool is None:
                pool = self.DEFAULT_STOCK_POOL

            norm_pool = []
            for item in pool:
                if isinstance(item, (list, tuple)):
                    norm_pool.append((str(item[0]), item[1] if len(item) > 1 else str(item[0])))
                else:
                    norm_pool.append((str(item), str(item)))
            codes = [c for c, _ in norm_pool]

            fetch_res = self.fetch(codes)
            if not fetch_res.get("success") or not fetch_res.get("data"):
                return {"success": False, "message": "无法获取股票池数据", "status": "no_data"}
            mode = fetch_res.get("mode", "mock")

            analysis = self.analyze(fetch_res["data"])
            results = analysis.get("results", {})
            if not results:
                return {"success": False, "message": "分析无结果", "status": "no_result"}

            criteria = criteria or {}
            min_score = criteria.get("min_score", 0)
            require_technical = criteria.get("require_technical", True)

            use_multi_factor = str(kwargs.get("multi_factor", "true")).lower() in ("1", "true", "yes")
            if use_multi_factor:
                from domains.stock.stock_screener import StockScreener
                screener = StockScreener()
                screen_res = screener.screen(
                    fetch_res["data"], results,
                    top_n=top_n, min_score=min_score,
                    require_technical=require_technical,
                )
                if not screen_res.get("success"):
                    return screen_res
                return {
                    "success": True,
                    "screened": screen_res["screened"],
                    "total_pool": screen_res["total_analyzed"],
                    "passed": screen_res["passed"],
                    "factor_summary": screen_res.get("factor_summary"),
                    "summary": f"多因子选股: 从 {screen_res['total_analyzed']} 只中筛选 {screen_res['returned']} 只",
                    "mode": mode,
                    "status": "ok",
                    "domain_id": self.DOMAIN_ID,
                }
            else:
                criteria = criteria or {}
                min_strength = criteria.get("min_strength", 60)
                require_signal = criteria.get("require_signal", True)
                direction = criteria.get("direction", "up")

                screened = []
                for sym, r in results.items():
                    trend = r.get("trend", {})
                    signals = r.get("signals", [])
                    score = self._score_stock(r)
                    if trend.get("direction") != direction:
                        continue
                    if trend.get("strength", 0) < min_strength:
                        continue
                    if require_signal and not signals:
                        continue
                    screened.append({
                        "symbol": sym,
                        "name": sym,
                        "score": round(score, 1),
                        "direction": trend.get("direction"),
                        "strength": trend.get("strength"),
                        "signals": signals,
                        "reason": f"趋势:{trend.get('direction')}, 强度:{trend.get('strength', 0):.1f}, 信号:{','.join(signals) or '无'}",
                    })

                screened.sort(key=lambda x: x["score"], reverse=True)
                top = screened[:top_n]
                summary = f"从 {len(results)} 只股票中筛选 {len(top)} 只（方向={direction}, 强度≥{min_strength}）"
                return {
                    "success": True,
                    "screened": top,
                    "total_pool": len(results),
                    "passed": len(screened),
                    "summary": summary,
                    "mode": mode,
                    "status": "ok",
                    "domain_id": self.DOMAIN_ID,
                }
        except Exception as e:
            logger.error("股票筛选失败: %s", e)
            return {"success": False, "message": str(e), "status": "error"}

    def review(self, predictions=None, actual=None, **kwargs):
        """复盘：收益率、胜率、回撤评估

        Args:
            predictions: 预测记录列表 [{symbol, action, confidence, timestamp}, ...]
            actual: 实际价格数据 {symbol: [{date, close}, ...]}

        Returns:
            dict: {"reviews": int, "hits": int, "updated": bool, "metrics": {...}}
        """
        try:
            if not predictions:
                return {"reviews": 0, "hits": 0, "updated": True, "metrics": {}, "status": "ok"}

            # 计算基础复盘指标
            metrics = self._calc_metrics(predictions, actual or {})
            return {
                "reviews": len(predictions),
                "hits": metrics.get("hit_count", 0),
                "updated": True,
                "metrics": metrics,
                "status": "ok",
            }
        except Exception as e:
            logger.error("股票复盘失败: %s", e)
            return {"reviews": 0, "hits": 0, "updated": False, "error": str(e)}

    # ------------------------------------------------------------------
    # 回测接口（股基 API 端点 /api/backtest?type=stock 落点）
    # ------------------------------------------------------------------

    def backtest(self, symbols=None, strategy="买入持有", **kwargs):
        """股票历史K线回测（接入 BacktestEngine.run_stock）

        默认使用 fetch() 已缓存的K线；也可先抓取。当前内置「买入持有」策略，
        由 backtesting.engine.stock_strategy_buy_hold 提供（首个交易日满仓买入、之后持有）。

        Args:
            symbols: 股票代码列表；None 表示用默认股票池 DEFAULT_STOCK_POOL
            strategy: 当前支持 "买入持有"（扩展点：后续可加 均线择时/定投）
            **kwargs: commission_rate(默认万3)、initial_capital(默认10万)

        Returns:
            dict: {"success", "strategy", "report", "status"}
        """
        try:
            from backtesting.engine import BacktestEngine, stock_strategy_buy_hold

            target = symbols or self.DEFAULT_STOCK_POOL
            # 规整为代码列表（DEFAULT_STOCK_POOL 形如 [(code, name), ...]）
            if target and isinstance(target[0], (list, tuple)):
                target = [c for c, _ in target]

            # 确保有数据：缓存为空或强制刷新时先抓取
            if kwargs.get("force_refresh") or not self._data_cache:
                self.fetch(target)

            if not self._data_cache:
                return {"success": False, "message": "无股票数据，抓取失败", "status": "no_data"}

            # 仅保留目标标的（若已缓存更多）
            data = {s: df for s, df in self._data_cache.items() if s in (target or self._data_cache)}
            if not data:
                data = self._data_cache

            strat_func = stock_strategy_buy_hold
            engine = BacktestEngine(
                name=f"stock_{strategy}",
                initial_capital=kwargs.get("initial_capital", 100000.0),
            )
            report = engine.run_stock(
                data, strat_func,
                commission_rate=kwargs.get("commission_rate", 0.0003),
            )
            if "error" in report:
                return {"success": False, "message": report["error"], "status": "error"}

            report["strategy"] = strategy
            report["domain_id"] = self.DOMAIN_ID
            summary = (
                f"股票回测（{strategy}）：初始 {_as_float(kwargs.get('initial_capital', 100000.0), 100000.0):.0f} → "
                f"最终 {_as_float(report.get('final_value', 0)):.2f} "
                f"(收益率 {_as_float(report.get('total_return', 0))*100:.2f}%, "
                f"最大回撤 {_as_float(report.get('max_drawdown', 0))*100:.2f}%, "
                f"夏普 {_as_float(report.get('sharpe_ratio', 0)):.2f})"
            )
            report["summary"] = summary

            return {"success": True, "strategy": strategy, "report": report, "status": "ok"}
        except Exception as e:
            logger.error("股票回测失败: %s", e)
            return {"success": False, "message": str(e), "status": "error"}

    def status(self):
        """健康状态"""
        return {
            "ready": self._initialized,
            "domain_id": self.DOMAIN_ID,
            "engines": [
                "StockFetcher" if self._fetcher else "StockFetcher(unavailable)",
                "TechnicalEngine" if self._tech_engine else "TechnicalEngine(unavailable)",
                "TrendEngine" if self._trend_engine else "TrendEngine(unavailable)",
            ],
            "cache_size": len(self._data_cache),
            "last_run": None,
            "errors": [],
        }

    # ------------------------------------------------------------------
    # 内部方法（降级模式支持）
    # ------------------------------------------------------------------

    def _generate_mock_data(self, symbol, days=250):
        """生成模拟K线数据（降级模式）"""
        import random
        import pandas as pd

        base_price = random.uniform(10, 100)
        dates = pd.date_range(end=datetime.now(), periods=days, freq="B")
        data = []

        for i, date in enumerate(dates):
            change = random.gauss(0, 0.02)  # 2% 日波动
            if i > 0:
                base_price = data[-1]["close"] * (1 + change)
            open_p = base_price * (1 + random.gauss(0, 0.005))
            close_p = base_price * (1 + random.gauss(0, 0.005))
            high_p = max(open_p, close_p) * (1 + abs(random.gauss(0, 0.01)))
            low_p = min(open_p, close_p) * (1 - abs(random.gauss(0, 0.01)))
            vol = int(random.uniform(1e6, 1e8))

            data.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": round(open_p, 2),
                "close": round(close_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "volume": vol,
            })

        return pd.DataFrame(data)

    def _calc_basic_indicators(self, df):
        """基础指标计算（纯Python，无外部依赖）"""
        if df is None or df.empty:
            return {}

        closes = df["close"].tolist() if "close" in df.columns else []
        if len(closes) < 60:
            return {"error": "数据不足60天"}

        # 简单移动平均
        def sma(values, n):
            if len(values) < n:
                return []
            return [sum(values[i - n + 1:i + 1]) / n for i in range(n - 1, len(values))]

        ma5 = sma(closes, 5)
        ma20 = sma(closes, 20)
        ma60 = sma(closes, 60)

        latest = closes[-1]
        return {
            "latest_price": latest,
            "ma5": ma5[-1] if ma5 else None,
            "ma20": ma20[-1] if ma20 else None,
            "ma60": ma60[-1] if ma60 else None,
            "ma5_list": ma5,
            "ma20_list": ma20,
            "ma60_list": ma60,
        }

    def _judge_basic_trend(self, df, indicators):
        """基础趋势判断"""
        ma5 = indicators.get("ma5")
        ma20 = indicators.get("ma20")
        ma60 = indicators.get("ma60")
        latest = indicators.get("latest_price")

        if None in (ma5, ma20, ma60, latest):
            return {"direction": "unknown", "strength": 0}

        # 多头排列判断
        bull = ma5 > ma20 > ma60
        bear = ma5 < ma20 < ma60

        if bull:
            strength = min(100, 50 + (latest - ma5) / ma5 * 1000)
            return {"direction": "up", "strength": round(strength, 1)}
        elif bear:
            strength = min(100, 50 + (ma5 - latest) / latest * 1000)
            return {"direction": "down", "strength": round(strength, 1)}
        else:
            return {"direction": "sideways", "strength": 30}

    def _generate_signals(self, result):
        """根据指标生成交易信号"""
        signals = []
        indicators = result.get("indicators", {})
        trend = result.get("trend", {})

        ma5 = indicators.get("ma5")
        ma20 = indicators.get("ma20")
        latest = indicators.get("latest_price")

        if ma5 and ma20 and latest:
            if latest > ma5 > ma20:
                signals.append("多头排列")
            elif latest < ma5 < ma20:
                signals.append("空头排列")
            if latest > ma5 and ma5 > ma20:
                signals.append("站上MA5/MA20")

        if trend.get("direction") == "up" and trend.get("strength", 0) > 70:
            signals.append("强势上涨")
        elif trend.get("direction") == "down" and trend.get("strength", 0) > 70:
            signals.append("强势下跌")

        return signals

    def _score_stock(self, result):
        """综合评分 0-100"""
        score = 50  # 基础分
        trend = result.get("trend", {})
        signals = result.get("signals", [])

        if trend.get("direction") == "up":
            score += trend.get("strength", 0) * 0.3
        elif trend.get("direction") == "down":
            score -= trend.get("strength", 0) * 0.3

        score += len(signals) * 5
        return min(100, max(0, score))

    def _calc_metrics(self, predictions, actual):
        """计算复盘指标"""
        total = len(predictions)
        if total == 0:
            return {}

        # 简化指标：按action统计
        buy_count = sum(1 for p in predictions if p.get("action") == "buy")
        hold_count = sum(1 for p in predictions if p.get("action") == "hold")

        return {
            "total_predictions": total,
            "buy_signals": buy_count,
            "hold_signals": hold_count,
            "avg_confidence": sum(p.get("confidence", 0) for p in predictions) / total,
            "hit_count": 0,  # 需要实际价格对比才能计算
            "win_rate": None,
        }

    def _save_cache(self):
        """保存数据缓存到本地"""
        try:
            cache_file = os.path.join(self.data_dir, "cache_meta.json")
            meta = {
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "symbols": list(self._data_cache.keys()),
                "count": len(self._data_cache),
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("缓存元数据保存失败: %s", e)
