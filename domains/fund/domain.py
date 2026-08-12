# -*- coding: utf-8 -*-
"""基金子系统 - 金水谣内核适配层

公募基金分析与推荐子系统：
  数据 → 净值分析 → 风险评估 → 基金经理评价 → 持仓分析 → 推荐生成

支持功能：
  - 多维度基金分析（收益率/风险/夏普比率/最大回撤）
  - 基金经理能力评价
  - 持仓集中度与行业分析
  - 基金推荐与配置建议
  - 集成AI服务生成专业推荐语

数据源：优先使用 akshare（免费基金数据），不可用时降级为模拟数据。
"""
import os
import json
import logging
from datetime import datetime
from domains.base import DomainBase, project_data_dir

logger = logging.getLogger(__name__)


def _as_float(v, default=0.0):
    """统一把任意类型转 float，避免 .get() 结果为字符串/None 时 f-string 数值格式化报错。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class FundDomain(DomainBase):
    """基金分析与推荐子系统

    基于净值数据和基本面信息的基金筛选与推荐。
    完全遵循 DomainBase 契约，可由内核统一调度。
    """
    DOMAIN_ID = "fund"
    DESCRIPTION = "基金分析（净值+风险+基金经理+持仓+推荐）"

    # 默认关注的基金池
    DEFAULT_FUNDS = [
        "000001",  # 华夏成长混合
        "110011",  # 易方达中小盘混合
        "161725",  # 招商中证白酒指数
        "005827",  # 易方达蓝筹精选混合
        "001102",  # 前海开源国家比较优势
        "519674",  # 银河创新成长混合
        "003096",  # 中欧医疗健康混合
        "001071",  # 华安媒体互联网混合
        "001875",  # 前海开源沪港深优势精选
        "260108",  # 景顺长城新兴成长混合
    ]

    def __init__(self, config=None):
        """初始化基金子系统

        Args:
            config: 子系统配置字典
        """
        super().__init__(config)
        self.data_dir = self.config.get("data_dir", project_data_dir("fund"))
        self._fetcher = None
        self._analyzer = None
        self._ai_service = None
        self._data_cache = {}  # {fund_code: {nav, info, holdings}}
        self._data_mode = {}  # {fund_code: "real"|"mock"} 数据来源诚实标记
        self._analysis_cache = {}  # {fund_code: analysis_result}
        self._last_run = None
        self._review_count = 0
        os.makedirs(self.data_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def setup(self):
        """加载基金引擎（优雅降级）

        依次加载：数据获取器、分析引擎、AI服务。
        任一模块加载失败不影响整体运行，以降级模式工作。

        Returns:
            bool: 初始化是否成功
        """
        try:
            # 1. 加载数据获取模块
            try:
                from domains.fund.fetcher import FundFetcher
                self._fetcher = FundFetcher(
                    cache_dir=os.path.join(self.data_dir, "cache")
                )
                logger.info("基金数据获取模块已加载")
            except ImportError as e:
                logger.warning("基金数据获取模块未就绪（%s），以降级模式运行", e)
                self._fetcher = None

            # 2. 加载分析引擎
            try:
                from domains.fund.analyzer import FundAnalyzer
                self._analyzer = FundAnalyzer()
                logger.info("基金分析引擎已加载")
            except ImportError as e:
                logger.warning("基金分析引擎未就绪（%s），以降级模式运行", e)
                self._analyzer = None

            # 3. 加载AI服务（可选，用于生成推荐语）
            try:
                from core.ai_service import get_ai_service
                self._ai_service = get_ai_service()
                logger.info("AI服务已关联到基金子系统")
            except ImportError as e:
                logger.info("AI服务不可用（%s），推荐语将使用模板生成", e)
                self._ai_service = None

            self._initialized = True
            logger.info(
                "基金子系统初始化完成 (降级=%s, AI=%s)",
                self._fetcher is None,
                self._ai_service is not None and self._ai_service.is_available,
            )
            return True
        except Exception as e:
            logger.error("基金子系统初始化失败: %s", e)
            return False

    def teardown(self):
        """清理资源，保存缓存数据

        Returns:
            bool: 关闭是否成功
        """
        try:
            self._save_cache()
            self._initialized = False
            logger.info("基金子系统已关闭")
            return True
        except Exception as e:
            logger.error("基金子系统关闭失败: %s", e)
            return False

    # ------------------------------------------------------------------
    # 核心流程 - fetch
    # ------------------------------------------------------------------

    def fetch(self, funds=None, **kwargs):
        """抓取基金数据

        获取指定基金的净值、基本信息和持仓数据。

        Args:
            funds: 基金代码列表，None 表示使用默认基金池
            **kwargs: 额外参数（start_date, end_date 等）

        Returns:
            dict: {
                "success": bool,
                "data": {fund_code: {nav, info, holdings}},
                "message": str,
                "mode": "real" | "mock",
            }
        """
        target = funds or self.active_funds()
        results = {}
        mock_fallback = False
        success_count = 0

        try:
            if self._fetcher:
                for code in target:
                    fund_data = {}
                    try:
                        # 获取净值数据
                        nav_df = self._fetcher.get_fund_nav(code)
                        if nav_df is not None and not nav_df.empty:
                            fund_data["nav"] = nav_df

                        # 获取基本信息
                        info = self._fetcher.get_fund_info(code)
                        if info:
                            fund_data["info"] = info

                        # 获取持仓数据
                        holdings_df = self._fetcher.get_fund_holdings(code)
                        if holdings_df is not None and not holdings_df.empty:
                            fund_data["holdings"] = holdings_df

                        if fund_data:
                            results[code] = fund_data
                            self._data_cache[code] = fund_data
                            self._data_mode[code] = "real"
                            success_count += 1
                    except Exception as e:
                        logger.warning("获取基金 %s 数据失败: %s", code, e)
            else:
                logger.warning("数据获取器未加载，全部使用模拟数据")

            # 如果真实数据获取不足，补充模拟数据
            if success_count < len(target):
                mock_fallback = True
                logger.info("补充模拟数据，目标 %d 只，已获取 %d 只", len(target), success_count)
                for code in target:
                    if code not in results:
                        results[code] = self._generate_mock_fund_data(code)
                        self._data_cache[code] = results[code]
                        self._data_mode[code] = "mock"

            self._last_run = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return {
                "success": len(results) > 0,
                "data": results,
                "message": f"获取 {len(results)}/{len(target)} 只基金数据",
                "mode": "mock" if mock_fallback else "real",
                "fund_count": len(results),
            }
        except Exception as e:
            logger.error("基金数据抓取失败: %s", e)
            return {"success": False, "data": {}, "message": str(e)}

    # ------------------------------------------------------------------
    # 核心流程 - analyze
    # ------------------------------------------------------------------

    def analyze(self, data, funds=None, **kwargs):
        """基金多维度分析

        对每只基金进行净值分析、风险评估、基金经理评价、持仓分析。

        Args:
            data: fetch() 返回的数据字典 {fund_code: {nav, info, holdings}}
            funds: 目标基金代码列表，None 表示全部

        Returns:
            dict: {
                "funds": [fund_code...],
                "results": {fund_code: analysis_result},
                "analysis_time": str,
                "status": str,
            }
        """
        try:
            if not data:
                return {
                    "funds": [],
                    "results": {},
                    "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "no_data",
                    "error": "无数据可分析",
                }

            target_funds = funds or list(data.keys())
            results = {}

            for code in target_funds:
                if code not in data:
                    continue

                fund_data = data[code]
                analysis = {}

                # 1. 净值分析（收益率 + 风险 + 夏普）
                if self._analyzer and "nav" in fund_data:
                    nav_result = self._analyzer.analyze_nav(fund_data["nav"])
                    analysis["nav_analysis"] = nav_result
                elif "nav" in fund_data:
                    # 降级：基础计算
                    analysis["nav_analysis"] = self._basic_nav_analysis(fund_data["nav"])

                # 2. 基金经理评价
                if self._analyzer and "info" in fund_data:
                    returns = analysis.get("nav_analysis", {}).get("returns", {})
                    risk = analysis.get("nav_analysis", {}).get("risk", {})
                    manager_eval = self._analyzer.evaluate_manager(
                        fund_data["info"], returns, risk, code=code
                    )
                    analysis["manager_evaluation"] = manager_eval

                # 3. 持仓分析
                if self._analyzer and "holdings" in fund_data:
                    holdings_analysis = self._analyzer.analyze_holdings(fund_data["holdings"])
                    analysis["holdings_analysis"] = holdings_analysis

                # 4. 综合评分
                if self._analyzer and "nav_analysis" in analysis:
                    score = self._analyzer.composite_score(analysis["nav_analysis"])
                    analysis["composite_score"] = score

                # 5. 基本信息透传
                if "info" in fund_data:
                    analysis["info"] = fund_data["info"]

                results[code] = analysis
                self._analysis_cache[code] = analysis

            return {
                "funds": list(results.keys()),
                "results": results,
                "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "ok" if results else "no_result",
                "total_analyzed": len(results),
            }
        except Exception as e:
            logger.error("基金分析失败: %s", e)
            return {
                "funds": [],
                "results": {},
                "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "error",
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # 核心流程 - generate
    # ------------------------------------------------------------------

    def generate(self, params=None, top_n=20, **kwargs):
        """生成基金推荐列表

        基于分析结果对基金进行排序和分级，生成 buy/hold/watch 推荐。
        集成AI服务生成专业推荐语。

        Args:
            params: analyze() 返回的分析结果
            top_n: 推荐数量

        Returns:
            dict: {
                "predictions": [...],
                "summary": str,
                "status": str,
                "domain_id": str,
            }
        """
        if not params or "results" not in params or not params["results"]:
            return {
                "predictions": [],
                "summary": "无分析数据，无法生成推荐",
                "status": "no_data",
                "domain_id": self.DOMAIN_ID,
            }

        results = params["results"]
        scored = []

        for code, r in results.items():
            # 获取综合评分
            comp = r.get("composite_score", {})
            score = comp.get("总分", 50)
            grade = comp.get("等级", "C")

            # 提取关键指标
            nav_info = r.get("nav_analysis", {})
            returns = nav_info.get("returns", {})
            risk = nav_info.get("risk", {})
            risk_adj = nav_info.get("risk_adjusted", {})

            manager_info = r.get("manager_evaluation", {})
            holdings_info = r.get("holdings_analysis", {})
            fund_info = r.get("info", {})

            scored.append({
                "fund_code": code,
                "fund_name": fund_info.get("基金名称", f"基金{code}"),
                "score": score,
                "grade": grade,
                "annual_return": returns.get("年化收益率", 0),
                "max_drawdown": risk.get("最大回撤", 0),
                "sharpe": risk_adj.get("夏普比率", 0),
                "manager": manager_info.get("基金经理", ""),
                "manager_rating": manager_info.get("评级", ""),
                "fund_type": fund_info.get("基金类型", ""),
                "style": holdings_info.get("风格倾向", "均衡"),
                "analysis": r,
            })

        # 按综合评分排序
        scored.sort(key=lambda x: x["score"], reverse=True)
        top = scored[:top_n]

        # 生成推荐列表
        predictions = []
        for item in top:
            action = self._classify_action(item)
            confidence = min(100, max(0, item["score"]))

            # 生成推荐理由
            reason = self._generate_reason(item)

            prediction = {
                "fund_code": item["fund_code"],
                "fund_name": item["fund_name"],
                "action": action,
                "confidence": round(confidence, 1),
                "grade": item["grade"],
                "annual_return": item["annual_return"],
                "max_drawdown": item["max_drawdown"],
                "sharpe_ratio": item["sharpe"],
                "manager": item["manager"],
                "manager_rating": item["manager_rating"],
                "fund_type": item["fund_type"],
                "style": item["style"],
                "reason": reason,
                "ai_recommendation": None,
            }

            predictions.append(prediction)

        # 生成AI推荐语（可选）
        self._enhance_with_ai(predictions)

        # 生成总结
        summary = self._generate_summary(predictions, len(results))

        return {
            "predictions": predictions,
            "summary": summary,
            "status": "ok",
            "domain_id": self.DOMAIN_ID,
            "total_analyzed": len(results),
            "recommended": len(predictions),
            "buy_count": sum(1 for p in predictions if p["action"] == "buy"),
            "hold_count": sum(1 for p in predictions if p["action"] == "hold"),
            "watch_count": sum(1 for p in predictions if p["action"] == "watch"),
        }

    # ------------------------------------------------------------------
    # 核心流程 - review
    # ------------------------------------------------------------------

    def review(self, predictions=None, actual=None, **kwargs):
        """复盘：基金推荐效果评估

        对比历史推荐与实际表现，统计命中率和收益率。

        Args:
            predictions: 预测记录列表 [{fund_code, action, confidence, timestamp}, ...]
            actual: 实际表现数据 {fund_code: {return_pct, ...}}

        Returns:
            dict: {
                "reviews": int,
                "hits": int,
                "updated": bool,
                "metrics": {...},
            }
        """
        try:
            if not predictions:
                self._review_count += 1
                return {
                    "reviews": 0,
                    "hits": 0,
                    "updated": True,
                    "metrics": {},
                    "status": "ok",
                    "review_count": self._review_count,
                }

            metrics = self._calc_review_metrics(predictions, actual or {})
            self._review_count += 1

            return {
                "reviews": len(predictions),
                "hits": metrics.get("hit_count", 0),
                "updated": True,
                "metrics": metrics,
                "status": "ok",
                "review_count": self._review_count,
            }
        except Exception as e:
            logger.error("基金复盘失败: %s", e)
            return {
                "reviews": 0,
                "hits": 0,
                "updated": False,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # 回测接口
    # ------------------------------------------------------------------

    def backtest(self, nav_data=None, strategy="买入持有", **kwargs):
        """基金净值回测（接入 BacktestEngine.run_fund）

        对基金历史净值运行指定策略，输出收益/回撤/夏普等指标。
        默认使用 fetch() 已缓存的净值；也可直接传入 nav_data。

        Args:
            nav_data: {fund_code: nav_records}；为空则用 self._data_cache 的 nav
            strategy: "买入持有" / "均线择时" / "定投"
            **kwargs: initial_capital(默认10万)、commission_rate(赎回费默认0.15%)

        Returns:
            dict: {"success", "strategy", "report", "status"}
        """
        try:
            from backtesting.engine import BacktestEngine, FUND_STRATEGIES

            if nav_data is None:
                nav_data = {}
                for code, fd in self._data_cache.items():
                    nav = fd.get("nav")
                    if nav is not None:
                        nav_data[code] = nav

            if not nav_data:
                return {
                    "success": False,
                    "message": "无净值数据，请先调用 fetch() 获取基金净值",
                    "status": "no_data",
                }

            strat = FUND_STRATEGIES.get(strategy, FUND_STRATEGIES["买入持有"])
            engine = BacktestEngine(
                name=f"fund_{strategy}",
                initial_capital=kwargs.get("initial_capital", 100000.0),
            )
            report = engine.run_fund(
                nav_data, strat,
                commission_rate=kwargs.get("commission_rate", 0.0015),
            )
            if "error" in report:
                return {"success": False, "message": report["error"], "status": "error"}

            report["strategy"] = strategy
            report["domain_id"] = self.DOMAIN_ID

            # 便捷摘要
            summary = (
                f"基金回测（{strategy}）："
                f"初始 {_as_float(kwargs.get('initial_capital', 100000.0), 100000.0):.0f} → "
                f"最终 {_as_float(report.get('final_value', 0)):.2f} "
                f"(收益率 {_as_float(report.get('total_return', 0))*100:.2f}%, "
                f"最大回撤 {_as_float(report.get('max_drawdown', 0))*100:.2f}%, "
                f"夏普 {_as_float(report.get('sharpe_ratio', 0)):.2f})"
            )
            report["summary"] = summary

            return {
                "success": True,
                "strategy": strategy,
                "report": report,
                "status": "ok",
            }
        except Exception as e:
            logger.error("基金回测失败: %s", e)
            return {"success": False, "message": str(e), "status": "error"}

    def simulate_dca(self, nav_data=None, amount_per_period=1000.0, every=5, **kwargs):
        """基金定投模拟（微笑曲线）

        固定金额定期买入，测算累计份额、成本摊薄与收益率曲线。
        默认用 fetch() 已缓存净值；也可直接传入 nav_data。

        Args:
            nav_data: {fund_code: nav_records} 或单只 nav；为空用 self._data_cache
            amount_per_period: 每期定投金额（默认1000）
            every: 每 N 个交易日定投一次（默认5）
            **kwargs: fee_rate(申购费默认0.15%)、start_index(默认1)

        Returns:
            dict: {"success", "report", "status"}
        """
        try:
            from backtesting.engine import BacktestEngine

            if nav_data is None:
                nav_data = {}
                for code, fd in self._data_cache.items():
                    nav = fd.get("nav")
                    if nav is not None:
                        nav_data[code] = nav

            if not nav_data:
                return {
                    "success": False,
                    "message": "无净值数据，请先调用 fetch() 获取基金净值",
                    "status": "no_data",
                }

            engine = BacktestEngine(name="fund_dca")
            report = engine.simulate_dca(
                nav_data,
                amount_per_period=amount_per_period,
                every=every,
                fee_rate=kwargs.get("fee_rate", 0.0015),
                start_index=kwargs.get("start_index", 1),
            )
            if "error" in report:
                return {"success": False, "message": report["error"], "status": "error"}

            report["domain_id"] = self.DOMAIN_ID
            return {
                "success": True,
                "report": report,
                "status": "ok",
            }
        except Exception as e:
            logger.error("基金定投模拟失败: %s", e)
            return {"success": False, "message": str(e), "status": "error"}

    def compare_funds(self, codes=None, top_n=None, **kwargs):
        """基金横向对比视图（多基金同屏对比）

        对一组基金做净值分析 + 风险 + 夏普 + 经理任职(含来源) + 综合评分的横向对比，
        便于用户一眼挑基金。优先复用 fetch() 已缓存数据；必要时先抓取。

        Args:
            codes: 基金代码列表；None 表示用默认基金池 DEFAULT_FUNDS
            top_n: 返回前 N 只（按综合评分降序）；None 表示全部
            **kwargs: force_refresh(bool) 强制重新抓取

        Returns:
            dict: {"success", "comparison":[{...}], "count", "status", "mode"}
        """
        try:
            target = codes or self.active_funds()

            # 确保有数据
            need_fetch = kwargs.get("force_refresh", False) or not self._data_cache
            if need_fetch:
                fetch_res = self.fetch(target)
                mode = fetch_res.get("mode", "mock")
            else:
                mode = "cached"

            if not self._data_cache:
                return {"success": False, "message": "无基金数据，抓取失败", "status": "no_data"}

            # 仅分析目标基金（取已在缓存中的）
            analyze_input = {c: self._data_cache[c] for c in target if c in self._data_cache}
            if not analyze_input:
                analyze_input = self._data_cache

            analysis = self.analyze(analyze_input, funds=list(analyze_input.keys()))

            comparison = []
            for code, r in analysis.get("results", {}).items():
                nav = r.get("nav_analysis", {})
                returns = nav.get("returns", {})
                risk = nav.get("risk", {})
                risk_adj = nav.get("risk_adjusted", {})
                comp = r.get("composite_score", {})
                manager = r.get("manager_evaluation", {})
                holdings = r.get("holdings_analysis", {})
                info = r.get("info", {})

                comparison.append({
                    "code": code,
                    "name": info.get("基金名称", f"基金{code}"),
                    "type": info.get("基金类型", ""),
                    "scale": info.get("基金规模(亿元)"),
                    "annual_return": returns.get("年化收益率"),
                    "return_1y": returns.get("近1年"),
                    "max_drawdown": risk.get("最大回撤"),
                    "sharpe": risk_adj.get("夏普比率"),
                    "score": comp.get("总分"),
                    "grade": comp.get("等级"),
                    "manager": manager.get("基金经理", ""),
                    "manager_rating": manager.get("评级", ""),
                    "tenure_source": manager.get("任职年限来源"),
                    "style": holdings.get("风格倾向", "均衡"),
                })

            # 综合评分降序（None 排最后）
            comparison.sort(
                key=lambda x: (x.get("score") is not None, x.get("score") or 0),
                reverse=True,
            )
            if top_n:
                comparison = comparison[:top_n]

            return {
                "success": True,
                "comparison": comparison,
                "count": len(comparison),
                "mode": mode,
                "status": "ok",
                "domain_id": self.DOMAIN_ID,
            }
        except Exception as e:
            logger.error("基金对比失败: %s", e)
            return {"success": False, "message": str(e), "status": "error"}

    # ------------------------------------------------------------------
    # 分析基金池（用户持仓优先）
    # ------------------------------------------------------------------

    def active_funds(self):
        """当前分析基金池：优先取用户持仓列表，为空时回退内置池。

        用户持仓（FundDataManager）即"关注列表"的唯一真源：
        持仓管理页 / 桌面基金 GUI / 分析引擎共用同一份名单。
        """
        try:
            from domains.fund.fund_data_manager import FundDataManager
            mgr = FundDataManager()
            codes = [h.get("code") for h in mgr.get_holdings() if h.get("code")]
            if codes:
                return codes
        except Exception as e:
            logger.warning("读取用户持仓失败，回退内置基金池: %s", e)
        return self.DEFAULT_FUNDS

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def status(self):
        """子系统健康状态

        Returns:
            dict: 健康状态信息
        """
        return {
            "ready": self._initialized,
            "domain_id": self.DOMAIN_ID,
            "description": self.DESCRIPTION,
            "engines": [
                "FundFetcher" if self._fetcher else "FundFetcher(unavailable)",
                "FundAnalyzer" if self._analyzer else "FundAnalyzer(unavailable)",
                "AIService" if (self._ai_service and self._ai_service.is_available) else "AIService(unavailable)",
            ],
            "cache_size": len(self._data_cache),
            "analysis_cache_size": len(self._analysis_cache),
            "last_run": self._last_run,
            "review_count": self._review_count,
            "default_funds": len(self.DEFAULT_FUNDS),
            "active_funds": len(self.active_funds()) or len(self.DEFAULT_FUNDS),
            "errors": [],
        }

    # ==================================================================
    # 内部方法
    # ==================================================================

    # ------------------------------------------------------------------
    # 推荐分类
    # ------------------------------------------------------------------

    def _classify_action(self, item):
        """根据评分和指标分类推荐动作

        Args:
            item: 带评分的基金数据

        Returns:
            str: "buy" | "hold" | "watch"
        """
        score = item["score"]
        grade = item["grade"]
        max_dd = item["max_drawdown"]

        # A+ / A 级且最大回撤可控 → 买入
        if grade in ("A+", "A") and (isinstance(max_dd, (int, float)) and max_dd > -25):
            return "buy"

        # B 级 → 持有
        if grade == "B" or score >= 60:
            return "hold"

        # C 级及以下 → 观望
        return "watch"

    # ------------------------------------------------------------------
    # 推荐理由生成
    # ------------------------------------------------------------------

    def _generate_reason(self, item):
        """生成推荐理由文本

        Args:
            item: 基金分析数据

        Returns:
            str: 推荐理由
        """
        parts = []

        # 收益表现
        annual = item["annual_return"]
        if isinstance(annual, (int, float)):
            if annual > 15:
                parts.append(f"年化收益{annual:.1f}%表现优秀")
            elif annual > 8:
                parts.append(f"年化收益{annual:.1f}%良好")
            elif annual > 0:
                parts.append(f"年化收益{annual:.1f}%一般")
            else:
                parts.append(f"年化收益{annual:.1f}%偏弱")

        # 风险控制
        max_dd = item["max_drawdown"]
        if isinstance(max_dd, (int, float)):
            if max_dd > -15:
                parts.append("回撤控制优秀")
            elif max_dd > -25:
                parts.append("回撤可控")
            else:
                parts.append("回撤较大")

        # 夏普比率
        sharpe = item["sharpe"]
        if isinstance(sharpe, (int, float)):
            if sharpe > 1.5:
                parts.append("性价比极高")
            elif sharpe > 1.0:
                parts.append("性价比良好")
            elif sharpe > 0.5:
                parts.append("性价比一般")

        # 基金经理
        if item.get("manager_rating") == "优秀":
            parts.append(f"基金经理{item['manager']}能力优秀")
        elif item.get("manager_rating") == "良好":
            parts.append(f"基金经理{item['manager']}能力良好")

        # 风格
        if item.get("style"):
            parts.append(f"{item['style']}风格")

        return "，".join(parts) if parts else "综合评估"

    # ------------------------------------------------------------------
    # AI 增强推荐
    # ------------------------------------------------------------------

    def _enhance_with_ai(self, predictions):
        """使用AI服务增强推荐语

        Args:
            predictions: 推荐列表（就地修改，添加 ai_recommendation 字段）
        """
        if not self._ai_service or not self._ai_service.is_available:
            return

        # 仅对前5只生成AI推荐（节省token）
        for pred in predictions[:5]:
            try:
                # 构造分析内容
                content = (
                    f"基金：{pred['fund_name']}（{pred['fund_code']}）\n"
                    f"类型：{pred['fund_type']}\n"
                    f"年化收益：{pred['annual_return']}%\n"
                    f"最大回撤：{pred['max_drawdown']}%\n"
                    f"夏普比率：{pred['sharpe_ratio']}\n"
                    f"基金经理：{pred['manager']}（{pred['manager_rating']}）\n"
                    f"投资风格：{pred['style']}\n"
                    f"综合评级：{pred['grade']}\n"
                    f"建议：{pred['action']}\n"
                    f"理由：{pred['reason']}\n"
                )

                ai_text = self._ai_service.analyze(
                    "fund", content,
                    extra_system="请针对这只基金给出简洁的投资建议和风险提示，控制在100字以内。"
                )

                if ai_text:
                    pred["ai_recommendation"] = ai_text.strip()

            except Exception as e:
                logger.debug("AI推荐生成失败 %s: %s", pred["fund_code"], e)

    # ------------------------------------------------------------------
    # 总结生成
    # ------------------------------------------------------------------

    def _generate_summary(self, predictions, total_analyzed):
        """生成整体推荐总结

        Args:
            predictions: 推荐列表
            total_analyzed: 分析的基金总数

        Returns:
            str: 总结文本
        """
        buy_count = sum(1 for p in predictions if p["action"] == "buy")
        hold_count = sum(1 for p in predictions if p["action"] == "hold")
        watch_count = sum(1 for p in predictions if p["action"] == "watch")

        avg_score = sum(p["confidence"] for p in predictions) / len(predictions) if predictions else 0

        return (
            f"共分析 {total_analyzed} 只基金，推荐 {len(predictions)} 只。"
            f"其中买入 {buy_count} 只，持有 {hold_count} 只，观望 {watch_count} 只。"
            f"平均置信度 {avg_score:.1f} 分。"
        )

    # ------------------------------------------------------------------
    # 复盘指标计算
    # ------------------------------------------------------------------

    def _calc_review_metrics(self, predictions, actual):
        """计算复盘指标

        Args:
            predictions: 预测记录列表
            actual: 实际数据

        Returns:
            dict: 复盘指标
        """
        total = len(predictions)
        if total == 0:
            return {}

        buy_count = sum(1 for p in predictions if p.get("action") == "buy")
        hold_count = sum(1 for p in predictions if p.get("action") == "hold")
        watch_count = sum(1 for p in predictions if p.get("action") == "watch")

        # 计算命中率（如果有实际数据）
        hit_count = 0
        total_return = 0
        valid_count = 0

        for pred in predictions:
            code = pred.get("fund_code", "")
            action = pred.get("action", "")
            if code in actual:
                actual_return = actual[code].get("return_pct", 0)
                valid_count += 1
                total_return += actual_return

                # 买入且正收益 = 命中
                if action == "buy" and actual_return > 0:
                    hit_count += 1
                # 观望且负收益 = 命中
                elif action == "watch" and actual_return < 0:
                    hit_count += 1
                # 持有 = 中性，也算命中
                elif action == "hold":
                    hit_count += 1

        return {
            "total_predictions": total,
            "buy_signals": buy_count,
            "hold_signals": hold_count,
            "watch_signals": watch_count,
            "avg_confidence": sum(p.get("confidence", 0) for p in predictions) / total,
            "hit_count": hit_count,
            "win_rate": round(hit_count / valid_count * 100, 2) if valid_count > 0 else None,
            "avg_actual_return": round(total_return / valid_count, 2) if valid_count > 0 else None,
        }

    # ------------------------------------------------------------------
    # 降级模式 - 基础净值分析
    # ------------------------------------------------------------------

    def _basic_nav_analysis(self, nav_df):
        """基础净值分析（无分析引擎时的降级模式）

        Args:
            nav_df: 净值数据

        Returns:
            dict: 基础分析结果
        """
        try:
            navs = []
            if hasattr(nav_df, "columns") and "单位净值" in nav_df.columns:
                navs = nav_df["单位净值"].tolist()
            elif isinstance(nav_df, list):
                navs = [row.get("单位净值", 0) for row in nav_df if isinstance(row, dict)]

            if not navs or len(navs) < 10:
                return {"error": "数据不足"}

            latest = navs[-1]
            total = len(navs)

            def _ret(n):
                idx = max(0, total - n - 1)
                return round((latest - navs[idx]) / navs[idx] * 100, 2) if navs[idx] else 0

            returns = {
                "近1月": _ret(21),
                "近3月": _ret(63),
                "近6月": _ret(126),
                "近1年": _ret(252),
                "年化收益率": _ret(252),
            }

            # 简单最大回撤
            peak = navs[0]
            max_dd = 0
            for nav in navs:
                if nav > peak:
                    peak = nav
                dd = (peak - nav) / peak if peak else 0
                if dd > max_dd:
                    max_dd = dd

            risk = {
                "最大回撤": round(max_dd * 100, 2),
            }

            return {
                "returns": returns,
                "risk": risk,
                "summary": f"年化{returns['年化收益率']}%，最大回撤{risk['最大回撤']}%",
            }
        except Exception as e:
            return {"error": f"基础分析失败: {e}"}

    # ------------------------------------------------------------------
    # 模拟数据生成
    # ------------------------------------------------------------------

    def _generate_mock_fund_data(self, fund_code):
        """生成模拟基金完整数据（降级模式）

        Args:
            fund_code: 基金代码

        Returns:
            dict: {nav, info, holdings}
        """
        import random
        import pandas as pd
        from datetime import datetime

        random.seed(hash(fund_code) % (2**32))

        # 模拟净值
        days = 365
        base_nav = 1.0 + (hash(fund_code) % 200) / 100.0
        annual_return = 0.05 + (hash(fund_code + "r") % 200) / 1000.0
        volatility = 0.15 + (hash(fund_code + "v") % 200) / 1000.0

        dates = pd.date_range(end=datetime.now(), periods=days, freq="B")
        daily_ret = annual_return / 252
        daily_vol = volatility / (252 ** 0.5)

        nav_data = []
        nav = base_nav
        cum_nav = base_nav * 1.5
        prev_nav = base_nav

        for date in dates:
            shock = random.gauss(daily_ret, daily_vol)
            nav = nav * (1 + shock)
            cum_nav = cum_nav * (1 + shock)
            daily_growth = (nav - prev_nav) / prev_nav * 100 if prev_nav else 0

            nav_data.append({
                "净值日期": date.strftime("%Y-%m-%d"),
                "单位净值": round(nav, 4),
                "累计净值": round(cum_nav, 4),
                "日增长率": round(daily_growth, 2),
            })
            prev_nav = nav

        # 模拟基金信息
        mock_names = {
            "000001": ("华夏成长混合", "王亚伟", "混合型", 150.5, "2001-12-18", "2015-03-01"),
            "110011": ("易方达中小盘混合", "张坤", "混合型", 280.3, "2008-06-19", "2012-09-28"),
            "161725": ("招商中证白酒指数", "侯昊", "指数型", 650.8, "2015-05-27", "2017-05-01"),
            "005827": ("易方达蓝筹精选混合", "张坤", "混合型", 520.6, "2018-09-05", "2018-09-05"),
            "519674": ("银河创新成长混合", "郑巍山", "混合型", 120.4, "2010-12-29", "2019-01-01"),
            "003096": ("中欧医疗健康混合", "葛兰", "混合型", 410.7, "2016-09-29", "2016-09-29"),
            "260108": ("景顺长城新兴成长混合", "刘彦春", "混合型", 350.2, "2009-06-18", "2015-04-01"),
        }

        if fund_code in mock_names:
            name, manager, ftype, scale, found_date, tenure_date = mock_names[fund_code]
        else:
            name = f"基金{fund_code}"
            manager = f"经理{fund_code[-2:]}"
            ftype = "混合型"
            scale = round(50 + random.random() * 300, 1)
            found_date = f"20{15 + random.randint(0, 8)}-01-01"
            tenure_date = found_date  # 无真实数据：默认同成立日期（analyzer 会标注估算）

        info = {
            "基金代码": fund_code,
            "基金名称": name,
            "基金经理": manager,
            "基金类型": ftype,
            "基金规模(亿元)": scale,
            "成立日期": found_date,
            "任职日期": tenure_date,
            "基金公司": f"{name[:2]}基金",
        }

        # 模拟持仓
        stocks = [
            ("600519", "贵州茅台", 9.85),
            ("000858", "五粮液", 8.32),
            ("601318", "中国平安", 6.75),
            ("000333", "美的集团", 5.42),
            ("600036", "招商银行", 4.98),
            ("002594", "比亚迪", 4.56),
            ("300750", "宁德时代", 4.21),
            ("601899", "紫金矿业", 3.89),
            ("002415", "海康威视", 3.56),
            ("600900", "长江电力", 3.21),
        ]
        random.shuffle(stocks)
        holdings_data = [
            {"股票代码": code, "股票名称": name, "占净值比例": round(ratio * (0.8 + random.random() * 0.4), 2)}
            for code, name, ratio in stocks
        ]

        random.seed()

        return {
            "nav": pd.DataFrame(nav_data),
            "info": info,
            "holdings": pd.DataFrame(holdings_data),
        }

    # ------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------

    def _save_cache(self):
        """保存缓存元数据到本地"""
        try:
            cache_file = os.path.join(self.data_dir, "cache_meta.json")
            meta = {
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "funds": list(self._data_cache.keys()),
                "count": len(self._data_cache),
                "review_count": self._review_count,
                "last_run": self._last_run,
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("缓存元数据保存失败: %s", e)
