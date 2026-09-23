# -*- coding: utf-8 -*-
"""
金水谣系统 - 每日基金监控脚本 (Daily Fund Monitor)

功能：
    1. 自动获取8只持仓基金的最新净值和历史数据
    2. 计算风险指标（最大回撤、年化波动率、夏普比率、Calmar比率）
    3. 检测止盈信号（目标收益率16.4%）
    4. 检测限购/开放状态变化
    5. 获取关联市场指数行情（美股、港股、黄金）
    6. 生成暗色科技风HTML日报
    7. 保存JSON数据供历史对比

使用方式：
    python scripts/daily_fund_monitor.py              # 生成今日报告
    python scripts/daily_fund_monitor.py --historical  # 同时输出90天历史数据CSV

依赖：
    akshare, pandas, numpy

作者：金水谣系统自动生成
日期：2026-07-16
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, Optional

# 确保项目根目录在路径中
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import numpy as np
import pandas as pd

from utils.safe_json import safe_write_json

# 基金外围风险（基金经理变更 / 规模变化·清盘预警）——JS-20260920-04 新增
# 依赖 requests（可选）：缺失时自动降级，报告该板块显示"暂缺"而非编造数据
try:
    from domains.fund.fund_profile_risk import build_profiles
    PROFILE_AVAILABLE = True
    PROFILE_IMPORT_ERR = ""
except Exception as _e:  # pragma: no cover
    build_profiles = None
    PROFILE_AVAILABLE = False
    PROFILE_IMPORT_ERR = str(_e)

# 区间收益（近3月/6月/1年/3年）复用领域层分析引擎——JS-20260923-11 批2
try:
    from domains.fund.analyzer import FundAnalyzer
    ANALYZER_AVAILABLE = True
    ANALYZER_IMPORT_ERR = ""
except Exception as _e:  # pragma: no cover
    FundAnalyzer = None
    ANALYZER_AVAILABLE = False
    ANALYZER_IMPORT_ERR = str(_e)

# 同类排名复用领域层 FundFetcher.get_rank（real_only=True，不编造模拟排名）——JS-20260923-11 批2
try:
    from domains.fund.fetcher import FundFetcher
    RANK_FETCHER_AVAILABLE = True
    RANK_FETCHER_IMPORT_ERR = ""
except Exception as _e:  # pragma: no cover
    FundFetcher = None
    RANK_FETCHER_AVAILABLE = False
    RANK_FETCHER_IMPORT_ERR = str(_e)

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('fund_monitor')


# ================================================================
# 基金配置 - 8只监控基金
# ================================================================

# JS-20260923-02 批 1：止盈/预警口径升格为常量（七期 TRAE 报告一致的用户设定值）
TARGET_PROFIT_DEFAULT = 0.164   # 统一止盈线 16.4%
WARN_LINE_DEFAULT = 0.12        # 预警线 12%（两档制：先预警后止盈，保住 000216 现有提醒）

# JS-20260924-02：Calmar = 年化收益/最大回撤。回撤极小时该比值发散（实测债基回撤 0.01%
# → Calmar 145.62），数学上成立但无投资含义。回撤低于该阈值(%)时返回 None，渲染显示「—」。
CALMAR_MIN_DRAWDOWN_PCT = 0.5

# dca_amount/dca_freq：定投计划（七期 TRAE 报告完全一致，视为用户确认口径）。
# 限购比较用「单次买入金额」= dca_amount，不再用 investment/30 折算（修 017641 误报）。
FUND_CONFIG = [
    {
        "code": "005698",
        "name": "华夏全球科技先锋混合(QDII)A",
        "category": "QDII-科技",
        "investment": 3000,
        "target_profit": TARGET_PROFIT_DEFAULT,
        "warn_line": WARN_LINE_DEFAULT,
        "dca_amount": 10,
        "dca_freq": "daily",
        "manager": "李湘杰",  # 批 1 修正：李博→李湘杰（2018-04-17 起任职）
        "company": "华夏基金",
        "risk_level": "高",
        "related_index": "全球科技(主动)",  # 批 1 修正：主动选股（光通信/AI 算力），非纳指宽基
    },
    {
        "code": "017641",
        "name": "摩根标普500指数(QDII)人民币A",
        "category": "QDII-宽基",
        "investment": 3000,
        "target_profit": TARGET_PROFIT_DEFAULT,
        "warn_line": WARN_LINE_DEFAULT,
        "dca_amount": 10,
        "dca_freq": "daily",
        "manager": "张军",
        "company": "摩根资管",
        "risk_level": "中高",
        "related_index": "标普500",
    },
    {
        "code": "270042",
        "name": "广发纳斯达克100ETF联接人民币(QDII)A",
        "category": "QDII-科技",
        "investment": 3000,
        "target_profit": TARGET_PROFIT_DEFAULT,
        "warn_line": WARN_LINE_DEFAULT,
        "dca_amount": 10,
        "dca_freq": "daily",
        "manager": "刘杰",
        "company": "广发基金",
        "risk_level": "高",
        "related_index": "纳斯达克100",
    },
    {
        "code": "011369",
        "name": "华商均衡成长混合A",
        "category": "混合型",
        "investment": 3000,
        "target_profit": TARGET_PROFIT_DEFAULT,
        "warn_line": WARN_LINE_DEFAULT,
        "dca_amount": 70,
        "dca_freq": "weekly",
        "manager": "张明昕",  # 批 1 修正：周海栋→张明昕（周海栋 2025-03 清仓式离职）
        "company": "华商基金",
        "risk_level": "中高",
        "related_index": "沪深300",
    },
    {
        "code": "015942",
        "name": "上银慧享利30天滚动持有中短债发起A",
        "category": "债券型",
        "investment": 10000,
        "target_profit": None,  # 批 1：不止盈（中短债波动小，用户设定）；预警档仍保留
        "warn_line": WARN_LINE_DEFAULT,
        "dca_amount": 70,
        "dca_freq": "weekly",
        "manager": "蔡唯峰、周岳洋",  # 批 1 修正：陈芳菲→蔡唯峰+周岳洋（2026-08-14 增聘）
        "company": "上银基金",
        "risk_level": "低",
        "related_index": "中债总指数",
    },
    {
        "code": "009051",
        "name": "易方达中证红利ETF联接发起式A",
        "category": "指数型-红利",
        "investment": 10000,
        "target_profit": TARGET_PROFIT_DEFAULT,  # 批 1：0.10→16.4% 统一口径
        "warn_line": WARN_LINE_DEFAULT,
        "dca_amount": 70,
        "dca_freq": "weekly",
        "manager": "林伟斌",
        "company": "易方达基金",
        "risk_level": "中",
        "related_index": "中证红利",
    },
    {
        "code": "000216",
        "name": "华安黄金ETF联接A",
        "category": "商品-黄金",
        "investment": 5000,
        "target_profit": TARGET_PROFIT_DEFAULT,  # 批 1：0.12→16.4% 统一口径，12% 转为预警档
        "warn_line": WARN_LINE_DEFAULT,
        "dca_amount": 10,
        "dca_freq": "weekly",
        "manager": "许之彦",
        "company": "华安基金",
        "risk_level": "中",
        "related_index": "COMEX黄金",
    },
    {
        "code": "013308",
        "name": "易方达恒生科技ETF联接(QDII)A",
        "category": "QDII-港股科技",
        "investment": 3000,
        "target_profit": TARGET_PROFIT_DEFAULT,
        "warn_line": WARN_LINE_DEFAULT,
        "dca_amount": 20,
        "dca_freq": "weekly",
        "manager": "刘依姗、成曦",  # 批 1 修正：范冰→刘依姗+成曦（2026-03-23 增聘）
        "company": "易方达基金",
        "risk_level": "高",
        "related_index": "恒生科技指数",
    },
]

# 基金代码到配置的映射
FUND_MAP = {f["code"]: f for f in FUND_CONFIG}


# ================================================================
# 数据获取层
# ================================================================

class FundDataFetcher:
    """基金数据获取器 - 封装akshare接口"""

    def __init__(self):
        self.daily_df = None  # 缓存当日全部基金数据
        self._load_daily_data()

    def _load_daily_data(self):
        """加载当日全部开放式基金数据（用于快速查询），失败自动重试 3 次"""
        import time as _time
        last_err = "未知原因"
        for attempt in range(1, 4):
            try:
                import akshare as ak
                self.daily_df = ak.fund_open_fund_daily_em()
                if self.daily_df is not None and len(self.daily_df) > 0:
                    logger.info("已加载当日基金数据，共 %d 行", len(self.daily_df))
                    return
                last_err = "接口返回空数据"
            except Exception as e:
                last_err = str(e)
            logger.warning("加载当日基金数据第 %d/3 次失败: %s", attempt, last_err)
            if attempt < 3:
                _time.sleep(10 * attempt)
        logger.error("加载当日基金数据 3 次均失败，本次快照将缺少净值: %s", last_err)
        self.daily_df = None

    def get_fund_snapshot(self, code: str) -> Optional[Dict]:
        """获取基金当日快照（净值、涨跌幅、申购状态等）

        净值列名格式如 '2026-07-25-单位净值'，日期随数据源变动
        （周末/节假日/QDII T+2 会滞后），因此扫描全部净值列按日期
        倒序取最新非空值，而非硬编码今天/昨天两列。
        """
        if self.daily_df is None:
            return None
        match = self.daily_df[self.daily_df["基金代码"] == code]
        if match.empty:
            return None

        row = match.iloc[0]

        # 扫描所有 'YYYY-MM-DD-单位净值' 列，按日期倒序收集非空净值
        nav_cols = sorted(
            (c for c in self.daily_df.columns if str(c).endswith("-单位净值")),
            reverse=True,
        )
        navs = []  # [(日期字符串, 净值float)]
        for col in nav_cols:
            val = row.get(col)
            if val is None or str(val).strip() in ("", "nan", "None", "---"):
                continue
            try:
                navs.append((str(col)[: -len("-单位净值")], float(val)))
            except (TypeError, ValueError):
                continue

        nav_today = navs[0][1] if navs else None
        nav_date = navs[0][0] if navs else None
        nav_yesterday = navs[1][1] if len(navs) > 1 else None

        # 日增长率：优先取源字段，缺失时用相邻两日净值补算
        daily_return = None
        raw_ret = row.get("日增长率")
        if raw_ret is not None and str(raw_ret).strip() not in ("", "nan", "None", "---"):
            try:
                daily_return = float(raw_ret)
            except (TypeError, ValueError):
                daily_return = None
        if daily_return is None and nav_today is not None and nav_yesterday:
            daily_return = round((nav_today - nav_yesterday) / nav_yesterday * 100, 2)

        return {
            "code": code,
            "name": row.get("基金简称", ""),
            "nav_today": nav_today,
            "nav_yesterday": nav_yesterday,
            "daily_return": daily_return,
            "buy_status": row.get("申购状态", "未知"),
            "sell_status": row.get("赎回状态", "未知"),
            "fee": row.get("手续费", ""),
            "update_date": nav_date or "",
        }

    def get_fund_history(self, code: str, days: int = 90) -> Optional[pd.DataFrame]:
        """获取基金历史净值走势（默认90天）"""
        try:
            import akshare as ak
            df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
            if df is None or df.empty:
                return None
            df["净值日期"] = pd.to_datetime(df["净值日期"])
            df = df.sort_values("净值日期")
            # 取最近N天
            cutoff = datetime.now() - timedelta(days=days + 10)
            df = df[df["净值日期"] >= cutoff]
            return df
        except Exception as e:
            logger.error("获取基金 %s 历史数据失败: %s", code, e)
            return None

    @staticmethod
    def _idx_from_df(df: Optional[pd.DataFrame], close_col: str = "close") -> Optional[Dict]:
        """从日线DataFrame提取最新收盘价与涨跌幅"""
        if df is None or df.empty:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        try:
            close = float(latest[close_col])
            prev_close = float(prev[close_col])
        except (KeyError, TypeError, ValueError):
            return None
        change = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        return {"value": round(close, 2), "change_pct": change}

    def get_market_indices(self) -> Dict[str, Dict]:
        """获取关联市场指数行情

        每个指数配置多个数据源（东财主源 + 新浪备源），按顺序尝试、
        成功即止；全部失败仅告警，不阻塞主流程、不编造数据。
        注：akshare 1.18.x 已移除 index_hk_hist_sina，恒指改用
        stock_hk_index_daily_em/sina；黄金改用 futures_main_sina('AU0')。
        """
        import akshare as ak

        sources = {
            "上证指数": [
                lambda: self._idx_from_df(ak.stock_zh_index_daily_em(symbol="sh000001")),
                lambda: self._idx_from_df(ak.stock_zh_index_daily(symbol="sh000001")),
            ],
            "沪深300": [
                lambda: self._idx_from_df(ak.stock_zh_index_daily_em(symbol="sh000300")),
                lambda: self._idx_from_df(ak.stock_zh_index_daily(symbol="sh000300")),
            ],
            "恒生指数": [
                lambda: self._idx_from_df(ak.stock_hk_index_daily_em(symbol="HSI")),
                lambda: self._idx_from_df(ak.stock_hk_index_daily_sina(symbol="HSI")),
            ],
            "沪金主力": [
                lambda: self._idx_from_df(
                    ak.futures_main_sina(symbol="AU0"), close_col="收盘价"
                ),
            ],
        }

        indices: Dict[str, Dict] = {}
        for name, fetchers in sources.items():
            for fetch in fetchers:
                try:
                    result = fetch()
                except Exception as e:
                    logger.warning("获取%s失败(尝试备用源): %s", name, str(e)[:100])
                    continue
                if result:
                    indices[name] = result
                    break
            if name not in indices:
                logger.warning("获取%s失败: 所有数据源均不可用", name)
        return indices


# ================================================================
# 风险指标计算
# ================================================================

class RiskCalculator:
    """风险指标计算器"""

    @staticmethod
    def calc_max_drawdown(nav_series: pd.Series) -> float:
        """计算最大回撤（%）"""
        if nav_series.empty or len(nav_series) < 2:
            return 0.0
        rolling_max = nav_series.cummax()
        drawdown = (nav_series - rolling_max) / rolling_max
        return round(abs(drawdown.min()) * 100, 2)

    @staticmethod
    def calc_volatility(nav_series: pd.Series, annualize: bool = True) -> float:
        """计算波动率（%），默认年化"""
        if nav_series.empty or len(nav_series) < 2:
            return 0.0
        returns = nav_series.pct_change().dropna()
        if returns.empty:
            return 0.0
        vol = returns.std()
        if annualize:
            vol *= np.sqrt(252)  # 年化
        return round(vol * 100, 2)

    @staticmethod
    def calc_sharpe(nav_series: pd.Series, risk_free_rate: float = 0.015) -> float:
        """计算夏普比率（假设无风险利率1.5%）"""
        if nav_series.empty or len(nav_series) < 5:
            return 0.0
        returns = nav_series.pct_change().dropna()
        if returns.empty or returns.std() == 0:
            return 0.0
        excess_return = returns.mean() * 252 - risk_free_rate
        return round(excess_return / (returns.std() * np.sqrt(252)), 2)

    @staticmethod
    def calc_calmar(nav_series: pd.Series) -> Optional[float]:
        """计算Calmar比率（年化收益/最大回撤）

        JS-20260924-02：回撤极小时该比值发散（实测债基回撤 0.01% → Calmar 145.62），
        数学上成立但无投资含义；样本不足时同理。两种情形均返回 None，渲染显示「—」，
        宁可留白也不给伪精确值。
        """
        if nav_series is None or nav_series.empty or len(nav_series) < 5:
            return None
        returns = nav_series.pct_change().dropna()
        if returns.empty:
            return None
        annual_return = returns.mean() * 252
        max_dd_pct = RiskCalculator.calc_max_drawdown(nav_series)
        if max_dd_pct is None or abs(max_dd_pct) < CALMAR_MIN_DRAWDOWN_PCT:
            return None
        max_dd = abs(max_dd_pct) / 100
        if max_dd == 0:
            return None
        return round(annual_return / max_dd, 2)

    @staticmethod
    def calc_total_return(nav_series: pd.Series) -> Optional[float]:
        """计算区间总收益率（%）

        JS-20260924-02：样本不足时原返回 0.0，被渲染成「0.00%」——看起来像
        「没涨没跌」而非「数据不足」。改为返回 None，渲染显示「—」。
        """
        if nav_series is None or nav_series.empty or len(nav_series) < 2:
            return None
        total = (nav_series.iloc[-1] - nav_series.iloc[0]) / nav_series.iloc[0]
        return round(total * 100, 2)


# ================================================================
# 信号检测
# ================================================================

class SignalDetector:
    """投资信号检测器"""

    @staticmethod
    def check_take_profit(current_nav: float, investment: float, target_profit,
                          nav_series: pd.Series, warn_line: float = None) -> Dict:
        """检测止盈信号（两档制：预警线 → 止盈线）

        ⚠️ 口径说明（JS-20260923-02 批 1 修正）：current_return 是「以历史区间
        首日净值为买入点」的区间收益，不是定投持仓的实际收益——定投成本是历次
        买入的加权平均。文案已如实标注，实际止盈请以平台持仓成本核算。
        target_profit=None 表示该基金设定不止盈（如中短债），此时只做预警判断。

        Args:
            current_nav: 当前净值（快照缺失时调用方已用历史最新值兜底）
            investment: 已投入本金（保留参数，当前口径未使用）
            target_profit: 止盈线（小数，如 0.164）；None=不止盈
            nav_series: 历史净值序列
            warn_line: 预警线（小数，如 0.12）；None=不做预警判断
        """
        if nav_series is None or nav_series.empty or len(nav_series) < 2:
            return {"signal": False, "current_return": None, "message": "历史数据不足"}

        buy_nav = nav_series.iloc[0]  # 简化：以区间第一天为买入点
        current_return = (current_nav - buy_nav) / buy_nav

        signal = target_profit is not None and current_return >= target_profit
        warn = (not signal and warn_line is not None
                and current_return >= warn_line)
        base = "90天区间收益 {:.2f}%（非持仓实际收益）".format(round(current_return * 100, 2))
        if signal:
            message = base + "，已达止盈目标 {:.1f}% ⚠️".format(target_profit * 100)
        elif warn and target_profit is not None:
            message = base + "，已过预警线 {:.0f}%（止盈线 {:.1f}%）⚠️".format(
                warn_line * 100, target_profit * 100)
        elif warn:
            message = base + "，已过预警线 {:.0f}%（该基金设定不止盈）⚠️".format(
                warn_line * 100)
        elif target_profit is None:
            message = base + "，该基金设定不止盈"
        else:
            message = base + "，止盈线 {:.1f}%".format(target_profit * 100)
        return {
            "signal": signal,
            "warn": warn,
            "current_return": round(current_return * 100, 2),
            "target_return": (round(target_profit * 100, 1)
                              if target_profit is not None else None),
            "message": message,
        }

    @staticmethod
    def check_purchase_limit(buy_status: str) -> Dict:
        """检测限购状态"""
        limit_keywords = ["限大额", "暂停", "封闭", "限购"]
        is_limited = any(kw in buy_status for kw in limit_keywords)
        return {
            "is_limited": is_limited,
            "status": buy_status,
            "message": "⚠️ 限购中" if is_limited else "正常开放",
        }

    @staticmethod
    def check_significant_drop(nav_series: pd.Series, threshold: float = -5.0) -> Dict:
        """检测近期显著下跌（5日内跌幅超过阈值%）"""
        if nav_series is None or len(nav_series) < 5:
            return {"signal": False, "message": "数据不足"}
        recent = nav_series.tail(5)
        drop = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0] * 100
        signal = drop <= threshold
        return {
            "signal": signal,
            "drop_pct": round(drop, 2),
            "message": f"近5日下跌 {round(drop,2)}%" + (" ⚠️ 显著下跌！" if signal else ""),
        }


# ================================================================
# 报告生成器
# ================================================================

# ================================================================
# 组合概览聚合（JS-20260924-03 批3·切片A）：跨基金对比，复用 monitor_data 已有字段，
# 不取任何新数据。区间收益/风险来自批2与旧管线，定投计划来自 FUND_CONFIG。
# ================================================================

def _aggregate_portfolio(data: Dict) -> Dict:
    """跨基金聚合，供「组合概览」板块渲染。纯计算，遇缺失字段安全跳过。"""
    rows = []
    for code, d in data.items():
        cfg = d.get("config", {}) or {}
        ir = d.get("interval_returns", {}) or {}
        risks = d.get("risks", {}) or {}
        rows.append({
            "code": code,
            "name": cfg.get("name", code),
            "inv_3m": ir.get("近3月"),
            "inv_1y": ir.get("近1年"),
            "ret_90": risks.get("total_return"),
            "max_dd": risks.get("max_drawdown"),
            "sharpe": risks.get("sharpe"),
        })
    dca_daily = sum(f.get("dca_amount", 0) for f in FUND_CONFIG if f.get("dca_freq") == "daily")
    dca_weekly = sum(f.get("dca_amount", 0) for f in FUND_CONFIG if f.get("dca_freq") == "weekly")

    def _extreme(key, best):
        vals = [r for r in rows if isinstance(r.get(key), (int, float))]
        if not vals:
            return None
        return max(vals, key=lambda x: x[key]) if best else min(vals, key=lambda x: x[key])

    return {
        "best_1y": _extreme("inv_1y", True),
        "worst_1y": _extreme("inv_1y", False),
        "best_3m": _extreme("inv_3m", True),
        "worst_3m": _extreme("inv_3m", False),
        "best_90": _extreme("ret_90", True),
        "worst_90": _extreme("ret_90", False),
        "worst_dd": _extreme("max_dd", False),
        "best_sharpe": _extreme("sharpe", True),
        "dca_daily": dca_daily,
        "dca_weekly": dca_weekly,
    }


def _render_portfolio_overview(ov: Dict) -> str:
    """将聚合结果渲染为组合概览卡片网格。"""
    def _pct(v):
        return f"{v:+.2f}%" if isinstance(v, (int, float)) else "—"

    def _dd(v):
        return f"{v:.2f}%" if isinstance(v, (int, float)) else "—"

    def _sharpe(v):
        return f"{v:.2f}" if isinstance(v, (int, float)) else "—"

    def _cls_pct(v):
        if not isinstance(v, (int, float)):
            return "neutral"
        return "up" if v > 0 else "down" if v < 0 else "neutral"

    def _card(label, rec, key, fmt, cls_fn="neutral"):
        val = rec.get(key) if rec else None
        sub = rec.get("name", "") if rec else ""
        cls = cls_fn(val) if callable(cls_fn) else cls_fn
        return (
            f'<div class="summary-card">'
            f'<div class="number {cls}">{fmt(val)}</div>'
            f'<div class="label">{label}</div>'
            f'<div class="label" style="margin-top:2px;opacity:.8">{sub}</div>'
            f'</div>'
        )

    cards = [
        _card("近1年最佳", ov["best_1y"], "inv_1y", _pct, _cls_pct),
        _card("近1年最弱", ov["worst_1y"], "inv_1y", _pct, _cls_pct),
        _card("近3月最佳", ov["best_3m"], "inv_3m", _pct, _cls_pct),
        _card("90天最佳", ov["best_90"], "ret_90", _pct, _cls_pct),
        _card("90天最弱", ov["worst_90"], "ret_90", _pct, _cls_pct),
        _card("最大回撤(最差)", ov["worst_dd"], "max_dd", _dd, "down"),
        _card("夏普最高", ov["best_sharpe"], "sharpe", _sharpe, "neutral"),
        (f'<div class="summary-card">'
         f'<div class="number" style="font-size:20px">{ov["dca_daily"]} / {ov["dca_weekly"]}</div>'
         f'<div class="label">定投计划(日/周 元)</div>'
         f'</div>'),
    ]
    return f'<div class="summary-bar">{"".join(cards)}</div>'


def _fill_daily_return_from_history(snapshot: Dict, hist_series) -> None:
    """快照日涨跌缺失时，用历史末两个净值补算（JS-20260924-02 修复2）。

    get_fund_snapshot 的日涨跌优先取 daily_df 的「日增长率」列，缺失时仅当
    nav_yesterday 存在才补算；而 daily_df 往往只含最新一列 → nav_yesterday 为 None
    → 日涨跌整列显示 "--"。历史序列（akshare）始终连续，可据此算出
    「最新可得一日涨跌」，语义与报告头部标注的净值日期一致。
    """
    if snapshot is None or hist_series is None:
        return
    if snapshot.get("daily_return") is not None:
        return
    if len(hist_series) < 2:
        return
    try:
        prev = float(hist_series.iloc[-2])
        last = float(hist_series.iloc[-1])
        if prev == 0:
            return
        snapshot["daily_return"] = round((last - prev) / prev * 100, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return


class ReportGenerator:
    """HTML日报生成器 - 暗色科技风"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate(self, monitor_data: Dict, market_indices: Dict,
                 profiles: Optional[Dict] = None) -> str:
        """生成HTML报告，返回文件路径"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M")
        filename = f"fund_report_{date_str}.html"
        filepath = os.path.join(self.output_dir, filename)

        html = self._build_html(date_str, time_str, monitor_data, market_indices, profiles)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info("报告已生成: %s", filepath)
        return filepath

    @staticmethod
    def _nav_date_note(data: Dict) -> str:
        """汇总各基金净值所属日期，避免"标题写今天、净值是上周"却无人察觉。

        JS-20260923-01：净值不是收盘即出（交易日19:00-23:00陆续公布，美股QDII再晚一天），
        报告必须显式标注净值日期，否则用户看到的数字是第几天的完全不可知。
        """
        dates = sorted({d.get("snapshot", {}).get("update_date", "")
                        for d in data.values()
                        if d.get("snapshot", {}).get("update_date")})
        if not dates:
            return ""
        if len(dates) == 1:
            return f" | 净值日期: {dates[0]}"
        return f" | 净值日期: {dates[0]} ~ {dates[-1]}（QDII滞后）"

    def _build_html(self, date_str: str, time_str: str, data: Dict, indices: Dict,
                    profiles: Optional[Dict] = None) -> str:
        """构建HTML内容"""
        
        # 统计
        total_invest = sum(f["investment"] for f in FUND_CONFIG)
        take_profit_count = sum(1 for d in data.values() if d.get("signals", {}).get("take_profit", {}).get("signal", False))
        limit_count = sum(1 for d in data.values() if d.get("signals", {}).get("purchase_limit", {}).get("is_limited", False))
        profiles = profiles or {}
        manager_warn_count = sum(1 for p in profiles.values()
                                 if p.get("manager", {}).get("level") in ("warn", "notice"))
        scale_warn_count = sum(1 for p in profiles.values() if p.get("scale", {}).get("level") in ("warn", "danger"))
        # JS-20260920-08：限购额度（含「低于计划日投」受限 + 本次采集到的收紧变化）
        limit_warn_count = sum(1 for p in profiles.values() if p.get("limit", {}).get("level") == "warn")
        limit_tighten_count = sum(1 for p in profiles.values() if p.get("limit_change") == "tighter")
        
        # JS-20260924-03 批3·切片A：组合概览（跨基金聚合，复用已有数据，不取新源）
        overview_html = _render_portfolio_overview(_aggregate_portfolio(data))

        # 基金卡片HTML
        fund_cards = []
        for fund in FUND_CONFIG:
            code = fund["code"]
            d = data.get(code, {})
            snapshot = d.get("snapshot", {})
            risks = d.get("risks", {})
            signals = d.get("signals", {})
            
            nav = snapshot.get("nav_today", "--")
            daily_ret = snapshot.get("daily_return")
            daily_ret_str = f"{daily_ret:+.2f}%" if daily_ret is not None else "--"
            daily_ret_class = "up" if daily_ret and daily_ret > 0 else "down" if daily_ret and daily_ret < 0 else "neutral"
            # JS-20260923-01：净值必须显示所属日期。此前 update_date 已算出但从未渲染，
            # 导致报告标题写 09-21、净值却是 09-18 的数，用户无法察觉滞后。
            _nd = snapshot.get("update_date", "") or ""
            nav_label = f"最新净值({_nd[5:]})" if len(_nd) >= 10 else "最新净值"
            
            tp = signals.get("take_profit", {})
            pl = signals.get("purchase_limit", {})
            sd = signals.get("significant_drop", {})

            # JS-20260923-11 批2：区间收益 + 同类排名展示准备
            _ir_map = d.get("interval_returns", {}) or {}

            def _fmt_ir(v):
                if v is None or isinstance(v, str):
                    return "--"
                return f"{v:+.2f}"

            def _cls_ir(v):
                if v is None or isinstance(v, str):
                    return "neutral"
                return "up" if v > 0 else "down" if v < 0 else "neutral"

            def _disp(v, suffix=""):
                """风险/收益指标渲染：None（样本不足或回撤≈0）显式显示「—」，不露伪精确值。"""
                return "—" if v is None else f"{v}{suffix}"

            ir_3m, ir_3m_cls = _fmt_ir(_ir_map.get("近3月")), _cls_ir(_ir_map.get("近3月"))
            ir_6m, ir_6m_cls = _fmt_ir(_ir_map.get("近6月")), _cls_ir(_ir_map.get("近6月"))
            ir_1y, ir_1y_cls = _fmt_ir(_ir_map.get("近1年")), _cls_ir(_ir_map.get("近1年"))
            ir_3y, ir_3y_cls = _fmt_ir(_ir_map.get("近3年")), _cls_ir(_ir_map.get("近3年"))

            _rk = d.get("rank") or {}
            _rank_raw = _rk.get("rank")
            if _rank_raw:
                try:
                    _a, _b = str(_rank_raw).split("/")
                    _ai, _bi = int(_a), int(_b)
                    _pct = round(_ai / _bi * 100, 1) if _bi else 0
                    rank_disp = f"{_rank_raw}（前{_pct}%）"
                    rank_cls = "up" if _pct <= 33 else "neutral" if _pct <= 66 else "down"
                except Exception:
                    rank_disp = str(_rank_raw)
                    rank_cls = "neutral"
            else:
                rank_disp = "暂缺"
                rank_cls = "neutral"

            card = f"""
            <div class="fund-card">
                <div class="fund-header">
                    <div class="fund-title">
                        <span class="fund-name">{fund["name"]}</span>
                        <span class="fund-code">{code}</span>
                    </div>
                    <div class="fund-category">{fund["category"]}</div>
                </div>
                <div class="fund-body">
                    <div class="metric-row">
                        <div class="metric">
                            <div class="metric-label">{nav_label}</div>
                            <div class="metric-value">{nav if nav else "--"}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">日涨跌</div>
                            <div class="metric-value {daily_ret_class}">{daily_ret_str}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">最大回撤</div>
                            <div class="metric-value">{_disp(risks.get("max_drawdown"), "%")}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">年化波动</div>
                            <div class="metric-value">{_disp(risks.get("volatility"), "%")}</div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric">
                            <div class="metric-label">夏普比率</div>
                            <div class="metric-value">{_disp(risks.get("sharpe"))}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Calmar</div>
                            <div class="metric-value">{_disp(risks.get("calmar"))}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">90天收益</div>
                            <div class="metric-value">{_disp(risks.get("total_return"), "%")}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">申购状态</div>
                            <div class="metric-value {'limit' if pl.get('is_limited') else 'ok'}">{pl.get("status", "--")}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">同类排名</div>
                            <div class="metric-value {rank_cls}">{rank_disp}</div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric">
                            <div class="metric-label">近3月</div>
                            <div class="metric-value {ir_3m_cls}">{ir_3m}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">近6月</div>
                            <div class="metric-value {ir_6m_cls}">{ir_6m}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">近1年</div>
                            <div class="metric-value {ir_1y_cls}">{ir_1y}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">近3年</div>
                            <div class="metric-value {ir_3y_cls}">{ir_3y}%</div>
                        </div>
                    </div>
                    <div class="signals">
                        {f'<div class="signal alert">止盈信号: {tp.get("message", "")}</div>' if tp.get("signal") else (f'<div class="signal warning">止盈预警: {tp.get("message", "")}</div>' if tp.get("warn") else f'<div class="signal info">{tp.get("message", "")}</div>')}
                        {f'<div class="signal warning">{sd.get("message", "")}</div>' if sd.get("signal") else ''}
                        <div class="signal note" style="font-size:12px;opacity:.75">定投实际收益按历次买入加权成本核算，与上方区间收益不同，请以平台持仓为准</div>
                    </div>
                </div>
            </div>
            """
            fund_cards.append(card)
        
        # 市场指数HTML
        index_cards = []
        for name, idx in indices.items():
            change_class = "up" if idx.get("change_pct", 0) > 0 else "down" if idx.get("change_pct", 0) < 0 else "neutral"
            index_cards.append(f"""
            <div class="index-item">
                <span class="index-name">{name}</span>
                <span class="index-value">{idx.get('value', '--')}</span>
                <span class="index-change {change_class}">{idx.get('change_pct', 0):+.2f}%</span>
            </div>
            """)
        
        # 外围风险HTML（基金经理变更 / 规模变化·清盘预警 / 限购额度）
        profile_items = []
        limit_items = []
        CHANGE_TAG = {
            "tighter": ' <span style="color:var(--alert);font-size:12px;">[较上次采集收紧]</span>',
            "loosened": ' <span style="color:var(--up);font-size:12px;">[较上次采集放宽]</span>',
            "new": ' <span style="color:var(--text-secondary);font-size:12px;">[首次采集]</span>',
        }
        for fund in FUND_CONFIG:
            code = fund["code"]
            p = profiles.get(code, {}) or {}
            mgr = p.get("manager", {}) or {}
            sc = p.get("scale", {}) or {}
            lim = p.get("limit", {}) or {}
            stale_note = (' <span style="color:var(--text-secondary);font-size:12px;">'
                          '（网络未通，展示缓存数据）</span>') if p.get("stale") else ""
            mgr_level = mgr.get("level", "info") if mgr.get("ok") else "miss"
            mgr_cls = {"info": "ok", "notice": "warn", "warn": "warn"}.get(mgr_level, "miss")
            sc_level = sc.get("level", "miss") if sc.get("ok") else "miss"
            sc_cls = {"safe": "ok", "warn": "warn", "danger": "danger"}.get(sc_level, "miss")
            lim_level = lim.get("level", "info") if lim.get("ok") else "miss"
            lim_cls = {"info": "ok", "warn": "warn"}.get(lim_level, "miss")
            profile_items.append(f"""
            <div class="profile-item">
                <div class="profile-title">
                    <span class="pname">{fund["name"]}</span>
                    <span class="pcode">{code}</span>{stale_note}
                </div>
                <div class="profile-line {mgr_cls}">经理：{mgr.get("message", "暂缺：未取到基金经理数据")}</div>
                <div class="profile-line {sc_cls}">规模：{sc.get("message", "暂缺：未取到规模数据")}</div>
            </div>
            """)
            limit_items.append(f"""
            <div class="profile-item">
                <div class="profile-title">
                    <span class="pname">{fund["name"]}</span>
                    <span class="pcode">{code}</span>{CHANGE_TAG.get(p.get("limit_change", ""), "")}
                </div>
                <div class="profile-line {lim_cls}">限购：{lim.get("message", "暂缺：未取到限购额度数据")}</div>
            </div>
            """)
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>金水谣基金监控日报 - {date_str}</title>
    <style>
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #1e293b;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --brand: #C9A96E;
            --brand-light: #E8ECF1;
            --up: #2D8B7E;
            --down: #C8755A;
            --warning: #f59e0b;
            --alert: #C8755A;
            --info: #5bc0de;
            --border: #334155;
            --radius: 12px;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        
        .header {{
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-size: 28px;
            background: linear-gradient(135deg, var(--brand), var(--brand-light));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        .header .subtitle {{
            color: var(--text-secondary);
            font-size: 14px;
        }}
        
        .summary-bar {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            text-align: center;
        }}
        .summary-card .number {{
            font-size: 32px;
            font-weight: bold;
            color: var(--brand);
        }}
        .summary-card .label {{
            color: var(--text-secondary);
            font-size: 13px;
            margin-top: 4px;
        }}
        
        .section-title {{
            font-size: 18px;
            margin: 30px 0 16px;
            padding-left: 12px;
            border-left: 4px solid var(--brand);
        }}
        
        .fund-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            margin-bottom: 16px;
            transition: border-color 0.2s;
        }}
        .fund-card:hover {{ border-color: var(--brand); }}
        .fund-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .fund-name {{ font-size: 16px; font-weight: 600; }}
        .fund-code {{
            font-size: 12px;
            color: var(--text-secondary);
            margin-left: 8px;
            font-family: monospace;
        }}
        .fund-category {{
            font-size: 12px;
            padding: 4px 12px;
            border-radius: 999px;
            background: rgba(201, 169, 110, 0.15);
            color: var(--brand-light);
        }}
        .metric-row {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 12px;
        }}
        @media (max-width: 768px) {{
            .metric-row {{ grid-template-columns: repeat(2, 1fr); }}
        }}
        .metric {{
            background: rgba(15, 23, 42, 0.5);
            border-radius: 8px;
            padding: 12px;
            text-align: center;
        }}
        .metric-label {{
            font-size: 11px;
            color: var(--text-secondary);
            margin-bottom: 4px;
        }}
        .metric-value {{
            font-size: 16px;
            font-weight: 600;
        }}
        .metric-value.up {{ color: var(--up); }}
        .metric-value.down {{ color: var(--down); }}
        .metric-value.limit {{ color: var(--warning); }}
        .metric-value.ok {{ color: var(--up); }}
        .signals {{ margin-top: 12px; }}
        .signal {{
            font-size: 13px;
            padding: 8px 12px;
            border-radius: 6px;
            margin-top: 6px;
        }}
        .signal.alert {{ background: rgba(200, 117, 90, 0.1); color: var(--alert); }}
        .signal.warning {{ background: rgba(245, 158, 11, 0.1); color: var(--warning); }}
        .signal.info {{ background: rgba(91, 192, 222, 0.1); color: var(--info); }}
        
        .market-section {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            margin-top: 20px;
        }}
        .index-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid var(--border);
        }}
        .index-item:last-child {{ border-bottom: none; }}
        .index-change {{ font-weight: 600; }}
        .index-change.up {{ color: var(--up); }}
        .index-change.down {{ color: var(--down); }}
        
        .profile-section {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
        }}
        .profile-item {{
            padding: 14px 0;
            border-bottom: 1px solid var(--border);
        }}
        .profile-item:last-child {{ border-bottom: none; }}
        .profile-title {{ margin-bottom: 6px; }}
        .profile-title .pname {{ font-size: 14px; font-weight: 600; }}
        .profile-title .pcode {{
            font-size: 12px;
            color: var(--text-secondary);
            margin-left: 8px;
            font-family: monospace;
        }}
        .profile-line {{ font-size: 13px; margin-top: 4px; }}
        .profile-line.danger {{ color: var(--alert); }}
        .profile-line.warn {{ color: var(--warning); }}
        .profile-line.ok {{ color: var(--up); }}
        .profile-line.miss {{ color: var(--text-secondary); }}
        
        .footer {{
            text-align: center;
            color: var(--text-secondary);
            font-size: 12px;
            margin-top: 40px;
            padding: 20px;
            border-top: 1px solid var(--border);
        }}
        .legend {{
            margin-top: 20px;
            padding: 16px;
            background: rgba(201, 169, 110, 0.05);
            border-radius: var(--radius);
            font-size: 12px;
            color: var(--text-secondary);
        }}
        .legend strong {{ color: var(--text-primary); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>金水谣基金监控日报</h1>
            <div class="subtitle">报告日期: {date_str} {time_str} | 共监控 {len(FUND_CONFIG)} 只基金{self._nav_date_note(data)}</div>
        </div>
        
        <div class="summary-bar">
            <div class="summary-card">
                <div class="number">{len(FUND_CONFIG)}</div>
                <div class="label">监控基金数</div>
            </div>
            <div class="summary-card">
                <div class="number">{total_invest:,}</div>
                <div class="label">总投入金额(元)</div>
            </div>
            <div class="summary-card">
                <div class="number" style="color: {'var(--alert)' if take_profit_count > 0 else 'var(--up)'}">{take_profit_count}</div>
                <div class="label">止盈信号</div>
            </div>
            <div class="summary-card">
                <div class="number" style="color: {'var(--warning)' if limit_count > 0 else 'var(--text-secondary)'}">{limit_count}</div>
                <div class="label">限购基金数</div>
            </div>
            <div class="summary-card">
                <div class="number" style="color: {'var(--warning)' if manager_warn_count > 0 else 'var(--text-secondary)'}">{manager_warn_count}</div>
                <div class="label">经理关注(变更/待核对)</div>
            </div>
            <div class="summary-card">
                <div class="number" style="color: {'var(--alert)' if scale_warn_count > 0 else 'var(--text-secondary)'}">{scale_warn_count}</div>
                <div class="label">规模/清盘预警</div>
            </div>
            <div class="summary-card">
                <div class="number" style="color: {'var(--alert)' if limit_warn_count > 0 else 'var(--text-secondary)'}">{limit_warn_count}</div>
                <div class="label">限购影响定投{'（收紧' + str(limit_tighten_count) + '只）' if limit_tighten_count else ''}</div>
            </div>
        </div>
        
        <div class="section-title">组合概览</div>
        {overview_html}
        
        <div class="section-title">持仓基金明细</div>
        {''.join(fund_cards)}
        
        <div class="section-title">关联市场行情</div>
        <div class="market-section">
            {''.join(index_cards) if index_cards else '<div style="color:var(--text-secondary);text-align:center;">市场数据获取中...</div>'}
        </div>
        
        <div class="section-title">基金经理变更 &amp; 规模·清盘预警</div>
        <div class="profile-section">
            {''.join(profile_items) if profile_items else '<div style="color:var(--text-secondary);text-align:center;">本轮未采集外围风险（可用 --no-profile 关闭该板块）</div>'}
        </div>

        <div class="section-title">限购额度变化监控</div>
        <div class="profile-section">
            {''.join(limit_items) if limit_items else '<div style="color:var(--text-secondary);text-align:center;">本轮未采集限购额度（可用 --no-profile 关闭该板块）</div>'}
        </div>
        
        <div class="legend">
            <strong>指标说明：</strong>
            最大回撤 = 一段时间内净值从最高点下跌的最大幅度，越小越好 |
            年化波动 = 净值波动的年化标准差，越小越稳定 |
            夏普比率 = 超额收益/风险，越大越好（>1优秀） |
            Calmar = 年化收益/最大回撤，越大越好 |
            90天收益 = 近90个交易日总收益率
            <br><br>
            <strong>外围风险口径：</strong>
            基金经理变更 = 天天基金「本基金历任基金经理」最新一条起始期在 180 天内即视为近期变更；
            规模为季报口径（期末净资产）；清盘线取 5000 万元（基金合同常见条款：连续 60 个工作日
            资产净值低于 5000 万可终止合同），2 亿元以下标记为迷你基金，单季环比 ≥ +100% 标记为规模显著扩张。
            <strong>限购额度</strong>取自天天基金基金费率页「单日累计购买上限」，
            与计划日投（月投入 ÷ 30）比较判断是否影响定投执行，并与上次采集对比标注收紧/放宽。
            取不到数据时显示"暂缺"，不用任何模拟值代替。
        </div>
        
        <div class="footer">
            金水谣万物引擎 - 基金监控子系统 | 净值数据来源于东方财富(akshare)，外围风险来源于天天基金公开页面 | 本报告仅供参考，不构成投资建议
        </div>
    </div>
</body>
</html>"""
        return html


