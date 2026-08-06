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

FUND_CONFIG = [
    {
        "code": "005698",
        "name": "华夏全球科技先锋混合(QDII)A",
        "category": "QDII-科技",
        "investment": 3000,
        "target_profit": 0.164,
        "manager": "李博",
        "company": "华夏基金",
        "risk_level": "高",
        "related_index": "纳斯达克100",
    },
    {
        "code": "017641",
        "name": "摩根标普500指数(QDII)人民币A",
        "category": "QDII-宽基",
        "investment": 3000,
        "target_profit": 0.164,
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
        "target_profit": 0.164,
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
        "target_profit": 0.164,
        "manager": "周海栋",
        "company": "华商基金",
        "risk_level": "中高",
        "related_index": "沪深300",
    },
    {
        "code": "015942",
        "name": "上银慧享利30天滚动持有中短债发起A",
        "category": "债券型",
        "investment": 10000,
        "target_profit": 0.05,
        "manager": "陈芳菲",
        "company": "上银基金",
        "risk_level": "低",
        "related_index": "中债总指数",
    },
    {
        "code": "009051",
        "name": "易方达中证红利ETF联接发起式A",
        "category": "指数型-红利",
        "investment": 10000,
        "target_profit": 0.10,
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
        "target_profit": 0.12,
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
        "target_profit": 0.164,
        "manager": "范冰",
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
        """加载当日全部开放式基金数据（用于快速查询）"""
        try:
            import akshare as ak
            self.daily_df = ak.fund_open_fund_daily_em()
            logger.info("已加载当日基金数据，共 %d 条", len(self.daily_df))
        except Exception as e:
            logger.error("加载当日基金数据失败: %s", e)
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
    def calc_calmar(nav_series: pd.Series) -> float:
        """计算Calmar比率（年化收益/最大回撤）"""
        if nav_series.empty or len(nav_series) < 5:
            return 0.0
        returns = nav_series.pct_change().dropna()
        if returns.empty:
            return 0.0
        annual_return = returns.mean() * 252
        max_dd = RiskCalculator.calc_max_drawdown(nav_series) / 100
        if max_dd == 0:
            return 0.0
        return round(annual_return / max_dd, 2)

    @staticmethod
    def calc_total_return(nav_series: pd.Series) -> float:
        """计算区间总收益率（%）"""
        if nav_series.empty or len(nav_series) < 2:
            return 0.0
        total = (nav_series.iloc[-1] - nav_series.iloc[0]) / nav_series.iloc[0]
        return round(total * 100, 2)


# ================================================================
# 信号检测
# ================================================================

class SignalDetector:
    """投资信号检测器"""

    @staticmethod
    def check_take_profit(current_nav: float, investment: float, target_profit: float, 
                          nav_series: pd.Series) -> Dict:
        """检测止盈信号
        
        由于我们不知道买入时的净值，使用历史数据估算：
        - 如果有历史数据，假设买入点为区间起点
        - 计算当前收益是否达到目标
        """
        if nav_series is None or nav_series.empty or len(nav_series) < 2:
            return {"signal": False, "current_return": None, "message": "历史数据不足"}
        
        buy_nav = nav_series.iloc[0]  # 简化：以区间第一天为买入点
        current_return = (current_nav - buy_nav) / buy_nav
        
        signal = current_return >= target_profit
        return {
            "signal": signal,
            "current_return": round(current_return * 100, 2),
            "target_return": round(target_profit * 100, 1),
            "message": f"当前收益 {round(current_return*100,2)}%，目标 {round(target_profit*100,1)}%" + (" ⚠️ 已达到止盈目标！" if signal else ""),
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

class ReportGenerator:
    """HTML日报生成器 - 暗色科技风"""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate(self, monitor_data: Dict, market_indices: Dict) -> str:
        """生成HTML报告，返回文件路径"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M")
        filename = f"fund_report_{date_str}.html"
        filepath = os.path.join(self.output_dir, filename)

        html = self._build_html(date_str, time_str, monitor_data, market_indices)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info("报告已生成: %s", filepath)
        return filepath

    def _build_html(self, date_str: str, time_str: str, data: Dict, indices: Dict) -> str:
        """构建HTML内容"""
        
        # 统计
        total_invest = sum(f["investment"] for f in FUND_CONFIG)
        take_profit_count = sum(1 for d in data.values() if d.get("signals", {}).get("take_profit", {}).get("signal", False))
        limit_count = sum(1 for d in data.values() if d.get("signals", {}).get("purchase_limit", {}).get("is_limited", False))
        
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
            
            tp = signals.get("take_profit", {})
            pl = signals.get("purchase_limit", {})
            sd = signals.get("significant_drop", {})
            
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
                            <div class="metric-label">最新净值</div>
                            <div class="metric-value">{nav if nav else "--"}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">日涨跌</div>
                            <div class="metric-value {daily_ret_class}">{daily_ret_str}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">最大回撤</div>
                            <div class="metric-value">{risks.get("max_drawdown", "--")}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">年化波动</div>
                            <div class="metric-value">{risks.get("volatility", "--")}%</div>
                        </div>
                    </div>
                    <div class="metric-row">
                        <div class="metric">
                            <div class="metric-label">夏普比率</div>
                            <div class="metric-value">{risks.get("sharpe", "--")}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Calmar</div>
                            <div class="metric-value">{risks.get("calmar", "--")}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">90天收益</div>
                            <div class="metric-value">{risks.get("total_return", "--")}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">申购状态</div>
                            <div class="metric-value {'limit' if pl.get('is_limited') else 'ok'}">{pl.get("status", "--")}</div>
                        </div>
                    </div>
                    <div class="signals">
                        {f'<div class="signal alert">止盈信号: {tp.get("message", "")}</div>' if tp.get("signal") else f'<div class="signal info">{tp.get("message", "")}</div>'}
                        {f'<div class="signal warning">{sd.get("message", "")}</div>' if sd.get("signal") else ''}
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
            --info: #3b82f6;
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
        .signal.info {{ background: rgba(59, 130, 246, 0.1); color: var(--info); }}
        
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
            <div class="subtitle">报告日期: {date_str} {time_str} | 共监控 {len(FUND_CONFIG)} 只基金</div>
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
        </div>
        
        <div class="section-title">持仓基金明细</div>
        {''.join(fund_cards)}
        
        <div class="section-title">关联市场行情</div>
        <div class="market-section">
            {''.join(index_cards) if index_cards else '<div style="color:var(--text-secondary);text-align:center;">市场数据获取中...</div>'}
        </div>
        
        <div class="legend">
            <strong>指标说明：</strong>
            最大回撤 = 一段时间内净值从最高点下跌的最大幅度，越小越好 |
            年化波动 = 净值波动的年化标准差，越小越稳定 |
            夏普比率 = 超额收益/风险，越大越好（>1优秀） |
            Calmar = 年化收益/最大回撤，越大越好 |
            90天收益 = 近90个交易日总收益率
        </div>
        
        <div class="footer">
            金水谣万物引擎 - 基金监控子系统 | 数据来源于东方财富(akshare) | 本报告仅供参考，不构成投资建议
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
        self.report_gen = ReportGenerator(
            output_dir=os.path.join(_SCRIPT_DIR, "金水谣数据", "fund_reports")
        )
        self.monitor_data = {}

    def run(self, export_historical: bool = False, force: bool = False) -> Dict:
        """执行完整监控流程
        
        Args:
            export_historical: 是否导出90天历史CSV
            force: 是否强制重新执行（即使今日报告已存在）
            
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

        # 1. 获取每只基金的数据
        for fund in FUND_CONFIG:
            code = fund["code"]
            logger.info("正在分析基金: %s %s", code, fund["name"])
            
            # 获取当日快照
            snapshot = self.fetcher.get_fund_snapshot(code)
            if snapshot is None:
                logger.warning("基金 %s 快照获取失败，跳过", code)
                continue
            
            # 获取历史数据
            history = self.fetcher.get_fund_history(code, days=90)
            
            # 计算风险指标
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
            if nav is not None and hist_series is not None:
                signals["take_profit"] = self.signal_detector.check_take_profit(
                    nav, fund["investment"], fund["target_profit"], hist_series
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
            }
        
        # 2. 获取市场指数
        market_indices = self.fetcher.get_market_indices()
        
        # 3. 生成HTML报告
        report_path = self.report_gen.generate(self.monitor_data, market_indices)
        
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
            with open(notif_path, 'w', encoding='utf-8') as f:
                json.dump(notification, f, ensure_ascii=False, indent=2)
            
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
            }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
                "date": datetime.now().isoformat(),
                "funds": serializable,
            }, f, ensure_ascii=False, indent=2)
        
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
    args = parser.parse_args()
    
    monitor = DailyFundMonitor()
    result = monitor.run(export_historical=args.historical, force=args.force)
    
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
