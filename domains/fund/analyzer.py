# -*- coding: utf-8 -*-
"""基金分析引擎

对基金净值数据进行多维度分析：
  - 收益率分析（近1月/3月/6月/1年/3年/成立以来）
  - 风险评估（最大回撤、波动率、下行风险）
  - 夏普比率、索提诺比率
  - 基金经理评价
  - 持仓集中度分析
"""
import math
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class FundAnalyzer:
    """基金分析引擎

    提供多维度基金分析能力，纯Python实现，无pandas强依赖时降级为基础计算。
    所有方法返回结构化 dict，便于上层调用和序列化。
    """

    def __init__(self):
        """初始化分析引擎"""
        self._risk_free_rate = 0.02  # 无风险利率默认2%（年化）
        self._trading_days = 252  # 年化交易日数

    # ------------------------------------------------------------------
    # 综合分析入口
    # ------------------------------------------------------------------

    def analyze_nav(self, nav_df):
        """净值综合分析

        对基金净值数据进行全面分析，包括收益率、风险、风险调整收益等。

        Args:
            nav_df: 净值数据DataFrame，需包含 [净值日期, 单位净值] 列

        Returns:
            dict: 综合分析结果
                {
                    "returns": {...},        # 收益率分析
                    "risk": {...},           # 风险评估
                    "risk_adjusted": {...},  # 风险调整收益
                    "drawdown": {...},       # 回撤分析
                    "summary": str           # 摘要
                }
        """
        if nav_df is None or self._is_empty(nav_df):
            return {"error": "净值数据为空", "summary": "数据不足，无法分析"}

        navs = self._extract_nav_series(nav_df)
        dates = self._extract_date_series(nav_df)

        if len(navs) < 30:
            return {"error": f"数据不足30条，当前{len(navs)}条", "summary": "数据量不足，分析结果仅供参考"}

        result = {}

        # 1. 收益率分析
        result["returns"] = self.calculate_returns(navs, dates)

        # 2. 风险评估
        result["risk"] = self.calculate_risk(navs)

        # 3. 风险调整收益（夏普比率等）
        result["risk_adjusted"] = self.calculate_sharpe(navs)

        # 4. 回撤分析
        result["drawdown"] = self.calculate_drawdown(navs, dates)

        # 5. 生成摘要
        result["summary"] = self._generate_summary(result)

        return result

    # ------------------------------------------------------------------
    # 收益率分析
    # ------------------------------------------------------------------

    def calculate_returns(self, navs, dates=None):
        """计算各周期收益率

        Args:
            navs: 单位净值列表（按时间升序）
            dates: 日期列表（与navs一一对应），可选

        Returns:
            dict: 各周期收益率
                {
                    "近1周": float,
                    "近1月": float,
                    "近3月": float,
                    "近6月": float,
                    "近1年": float,
                    "近3年": float,
                    "今年来": float,
                    "成立来": float,
                    "年化收益率": float,
                }
        """
        if not navs or len(navs) < 5:
            return {"error": "数据不足"}

        latest = navs[-1]
        total = len(navs)

        def _return_n(period_days):
            """获取指定交易日前的收益率"""
            idx = max(0, total - period_days - 1)
            if navs[idx] == 0:
                return 0
            return round((latest - navs[idx]) / navs[idx] * 100, 2)

        # 近似交易日数：周=5，月=21，3月=63，6月=126，1年=252，3年=756
        returns = {
            "近1周": _return_n(5),
            "近1月": _return_n(21),
            "近3月": _return_n(63),
            "近6月": _return_n(126),
            "近1年": _return_n(252),
            "近3年": _return_n(756),
        }

        # 今年来收益率
        if dates:
            this_year_start = None
            for i, d in enumerate(dates):
                if str(d).startswith(str(datetime.now().year)):
                    this_year_start = i
                    break
            if this_year_start is not None and navs[this_year_start] != 0:
                returns["今年来"] = round((latest - navs[this_year_start]) / navs[this_year_start] * 100, 2)
            else:
                returns["今年来"] = _return_n(total - 1)
        else:
            returns["今年来"] = _return_n(total - 1)

        # 成立来收益率
        if navs[0] != 0:
            returns["成立来"] = round((latest - navs[0]) / navs[0] * 100, 2)
        else:
            returns["成立来"] = 0

        # 年化收益率（几何平均）
        years = total / self._trading_days
        if years > 0 and navs[0] > 0:
            total_return = latest / navs[0]
            if total_return > 0:
                returns["年化收益率"] = round((total_return ** (1 / years) - 1) * 100, 2)
            else:
                returns["年化收益率"] = 0
        else:
            returns["年化收益率"] = returns.get("近1年", 0)

        return returns

    # ------------------------------------------------------------------
    # 风险评估
    # ------------------------------------------------------------------

    def calculate_risk(self, navs):
        """计算风险指标

        Args:
            navs: 单位净值列表（按时间升序）

        Returns:
            dict: 风险指标
                {
                    "波动率(年化)": float,      # 标准差年化
                    "最大回撤": float,           # 最大回撤百分比
                    "最大回撤期数": int,         # 最大回撤持续期数
                    "下行波动率": float,         # 仅考虑负收益的波动率
                    "正收益占比": float,         # 正收益交易日占比
                    "盈亏比": float,             # 平均盈利 / 平均亏损绝对值
                }
        """
        if not navs or len(navs) < 10:
            return {"error": "数据不足"}

        # 计算日收益率
        daily_returns = []
        for i in range(1, len(navs)):
            if navs[i - 1] != 0:
                daily_returns.append((navs[i] - navs[i - 1]) / navs[i - 1])
            else:
                daily_returns.append(0)

        if not daily_returns:
            return {"error": "无法计算收益率"}

        n = len(daily_returns)
        mean_ret = sum(daily_returns) / n

        # 波动率（年化）
        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / (n - 1) if n > 1 else 0
        volatility = math.sqrt(variance) * math.sqrt(self._trading_days)

        # 下行波动率（仅负收益）
        negative_returns = [r for r in daily_returns if r < 0]
        if negative_returns:
            neg_mean = sum(negative_returns) / len(negative_returns)
            neg_var = sum((r - neg_mean) ** 2 for r in negative_returns) / len(negative_returns)
            downside_vol = math.sqrt(neg_var) * math.sqrt(self._trading_days)
        else:
            downside_vol = 0

        # 最大回撤
        max_dd, max_dd_period = self._calc_max_drawdown(navs)

        # 正收益占比
        positive_count = sum(1 for r in daily_returns if r > 0)
        positive_ratio = positive_count / n if n else 0

        # 盈亏比
        gains = [r for r in daily_returns if r > 0]
        losses = [abs(r) for r in daily_returns if r < 0]
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_loss_ratio = avg_gain / avg_loss if avg_loss else float("inf")

        return {
            "波动率(年化)": round(volatility * 100, 2),
            "最大回撤": round(max_dd * 100, 2),
            "最大回撤期数": max_dd_period,
            "下行波动率": round(downside_vol * 100, 2),
            "正收益占比": round(positive_ratio * 100, 2),
            "盈亏比": round(profit_loss_ratio, 2) if profit_loss_ratio != float("inf") else "∞",
        }

    # ------------------------------------------------------------------
    # 夏普比率
    # ------------------------------------------------------------------

    def calculate_sharpe(self, navs, risk_free=0.02):
        """计算夏普比率及相关风险调整收益指标

        Args:
            navs: 单位净值列表（按时间升序）
            risk_free: 年化无风险利率，默认0.02（2%）

        Returns:
            dict: 风险调整收益指标
                {
                    "夏普比率": float,         # 经典夏普比率
                    "索提诺比率": float,         # 仅考虑下行风险
                    "卡玛比率": float,          # 年化收益 / 最大回撤
                    "特雷诺比率": float,        # （如无beta数据则留空）
                    "信息比率": float,          # （如无基准则留空）
                }
        """
        if not navs or len(navs) < 30:
            return {"error": "数据不足"}

        # 日收益率
        daily_returns = []
        for i in range(1, len(navs)):
            if navs[i - 1] != 0:
                daily_returns.append((navs[i] - navs[i - 1]) / navs[i - 1])

        if not daily_returns:
            return {"error": "无法计算收益率"}

        n = len(daily_returns)
        mean_daily = sum(daily_returns) / n

        # 年化收益率
        annual_return = mean_daily * self._trading_days
        excess_return = annual_return - risk_free

        # 波动率（年化）
        variance = sum((r - mean_daily) ** 2 for r in daily_returns) / (n - 1) if n > 1 else 0
        volatility = math.sqrt(variance) * math.sqrt(self._trading_days)

        # 夏普比率
        sharpe = excess_return / volatility if volatility else 0

        # 索提诺比率（仅下行风险）
        negative_returns = [r for r in daily_returns if r < 0]
        if negative_returns:
            neg_mean = sum(negative_returns) / len(negative_returns)
            neg_var = sum((r - neg_mean) ** 2 for r in negative_returns) / len(negative_returns)
            downside_vol = math.sqrt(neg_var) * math.sqrt(self._trading_days)
            sortino = excess_return / downside_vol if downside_vol else 0
        else:
            sortino = float("inf") if excess_return > 0 else 0

        # 卡玛比率（年化收益 / 最大回撤）
        max_dd, _ = self._calc_max_drawdown(navs)
        calmar = annual_return / max_dd if max_dd != 0 else float("inf")

        result = {
            "夏普比率": round(sharpe, 2),
            "索提诺比率": round(sortino, 2) if sortino != float("inf") else "∞",
            "卡玛比率": round(calmar, 2) if calmar != float("inf") else "∞",
            "特雷诺比率": None,  # 需要beta数据
            "信息比率": None,    # 需要基准数据
            "年化超额收益": round(excess_return * 100, 2),
        }

        return result

    # ------------------------------------------------------------------
    # 回撤分析
    # ------------------------------------------------------------------

    def calculate_drawdown(self, navs, dates=None):
        """详细回撤分析

        Args:
            navs: 单位净值列表
            dates: 日期列表

        Returns:
            dict: 回撤分析详情
                {
                    "最大回撤": float,
                    "最大回撤开始": str,
                    "最大回撤结束": str,
                    "最大回撤修复天数": int,
                    "回撤次数": int,
                    "平均回撤": float,
                }
        """
        if not navs or len(navs) < 10:
            return {"error": "数据不足"}

        max_dd, _, peak_idx, trough_idx, recovery_idx = self._calc_max_drawdown_detail(navs)

        # 统计回撤次数（超过5%的回撤）
        drawdowns = self._find_drawdowns(navs, threshold=0.05)

        result = {
            "最大回撤": round(max_dd * 100, 2),
            "回撤次数": len(drawdowns),
            "平均回撤": round(sum(d["depth"] for d in drawdowns) / len(drawdowns) * 100, 2) if drawdowns else 0,
        }

        if dates:
            date_list = [str(d) for d in dates]
            if peak_idx < len(date_list):
                result["最大回撤开始"] = date_list[peak_idx]
            if trough_idx < len(date_list):
                result["最大回撤底部"] = date_list[trough_idx]
            if recovery_idx is not None and recovery_idx < len(date_list):
                result["最大回撤修复日期"] = date_list[recovery_idx]
                result["修复天数(交易日)"] = recovery_idx - peak_idx
            else:
                result["修复状态"] = "尚未修复"
                result["持续天数(交易日)"] = len(navs) - peak_idx

        return result

    # ------------------------------------------------------------------
    # 基金经理评价
    # ------------------------------------------------------------------

    def evaluate_manager(self, info_dict, returns=None, risk=None, code=None):
        """基金经理综合评价

        Args:
            info_dict: 基金信息字典（含基金经理、规模、成立日期、任职日期等）
            returns: 收益率分析结果（可选）
            risk: 风险分析结果（可选）
            code: 基金代码（可选，用于实时抓取真实任职日期）

        Returns:
            dict: 基金经理评价
                {
                    "基金经理": str,
                    "任职年限": float,
                    "任职年限来源": str,   # real/provided/estimate_founding/unknown
                    "管理规模": float,
                    "业绩评分": float,
                    "风控评分": float,
                    "综合评分": float,
                    "评级": str,     # 优秀/良好/一般/较差
                    "评价": str,
                }
        """
        manager = info_dict.get("基金经理", "未知")
        scale = info_dict.get("基金规模(亿元)", 0)
        found_date = info_dict.get("成立日期", "")
        tenure_date = info_dict.get("任职日期", "")  # 真实任职起始日（上游提供时优先）

        # 计算任职年限：优先真实任职日期，成立日期仅作标注估算（不再冒充任职期）
        years, tenure_source = self._resolve_tenure_years(code, tenure_date, found_date)

        # 业绩评分
        perf_score = 50
        if returns:
            annual = returns.get("年化收益率", 0)
            if isinstance(annual, (int, float)):
                perf_score = min(100, max(0, 50 + annual * 2))  # 每1%年化加2分

        # 风控评分
        risk_score = 50
        if risk:
            max_dd = risk.get("最大回撤", 0)
            if isinstance(max_dd, (int, float)):
                # 最大回撤越小分越高，0回撤=100分，-30%回撤=0分
                risk_score = min(100, max(0, 100 + max_dd * (100 / 30)))
            vol = risk.get("波动率(年化)", 0)
            if isinstance(vol, (int, float)):
                # 波动率也纳入考虑
                risk_score = risk_score * 0.7 + min(100, max(0, 100 - vol * 2)) * 0.3

        # 任职年限加分（经验加分）
        exp_bonus = min(10, years * 1)

        # 规模适中加分（50-200亿最佳）
        scale_score = 50
        if isinstance(scale, (int, float)):
            if 50 <= scale <= 200:
                scale_score = 80
            elif 20 <= scale < 50 or 200 < scale <= 500:
                scale_score = 65
            else:
                scale_score = 50

        # 综合评分
        composite = perf_score * 0.4 + risk_score * 0.3 + exp_bonus + scale_score * 0.2
        composite = min(100, max(0, composite))

        # 评级
        if composite >= 80:
            rating = "优秀"
        elif composite >= 65:
            rating = "良好"
        elif composite >= 50:
            rating = "一般"
        else:
            rating = "较差"

        # 文字评价
        eval_text = self._manager_eval_text(manager, rating, composite, years, scale)

        return {
            "基金经理": manager,
            "任职年限": round(years, 1),
            "任职年限来源": tenure_source,
            "管理规模(亿元)": scale,
            "业绩评分": round(perf_score, 1),
            "风控评分": round(risk_score, 1),
            "规模评分": round(scale_score, 1),
            "综合评分": round(composite, 1),
            "评级": rating,
            "评价": eval_text,
        }

    # ------------------------------------------------------------------
    # 基金经理任职年限解析（真实数据优先）
    # ------------------------------------------------------------------

    def _resolve_tenure_years(self, code, tenure_date, found_date):
        """解析基金经理任职年限，返回 (年限, 来源)

        优先级：①实时抓取真实任职日期(akshare) > ②上游提供任职日期 > ③成立日期估算。
        成立日期被明确标记为估算(estimate_founding)，不再冒充真实任职期。
        """
        # ① 实时抓取基金经理真实任职日期（akshare）
        if code:
            real = self._fetch_real_manager_tenure(code)
            if real is not None:
                return real, "real"
        # ② 上游已提供任职日期（如 mock/缓存携带真实值）
        if tenure_date:
            y = self._years_since(tenure_date)
            if y is not None:
                return y, "provided"
        # ③ 兜底：用成立日期估算（明确标记非真实任职期）
        if found_date:
            y = self._years_since(found_date)
            if y is not None:
                return y, "estimate_founding"
        return 3.0, "unknown"

    @staticmethod
    def _years_since(datestr):
        """计算距今天数/365.25，解析失败返回 None"""
        try:
            from datetime import datetime
            d = datetime.strptime(str(datestr)[:10], "%Y-%m-%d")
            return (datetime.now() - d).days / 365.25
        except Exception:
            return None

    def _fetch_real_manager_tenure(self, code):
        """实时抓取基金经理真实任职日期 → 任职年限（优先 akshare）

        失败时返回 None（fail-safe，不影响主流程），由上层降级为估算。
        """
        try:
            import akshare as ak
            df = ak.fund_manager_em(symbol=str(code))
            if df is None or len(df) == 0:
                return None
            row = df.iloc[0]  # 首行通常为当前经理
            date_val = None
            for col in ("任职日期", "任职开始", "起始时间"):
                if col in getattr(df, "columns", []):
                    date_val = row[col]
                    break
            if date_val is None:
                return None
            return self._years_since(str(date_val))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 持仓分析
    # ------------------------------------------------------------------

    def analyze_holdings(self, holdings_df):
        """持仓集中度与行业分析

        Args:
            holdings_df: 持仓数据DataFrame

        Returns:
            dict: 持仓分析结果
                {
                    "十大重仓占比": float,         # 前十大重仓合计占比
                    "第一大重仓占比": float,       # 最大持仓占比
                    "持仓集中度(HHI)": float,      # 赫芬达尔指数
                    "持股数量": int,
                    "行业分布": dict,              # 行业估算分布
                    "风格倾向": str,               # 价值/成长/均衡
                }
        """
        if holdings_df is None or self._is_empty(holdings_df):
            return {"error": "持仓数据为空"}

        ratios = self._extract_ratio_series(holdings_df)

        if not ratios:
            return {"error": "无法提取持仓比例"}

        total_ratio = sum(ratios)
        top1_ratio = max(ratios) if ratios else 0

        # HHI 赫芬达尔指数（越高越集中）
        hhi = sum(r ** 2 for r in ratios)

        # 行业估算（简化版，根据股票代码/名称粗略分类）
        industry_dist = self._estimate_industry(holdings_df)

        # 风格倾向（根据行业分布估算）
        style = self._estimate_style(industry_dist)

        return {
            "十大重仓占比": round(total_ratio, 2),
            "第一大重仓占比": round(top1_ratio, 2),
            "持仓集中度(HHI)": round(hhi, 2),
            "持股数量": len(ratios),
            "行业分布": industry_dist,
            "风格倾向": style,
            "集中度评价": "高" if total_ratio > 60 else "中" if total_ratio > 40 else "低",
        }

    # ------------------------------------------------------------------
    # 综合评分
    # ------------------------------------------------------------------

    def composite_score(self, analysis_result):
        """基金综合评分（0-100）

        Args:
            analysis_result: analyze_nav 返回的完整分析结果

        Returns:
            dict: {
                "总分": float,
                "收益得分": float,
                "风险得分": float,
                "性价比得分": float,
                "等级": str,    # A+/A/B/C/D
                "建议": str,
            }
        """
        if not analysis_result or "error" in analysis_result:
            return {"总分": 0, "等级": "N/A", "建议": "数据不足"}

        returns = analysis_result.get("returns", {})
        risk = analysis_result.get("risk", {})
        risk_adj = analysis_result.get("risk_adjusted", {})

        # 收益得分（40%权重）
        annual = returns.get("年化收益率", 0)
        if isinstance(annual, (int, float)):
            # 0%=30分，10%=60分，20%=85分，30%+=100分
            if annual <= 0:
                ret_score = 30
            elif annual <= 10:
                ret_score = 30 + annual * 3
            elif annual <= 20:
                ret_score = 60 + (annual - 10) * 2.5
            else:
                ret_score = min(100, 85 + (annual - 20) * 1)
        else:
            ret_score = 50

        # 风险得分（30%权重）
        max_dd = risk.get("最大回撤", 0)
        if isinstance(max_dd, (int, float)):
            # 0回撤=100分，-15%回撤=70分，-30%回撤=40分，-50%回撤=10分
            if max_dd >= 0:
                risk_score = 100
            elif max_dd >= -15:
                risk_score = 100 + max_dd * 2
            elif max_dd >= -30:
                risk_score = 70 + (max_dd + 15) * 2
            else:
                risk_score = max(0, 40 + (max_dd + 30) * 1.5)
        else:
            risk_score = 50

        # 性价比得分（30%权重）- 基于夏普比率
        sharpe = risk_adj.get("夏普比率", 0)
        if isinstance(sharpe, (int, float)):
            # 夏普<0=30分，0.5=50分，1.0=70分，1.5=85分，2.0+=100分
            if sharpe < 0:
                value_score = 30
            elif sharpe <= 0.5:
                value_score = 30 + sharpe * 40
            elif sharpe <= 1.0:
                value_score = 50 + (sharpe - 0.5) * 40
            elif sharpe <= 1.5:
                value_score = 70 + (sharpe - 1.0) * 30
            else:
                value_score = min(100, 85 + (sharpe - 1.5) * 10)
        else:
            value_score = 50

        total = ret_score * 0.4 + risk_score * 0.3 + value_score * 0.3

        # 等级
        if total >= 85:
            grade = "A+"
        elif total >= 75:
            grade = "A"
        elif total >= 60:
            grade = "B"
        elif total >= 45:
            grade = "C"
        else:
            grade = "D"

        # 建议
        suggestion = self._score_suggestion(grade, total, returns, risk)

        return {
            "总分": round(total, 1),
            "收益得分": round(ret_score, 1),
            "风险得分": round(risk_score, 1),
            "性价比得分": round(value_score, 1),
            "等级": grade,
            "建议": suggestion,
        }

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _calc_max_drawdown(self, navs):
        """计算最大回撤及持续期数"""
        _, max_dd, _, _, period = self._calc_max_drawdown_detail(navs)
        return max_dd, period

    def _calc_max_drawdown_detail(self, navs):
        """详细计算最大回撤：返回 (max_dd, max_dd_ratio, peak_idx, trough_idx, recovery_idx)"""
        max_dd = 0
        peak = navs[0]
        peak_idx = 0
        trough_idx = 0
        current_peak_idx = 0
        recovery_idx = None

        for i, nav in enumerate(navs):
            if nav > peak:
                peak = nav
                current_peak_idx = i
                # 检查是否是新的高点（修复）
                if max_dd > 0 and recovery_idx is None:
                    pass  # 还在新高，回撤尚未发生
            dd = (peak - nav) / peak if peak else 0
            if dd > max_dd:
                max_dd = dd
                peak_idx = current_peak_idx
                trough_idx = i

        # 检查是否已修复
        for i in range(trough_idx, len(navs)):
            if navs[i] >= navs[peak_idx]:
                recovery_idx = i
                break

        return max_dd, max_dd / max(1, peak_idx) if peak_idx else 0, peak_idx, trough_idx, recovery_idx

    def _find_drawdowns(self, navs, threshold=0.05):
        """找出所有超过阈值的回撤"""
        drawdowns = []
        peak = navs[0]
        in_dd = False
        dd_start = 0
        dd_trough = 0

        for i, nav in enumerate(navs):
            if nav > peak:
                if in_dd:
                    # 回撤结束
                    depth = (peak - navs[dd_trough]) / peak if peak else 0
                    if depth >= threshold:
                        drawdowns.append({
                            "start": dd_start,
                            "trough": dd_trough,
                            "end": i,
                            "depth": depth,
                        })
                    in_dd = False
                peak = nav
                dd_start = i
            else:
                if not in_dd:
                    in_dd = True
                    dd_trough = i
                elif nav < navs[dd_trough]:
                    dd_trough = i

        return drawdowns

    def _generate_summary(self, result):
        """生成分析摘要文本"""
        returns = result.get("returns", {})
        risk = result.get("risk", {})
        risk_adj = result.get("risk_adjusted", {})

        annual = returns.get("年化收益率", "N/A")
        max_dd = risk.get("最大回撤", "N/A")
        sharpe = risk_adj.get("夏普比率", "N/A")
        y1 = returns.get("近1年", "N/A")

        return (
            f"年化收益{annual}%，近1年{y1}%，"
            f"最大回撤{max_dd}%，夏普比率{sharpe}"
        )

    def _manager_eval_text(self, manager, rating, score, years, scale):
        """生成基金经理文字评价"""
        if rating == "优秀":
            return f"{manager}管理能力优秀（综合评分{score}分），从业{years}年经验丰富，管理规模{scale}亿，历史业绩稳健，风控能力出色。"
        elif rating == "良好":
            return f"{manager}管理能力良好（综合评分{score}分），从业{years}年，管理规模{scale}亿，业绩表现中上水平。"
        elif rating == "一般":
            return f"{manager}管理能力一般（综合评分{score}分），从业{years}年，管理规模{scale}亿，业绩表现中规中矩。"
        else:
            return f"{manager}管理能力有待提升（综合评分{score}分），建议关注后续业绩变化。"

    def _estimate_industry(self, holdings_df):
        """根据持仓估算行业分布（简化版）"""
        # 简化的股票-行业映射
        industry_map = {
            "600519": "食品饮料", "000858": "食品饮料", "000568": "食品饮料",
            "601318": "金融", "600036": "金融", "000001": "金融",
            "000333": "家电", "000651": "家电",
            "002594": "新能源", "300750": "新能源", "601012": "新能源",
            "601899": "有色金属", "600030": "金融",
            "002415": "电子", "600900": "公用事业",
            "519674": "科技", "003096": "医药",
        }

        stocks = []
        if hasattr(holdings_df, "columns") and "股票代码" in holdings_df.columns:
            stocks = holdings_df["股票代码"].tolist()
        elif hasattr(holdings_df, "columns") and "股票名称" in holdings_df.columns:
            stocks = holdings_df["股票名称"].tolist()

        # 统计行业
        industry_count = {}
        for s in stocks:
            code = str(s).strip()
            industry = industry_map.get(code, "其他")
            industry_count[industry] = industry_count.get(industry, 0) + 1

        total = sum(industry_count.values()) or 1
        return {k: round(v / total * 100, 1) for k, v in industry_count.items()}

    def _estimate_style(self, industry_dist):
        """根据行业分布估算投资风格"""
        if not industry_dist:
            return "均衡"

        growth_industries = ["新能源", "科技", "电子", "医药"]
        value_industries = ["金融", "公用事业", "能源", "房地产"]

        growth_ratio = sum(v for k, v in industry_dist.items() if k in growth_industries)
        value_ratio = sum(v for k, v in industry_dist.items() if k in value_industries)

        if growth_ratio > value_ratio * 1.5:
            return "成长"
        elif value_ratio > growth_ratio * 1.5:
            return "价值"
        else:
            return "均衡"

    def _score_suggestion(self, grade, total, returns, risk):
        """根据评分给出投资建议"""
        if grade in ("A+", "A"):
            return "业绩优秀，风险可控，性价比高，建议重点关注，可作为核心配置。"
        elif grade == "B":
            return "业绩良好，风险适中，可作为卫星配置，建议定投参与。"
        elif grade == "C":
            return "业绩一般，需关注风险变化，建议观望或小仓位试探。"
        else:
            return "业绩较差，风险较高，建议规避，等待基本面改善。"

    # ------------------------------------------------------------------
    # 数据提取工具
    # ------------------------------------------------------------------

    def _extract_nav_series(self, df):
        """从DataFrame提取净值序列"""
        if hasattr(df, "columns") and "单位净值" in df.columns:
            return df["单位净值"].tolist()
        if hasattr(df, "columns") and "close" in df.columns:
            return df["close"].tolist()
        if isinstance(df, list):
            return [row.get("单位净值", row.get("close", 0)) for row in df if isinstance(row, dict)]
        return []

    def _extract_date_series(self, df):
        """从DataFrame提取日期序列"""
        if hasattr(df, "columns") and "净值日期" in df.columns:
            return df["净值日期"].tolist()
        if hasattr(df, "columns") and "date" in df.columns:
            return df["date"].tolist()
        if isinstance(df, list):
            return [row.get("净值日期", row.get("date", "")) for row in df if isinstance(row, dict)]
        return []

    def _extract_ratio_series(self, df):
        """从DataFrame提取持仓比例序列"""
        if hasattr(df, "columns") and "占净值比例" in df.columns:
            vals = df["占净值比例"].tolist()
            return [float(v) for v in vals if v is not None]
        if isinstance(df, list):
            return [float(row.get("占净值比例", 0)) for row in df if isinstance(row, dict)]
        return []

    def _is_empty(self, df):
        """检查数据是否为空"""
        if df is None:
            return True
        if hasattr(df, "empty"):
            return df.empty
        if isinstance(df, (list, dict)):
            return len(df) == 0
        return False
