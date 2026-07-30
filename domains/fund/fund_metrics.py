# -*- coding: utf-8 -*-
"""基金专属业绩归因指标

在 FundAnalyzer 基础指标之上提供更专业的基金评价指标：
  - Alpha (Jensen's Alpha)
  - Beta（市场敏感度）
  - Tracking Error（跟踪误差）
  - Information Ratio（信息比率）
  - Up/Down Capture Ratios（上行/下行捕获率）
  - 与基准的相关性分析
  - 滚动指标计算

所有方法均无外部依赖，纯 Python 实现。
基准数据默认使用沪深300指数（sh000300），也可自定义。
"""
import math
import logging

logger = logging.getLogger(__name__)


class FundMetrics:
    """基金专属业绩归因指标计算器

    用法：
        metrics = FundMetrics()
        result = metrics.calculate(fund_navs, bench_navs)
        # result: { alpha, beta, tracking_error, info_ratio,
        #            up_capture, down_capture, up_down_ratio,
        #            correlation, r_squared, ... }
    """

    def __init__(self, risk_free_rate=0.02, trading_days=252):
        self.risk_free_rate = risk_free_rate
        self.trading_days = trading_days

    def calculate(self, fund_navs, bench_navs):
        """计算全套基金归因指标

        Args:
            fund_navs: 基金净值序列 [float]（按时间升序）
            bench_navs: 基准净值序列 [float]（与 fund_navs 同频对齐）

        Returns:
            dict: 归因指标字典；数据不足时含 error 字段
        """
        if not fund_navs or len(fund_navs) < 30:
            return {"error": "基金净值数据不足30条"}
        if not bench_navs or len(bench_navs) < 30:
            return {"error": "基准净值数据不足30条"}

        fund_rets = self._to_daily_returns(fund_navs)
        bench_rets = self._to_daily_returns(bench_navs)

        min_len = min(len(fund_rets), len(bench_rets))
        if min_len < 30:
            return {"error": f"对齐后日收益率数据不足（{min_len}条）"}
        fund_rets = fund_rets[-min_len:]
        bench_rets = bench_rets[-min_len:]

        n = min_len
        rf_daily = self.risk_free_rate / self.trading_days

        fund_excess = [r - rf_daily for r in fund_rets]
        bench_excess = [r - rf_daily for r in bench_rets]

        mean_fund = sum(fund_rets) / n
        mean_bench = sum(bench_rets) / n
        mean_fund_ex = sum(fund_excess) / n
        mean_bench_ex = sum(bench_excess) / n

        var_bench = sum((r - mean_bench) ** 2 for r in bench_rets) / n
        cov = sum((fund_rets[i] - mean_fund) * (bench_rets[i] - mean_bench)
                  for i in range(n)) / n

        beta = cov / var_bench if var_bench else 0.0
        annual_fund = mean_fund * self.trading_days
        annual_bench = mean_bench * self.trading_days
        alpha = (annual_fund - self.risk_free_rate) - beta * (annual_bench - self.risk_free_rate)

        diff_rets = [fund_rets[i] - bench_rets[i] for i in range(n)]
        mean_diff = sum(diff_rets) / n
        var_diff = sum((r - mean_diff) ** 2 for r in diff_rets) / n
        tracking_error = math.sqrt(var_diff) * math.sqrt(self.trading_days)
        annual_diff = mean_diff * self.trading_days
        info_ratio = annual_diff / tracking_error if tracking_error else 0.0

        up_fund, up_bench = [], []
        dn_fund, dn_bench = [], []
        for i in range(n):
            if bench_rets[i] >= 0:
                up_fund.append(fund_rets[i])
                up_bench.append(bench_rets[i])
            else:
                dn_fund.append(fund_rets[i])
                dn_bench.append(abs(bench_rets[i]))

        up_capture = (sum(up_fund) / len(up_fund) / (sum(up_bench) / len(up_bench))
                      ) if up_bench and sum(up_bench) else 0.0
        dn_capture = (sum(dn_fund) / len(dn_fund) / (sum(dn_bench) / len(dn_bench))
                      ) if dn_bench and sum(dn_bench) else 0.0
        up_down_ratio = up_capture / dn_capture if dn_capture else 0.0

        corr_num = cov
        var_fund = sum((r - mean_fund) ** 2 for r in fund_rets) / n
        corr_den = math.sqrt(var_fund) * math.sqrt(var_bench) if var_fund and var_bench else 0
        correlation = corr_num / corr_den if corr_den else 0.0
        r_squared = correlation ** 2

        fund_vol = math.sqrt(var_fund) * math.sqrt(self.trading_days)
        bench_vol = math.sqrt(var_bench) * math.sqrt(self.trading_days)

        return {
            "alpha": round(alpha, 4),
            "alpha_pct": f"{alpha*100:.2f}%",
            "beta": round(beta, 4),
            "tracking_error": round(tracking_error, 4),
            "tracking_error_pct": f"{tracking_error*100:.2f}%",
            "information_ratio": round(info_ratio, 4),
            "up_capture": round(up_capture, 4),
            "up_capture_pct": f"{up_capture*100:.2f}%",
            "down_capture": round(dn_capture, 4),
            "down_capture_pct": f"{dn_capture*100:.2f}%",
            "up_down_ratio": round(up_down_ratio, 4),
            "correlation": round(correlation, 4),
            "r_squared": round(r_squared, 4),
            "fund_volatility": round(fund_vol, 4),
            "bench_volatility": round(bench_vol, 4),
            "fund_annual_return": round(annual_fund, 4),
            "bench_annual_return": round(annual_bench, 4),
            "excess_annual_return": round(annual_diff, 4),
            "period_days": n,
            "summary": self._generate_summary(alpha, beta, info_ratio, up_capture, dn_capture),
        }

    def rolling_alpha(self, fund_navs, bench_navs, window=252):
        """滚动 Alpha 计算（用于判断超额收益稳定性）

        Args:
            fund_navs: 基金净值序列
            bench_navs: 基准净值序列
            window: 滚动窗口（交易日，默认252≈1年）

        Returns:
            [{"date": str, "alpha": float}, ...]
        """
        fund_rets = self._to_daily_returns(fund_navs)
        bench_rets = self._to_daily_returns(bench_navs)
        min_len = min(len(fund_rets), len(bench_rets))
        if min_len < window + 10:
            return []
        fund_rets = fund_rets[-min_len:]
        bench_rets = bench_rets[-min_len:]

        result = []
        for i in range(window, len(fund_rets)):
            f_slice = fund_rets[i - window:i]
            b_slice = bench_rets[i - window:i]
            n = window
            rf_d = self.risk_free_rate / self.trading_days
            fe = [r - rf_d for r in f_slice]
            be = [r - rf_d for r in b_slice]
            mf = sum(fe) / n
            mb = sum(be) / n
            vb = sum((r - sum(b_slice) / n) ** 2 for r in b_slice) / n
            cv = sum((fe[j] - mf) * (be[j] - mb) for j in range(n)) / n
            b = cv / vb if vb else 0
            af = sum(f_slice) / n * self.trading_days
            ab = sum(b_slice) / n * self.trading_days
            a = (af - self.risk_free_rate) - b * (ab - self.risk_free_rate)
            result.append({"date": str(i), "alpha": round(a, 4)})
        return result

    def _to_daily_returns(self, navs):
        if not navs or len(navs) < 2:
            return []
        rets = []
        for i in range(1, len(navs)):
            if navs[i - 1]:
                rets.append((navs[i] - navs[i - 1]) / navs[i - 1])
        return rets

    def _generate_summary(self, alpha, beta, ir, up_cap, dn_cap):
        parts = []
        if alpha > 0.02:
            parts.append(f"Alpha={alpha*100:.1f}% 超额收益显著")
        elif alpha > 0:
            parts.append(f"Alpha={alpha*100:.1f}% 微弱超额")
        else:
            parts.append(f"Alpha={alpha*100:.1f}% 未产生超额")

        if beta < 0.8:
            parts.append(f"Beta={beta:.2f} 防御型")
        elif beta < 1.2:
            parts.append(f"Beta={beta:.2f} 市场同步")
        else:
            parts.append(f"Beta={beta:.2f} 进攻型")

        if ir > 0.5:
            parts.append(f"信息比率{ir:.2f} 优秀")
        elif ir > 0:
            parts.append(f"信息比率{ir:.2f} 一般")

        if up_cap > 1.1 and dn_cap < 0.9:
            parts.append("捕获率高α低β特征")
        elif up_cap > dn_cap:
            parts.append("上涨捕获 > 下跌捕获")
        else:
            parts.append("下跌捕获 > 上涨捕获")

        return "，".join(parts)