# ================================================================
# 主流程
# ================================================================

class DailyFundMonitor:
    """每日基金监控主控类"""

    def __init__(self):
        self.fetcher = FundDataFetcher()
        self.risk_calc = RiskCalculator()
        self.signal_detector = SignalDetector()
        # JS-20260923-11 批2：区间收益分析引擎（缺失则跳过区间收益栏，不报错）
        self.analyzer = FundAnalyzer() if ANALYZER_AVAILABLE else None
        self.ranks = {}
        self.report_gen = ReportGenerator(
            output_dir=os.path.join(_SCRIPT_DIR, "金水谣数据", "fund_reports")
        )
        self.monitor_data = {}
        self.profiles = {}

    def run(self, export_historical: bool = False, force: bool = False,
            with_profile: bool = True) -> Dict:
        """执行完整监控流程
        
        Args:
            export_historical: 是否导出90天历史CSV
            force: 是否强制重新执行（即使今日报告已存在）
            with_profile: 是否采集外围风险（基金经理变更 / 规模·清盘预警 / 限购额度）
            
        Returns:
            Dict: 包含报告路径、数据路径和监控数据的字典
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        report_dir = os.path.join(_SCRIPT_DIR, "金水谣数据", "fund_reports")
        report_path_today = os.path.join(report_dir, f"fund_report_{today_str}.html")
        notif_path = os.path.join(report_dir, ".notification.json")
        
        # 防重复执行检测：如果今日报告已存在且不强制，则跳过
        if not force and os.path.isfile(report_path_today) and os.path.isfile(notif_path):
            logger.info("今日报告已存在 (%s)，跳过重复执行。使用 --force 强制刷新。", report_path_today)
            # 读取已有通知文件返回关键信息
            try:
                with open(notif_path, 'r', encoding='utf-8') as f:
                    existing_notif = json.load(f)
                logger.info("已有报告摘要: 止盈信号 %d 个, 限购 %d 只",
                    existing_notif.get("summary", {}).get("take_profit_count", 0),
                    existing_notif.get("summary", {}).get("limit_count", 0))
                return {
                    "report_path": report_path_today,
                    "json_path": os.path.join(_SCRIPT_DIR, "金水谣数据", "fund_data", f"fund_monitor_{datetime.now().strftime('%Y%m%d')}.json"),
                    "monitor_data": {},
                    "market_indices": {},
                    "skipped": True,
                    "notification": existing_notif,
                }
            except Exception:
                pass  # 读取失败则继续执行
        
        logger.info("=" * 50)
        logger.info("开始执行每日基金监控...")
        logger.info("=" * 50)

        # 1.0 采集同类排名（真实数据缺失时返回空，卡片显示「暂缺」）——JS-20260923-11 批2
        self.ranks = self._collect_ranks()

        # 1. 获取每只基金的数据
        for fund in FUND_CONFIG:
            code = fund["code"]
            logger.info("正在分析基金: %s %s", code, fund["name"])
            
            # 获取当日快照
            snapshot = self.fetcher.get_fund_snapshot(code)
            if snapshot is None:
                logger.warning("基金 %s 快照获取失败，跳过", code)
                continue
            
            # 获取历史数据（近3年，供区间收益；同时截取最近90天供风险/信号，保持旧口径——JS-20260923-11 批2）
            history_full = self.fetcher.get_fund_history(code, days=800)
            history = (
                history_full.tail(90)
                if history_full is not None and not history_full.empty
                else history_full
            )

            # 计算风险指标（基于最近90天窗口，与旧报告一致）
            risks = {}
            if history is not None and not history.empty:
                nav_series = history["单位净值"].astype(float)
                risks = {
                    "max_drawdown": self.risk_calc.calc_max_drawdown(nav_series),
                    "volatility": self.risk_calc.calc_volatility(nav_series),
                    "sharpe": self.risk_calc.calc_sharpe(nav_series),
                    "calmar": self.risk_calc.calc_calmar(nav_series),
                    "total_return": self.risk_calc.calc_total_return(nav_series),
                }

            # JS-20260923-11 批2：区间收益（近3月/6月/1年/近3年）复用 analyzer.calculate_returns，不重写
            interval_returns = {}
            if self.analyzer is not None and history_full is not None and not history_full.empty and len(history_full) >= 5:
                navs = history_full["单位净值"].astype(float).tolist()
                dates = history_full["净值日期"].astype(str).tolist() if "净值日期" in history_full.columns else None
                _full = self.analyzer.calculate_returns(navs, dates)
                interval_returns = {k: v for k, v in _full.items()
                                    if k in ("近3月", "近6月", "近1年", "近3年")}

            # 检测信号
            signals = {}
            hist_series = (
                history["单位净值"].astype(float)
                if history is not None and not history.empty
                else None
            )
            nav = snapshot.get("nav_today")
            if nav is None and hist_series is not None:
                # 快照净值缺失（周末/QDII延迟）时用历史最新净值兜底，避免止盈检测失效
                nav = float(hist_series.iloc[-1])

            # JS-20260924-02 修复1：止盈判定端点必须与 calc_total_return 同源（都用历史末值）。
            # 此前传的是快照 nav_today(daily_df/东财)，而指标行用 history.iloc[-1](akshare)，
            # 两源最新净值略有差异 → 卡片「90天收益」与止盈注「90天区间收益」算出两个值
            # （实测 8 只全部不一致，差 0.33~0.53pp）。
            tp_nav = (float(hist_series.iloc[-1])
                      if hist_series is not None and not hist_series.empty else nav)

            # JS-20260924-02 修复2：快照日涨跌缺失时，用历史末两个净值补算（历史序列始终连续）。
            # daily_df 只含最新一列时 nav_yesterday 为 None，导致「日涨跌」整列全 "--"。
            _fill_daily_return_from_history(snapshot, hist_series)

            if tp_nav is not None and hist_series is not None:
                signals["take_profit"] = self.signal_detector.check_take_profit(
                    tp_nav, fund["investment"], fund["target_profit"], hist_series,
                    warn_line=fund.get("warn_line")
                )
            else:
                signals["take_profit"] = {"signal": False, "message": "净值数据缺失"}

            signals["purchase_limit"] = self.signal_detector.check_purchase_limit(
                snapshot.get("buy_status", "")
            )

            if hist_series is not None:
                signals["significant_drop"] = self.signal_detector.check_significant_drop(
                    hist_series
                )

            self.monitor_data[code] = {
                "snapshot": snapshot,
                "risks": risks,
                "signals": signals,
                "config": fund,
                "interval_returns": interval_returns,
                "rank": self.ranks.get(code),
            }
        
        # 1.5 外围风险采集（基金经理变更 / 规模变化·清盘预警）
        if with_profile:
            self.profiles = self._collect_profiles()
            for code, profile in self.profiles.items():
                if code in self.monitor_data:
                    self.monitor_data[code]["profile"] = profile
        
        # 2. 获取市场指数
        market_indices = self.fetcher.get_market_indices()
        
        # 3. 生成HTML报告
        report_path = self.report_gen.generate(
            self.monitor_data, market_indices, self.profiles)
        
        # 4. 保存JSON数据
        json_path = self._save_json()
        
        # 5. 可选：导出历史CSV
        if export_historical:
            self._export_historical_csv()
        
        # 6. 保存通知标记 + 发送Windows系统通知 + 微信推送
        self._save_notification(report_path)
        self._send_windows_notification(report_path)
        self._send_wechat_notification(report_path)
        
        logger.info("=" * 50)
        logger.info("监控完成！")
        logger.info("HTML报告: %s", report_path)
        logger.info("JSON数据: %s", json_path)
        logger.info("=" * 50)
        
        return {
            "report_path": report_path,
            "json_path": json_path,
            "monitor_data": self.monitor_data,
            "market_indices": market_indices,
        }

    def _collect_profiles(self) -> Dict:
        """采集基金外围风险（基金经理变更 / 规模变化·清盘预警 / 限购额度）

        数据源为天天基金公开页面，低速串行抓取；失败时该板块显示"暂缺"，不编造。
        """
        if not PROFILE_AVAILABLE:
            logger.warning("外围风险模块不可用，跳过该板块: %s", PROFILE_IMPORT_ERR)
            return {}
        try:
            logger.info("正在采集外围风险（基金经理变更 / 规模变动 / 限购额度）...")
            profiles = build_profiles(FUND_CONFIG)
            mgr_warn = sum(1 for p in profiles.values()
                           if p.get("manager", {}).get("level") == "warn")
            mgr_notice = sum(1 for p in profiles.values()
                             if p.get("manager", {}).get("level") == "notice")
            scale_warn = sum(1 for p in profiles.values()
                             if p.get("scale", {}).get("level") in ("warn", "danger"))
            limit_warn = sum(1 for p in profiles.values()
                             if p.get("limit", {}).get("level") == "warn")
            limit_tighten = sum(1 for p in profiles.values()
                                if p.get("limit_change") == "tighter")
            logger.info("外围风险采集完成：经理近期变更 %d 只，配置待核对 %d 只，"
                        "规模预警 %d 只，限购影响定投 %d 只（其中本次采集到收紧 %d 只）",
                        mgr_warn, mgr_notice, scale_warn, limit_warn, limit_tighten)
            return profiles
        except Exception as e:
            logger.warning("外围风险采集失败，跳过该板块: %s", e)
            return {}

    def _collect_ranks(self) -> Dict:
        """采集同类排名（近1月…近3年 + 同类排名）

        JS-20260923-11 批2：复用领域层 FundFetcher.get_rank()。
        真实数据不可用时（real_only=True）返回空 dict，报告对应栏显示「暂缺」，
        绝不返回模拟排名（违背诚实铁律）。
        """
        if not RANK_FETCHER_AVAILABLE:
            logger.warning("排名模块不可用，跳过该栏（显示暂缺）: %s", RANK_FETCHER_IMPORT_ERR)
            return {}
        try:
            logger.info("正在采集同类排名（真实数据优先）...")
            rk_fetcher = FundFetcher()
            df = rk_fetcher.get_rank(real_only=True, use_cache=False)
            if df is None or df.empty or "基金代码" not in df.columns:
                logger.warning("同类排名真实数据不可用，跳过该栏（显示暂缺）")
                return {}
            rank_map = {}
            for _, row in df.iterrows():
                code = str(row.get("基金代码", "")).strip()
                rank_str = str(row.get("同类排名", "")).strip()
                if code:
                    rank_map[code] = {"rank": rank_str}
            logger.info("同类排名采集完成：%d 只基金", len(rank_map))
            return rank_map
        except Exception as e:
            logger.warning("同类排名采集失败，跳过该栏（显示暂缺）: %s", e)
            return {}

    def _save_notification(self, report_path: str):
        """保存通知标记文件，供总控台检测未读日报"""
        try:
            # 提取关键摘要
            take_profit_funds = []
            limit_funds = []
            max_drop_fund = None
            max_drop_pct = 0
            
            for code, data in self.monitor_data.items():
                fund_name = data.get("config", {}).get("name", code)
                
                tp = data.get("signals", {}).get("take_profit", {})
                if tp.get("signal"):
                    take_profit_funds.append(f"{fund_name} (+{tp.get('current_return', 0)}%)")
                
                pl = data.get("signals", {}).get("purchase_limit", {})
                if pl.get("is_limited"):
                    limit_funds.append(fund_name)
                
                sd = data.get("signals", {}).get("significant_drop", {})
                if sd.get("drop_pct", 0) < max_drop_pct:
                    max_drop_pct = sd.get("drop_pct", 0)
                    max_drop_fund = fund_name
            
            nav_changes = []
            for code, data in self.monitor_data.items():
                snapshot = data.get("snapshot", {})
                daily_ret = snapshot.get("daily_return")
                if daily_ret is not None:
                    nav_changes.append({
                        "name": data.get("config", {}).get("name", code),
                        "code": code,
                        "change_pct": daily_ret,
                    })
            
            nav_changes.sort(key=lambda x: x["change_pct"], reverse=True)
            
            notification = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "report_path": report_path,
                "is_read": False,
                "summary": {
                    "take_profit_count": len(take_profit_funds),
                    "take_profit_funds": take_profit_funds,
                    "limit_count": len(limit_funds),
                    "limit_funds": limit_funds,
                    "top_gainer": nav_changes[0] if nav_changes else None,
                    "top_loser": nav_changes[-1] if nav_changes else None,
                    "max_drop_alert": f"{max_drop_fund} ({max_drop_pct}%)" if max_drop_fund else None,
                },
            }
            
            notif_path = os.path.join(_SCRIPT_DIR, "金水谣数据", "fund_reports", ".notification.json")
            safe_write_json(notif_path, notification)
            
            logger.info("通知标记已保存: %s", notif_path)
        except Exception as e:
            logger.warning("保存通知标记失败: %s", e)

    def _send_windows_notification(self, report_path: str):
        """发送Windows系统通知（右下角弹出，不阻塞）"""
        try:
            import subprocess
            
            # 提取摘要用于通知内容
            tp_count = sum(1 for d in self.monitor_data.values() 
                          if d.get("signals", {}).get("take_profit", {}).get("signal", False))
            
            nav_changes = []
            for data in self.monitor_data.values():
                snapshot = data.get("snapshot", {})
                ret = snapshot.get("daily_return")
                if ret is not None:
                    nav_changes.append(ret)
            
            if nav_changes:
                avg_change = sum(nav_changes) / len(nav_changes)
                avg_str = f"平均涨跌 {avg_change:+.2f}%"
            else:
                avg_str = "数据已更新"
            
            title = f"金水谣基金日报 - {datetime.now().strftime('%m月%d日')}"
            msg = f"{avg_str} | 止盈信号 {tp_count} 个"
            if tp_count > 0:
                msg += " | 有基金达到目标收益！"
            
            # 使用 PowerShell 发送 Windows 通知中心消息（不阻塞）
            ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = '{title}'
$notify.BalloonTipText = '{msg}'
$notify.Visible = $true
$notify.ShowBalloonTip(5000)
Start-Sleep -Milliseconds 5500
$notify.Dispose()
"""
            subprocess.Popen(
                ["powershell.exe", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0
            )
            
            logger.info("Windows系统通知已发送")
        except Exception as e:
            logger.warning("发送Windows通知失败: %s", e)

    def _send_wechat_notification(self, report_path: str):
        """通过 Server酱 推送基金日报到微信"""
        try:
            from utils.notifier import notify_fund_report
            tp_count = sum(1 for d in self.monitor_data.values()
                          if d.get("signals", {}).get("take_profit", {}).get("signal", False))
            nav_changes = []
            for data in self.monitor_data.values():
                snapshot = data.get("snapshot", {})
                ret = snapshot.get("daily_return")
                if ret is not None:
                    nav_changes.append(ret)
            if nav_changes:
                avg_change = sum(nav_changes) / len(nav_changes)
                summary = f"平均涨跌 {avg_change:+.2f}% | 止盈信号 {tp_count} 个"
            else:
                summary = f"止盈信号 {tp_count} 个"
            date = datetime.now().strftime('%Y-%m-%d')
            notify_fund_report(date, summary, report_path)
        except Exception:
            pass  # 微信推送失败不阻塞主流程

    @staticmethod
    def _clean_for_json(obj):
        """递归清理对象中的numpy类型，使其可JSON序列化"""
        if isinstance(obj, dict):
            return {k: DailyFundMonitor._clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [DailyFundMonitor._clean_for_json(v) for v in obj]
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif pd.isna(obj):
            return None
        else:
            return obj

    def _save_json(self) -> str:
        """保存监控数据为JSON"""
        date_str = datetime.now().strftime("%Y%m%d")
        json_dir = os.path.join(_SCRIPT_DIR, "金水谣数据", "fund_data")
        os.makedirs(json_dir, exist_ok=True)
        
        filepath = os.path.join(json_dir, f"fund_monitor_{date_str}.json")
        
        # 序列化（处理pandas/numpy类型）
        serializable = {}
        for code, data in self.monitor_data.items():
            serializable[code] = {
                "snapshot": self._clean_for_json(data.get("snapshot", {})),
                "risks": self._clean_for_json(data.get("risks", {})),
                "signals": self._clean_for_json(data.get("signals", {})),
                "profile": self._clean_for_json(data.get("profile", {})),
            }
        
        safe_write_json(filepath, {
            "date": datetime.now().isoformat(),
            "funds": serializable,
            "profiles": self._clean_for_json(self.profiles or {}),
        })
        
        return filepath

    def _export_historical_csv(self):
        """导出所有基金90天历史数据为CSV"""
        date_str = datetime.now().strftime("%Y%m%d")
        csv_dir = os.path.join(_SCRIPT_DIR, "金水谣数据", "fund_data")
        os.makedirs(csv_dir, exist_ok=True)
        
        all_data = []
        for fund in FUND_CONFIG:
            code = fund["code"]
            history = self.fetcher.get_fund_history(code, days=90)
            if history is not None and not history.empty:
                history["基金代码"] = code
                history["基金名称"] = fund["name"]
                all_data.append(history)
        
        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            filepath = os.path.join(csv_dir, f"fund_history_90d_{date_str}.csv")
            combined.to_csv(filepath, index=False, encoding='utf-8-sig')
            logger.info("历史数据已导出: %s", filepath)


# ================================================================
# 入口
# ================================================================

def main():
    parser = argparse.ArgumentParser(description="金水谣每日基金监控")
    parser.add_argument("--historical", action="store_true", help="同时导出90天历史CSV")
    parser.add_argument("--force", action="store_true", help="强制重新执行（忽略今日已有报告）")
    parser.add_argument("--no-profile", action="store_true",
                        help="跳过外围风险采集（基金经理变更 / 规模·清盘预警）")
    args = parser.parse_args()
    
    monitor = DailyFundMonitor()
    result = monitor.run(export_historical=args.historical, force=args.force,
                         with_profile=not args.no_profile)
    
    if result.get("skipped"):
        print("\n今日报告已存在，跳过重复执行。")
        print(f"报告文件: {result['report_path']}")
        print(f"如需强制刷新，请添加 --force 参数")
    else:
        print("\n监控完成！")
        print(f"报告文件: {result['report_path']}")
        print(f"数据文件: {result['json_path']}")
    return result


if __name__ == "__main__":
    main()
