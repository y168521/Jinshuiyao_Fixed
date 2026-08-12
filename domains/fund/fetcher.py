# -*- coding: utf-8 -*-
"""基金数据获取模块

优先使用 akshare（免费开源基金数据），不可用时提供模拟数据降级。

支持的数据类型：
  - 基金列表（全部/分类）
  - 基金净值（历史单位净值、累计净值）
  - 基金基本信息（基金经理、规模、成立日期等）
  - 基金排名（同类排名）
  - 基金持仓（十大重仓股）
"""
import os
import json
import logging
from utils.safe_json import safe_load_json, safe_write_json
import random
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class FundFetcher:
    """基金数据获取器

    支持数据源：
      - akshare: 免费公募基金数据（首选）
      - 本地缓存: JSON格式历史数据
      - 模拟数据: 降级模式

    内置熔断器和缓存机制，与股票子系统风格保持一致。
    """

    # 默认关注的示例基金代码（混合型/股票型/债券型/指数型各几只）
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

    # 默认池名称表（真实基金名称，供前端下拉快速渲染，不发网络）
    DEFAULT_FUND_NAMES = {
        "000001": "华夏成长混合",
        "110011": "易方达中小盘混合",
        "161725": "招商中证白酒指数",
        "005827": "易方达蓝筹精选混合",
        "001102": "前海开源国家比较优势",
        "519674": "银河创新成长混合",
        "003096": "中欧医疗健康混合",
        "001071": "华安媒体互联网混合",
        "001875": "前海开源沪港深优势精选",
        "260108": "景顺长城新兴成长混合",
        "000961": "天弘沪深300ETF联接A",
        "110022": "易方达消费行业股票",
        "000171": "易方达裕丰回报债券",
        "003547": "鹏华丰禄债券",
        "163406": "兴全合润混合",
    }

    def get_fund_names_map(self, codes=None):
        """快速获取基金名称映射 {code: name}（仅缓存+内置表，不发网络请求）

        优先级：本地列表缓存 → 内置名称表 → 代码本身。
        """
        name_map = {}
        try:
            cached = self._read_cache("list_all")
            if cached is not None and hasattr(cached, "columns"):
                for _, row in cached.iterrows():
                    c = str(row.get("基金代码", "")).strip()
                    if c:
                        name_map[c] = str(row.get("基金名称", "")) or c
        except Exception as e:
            logger.warning("读取基金列表缓存失败: %s", e)
        name_map.update(self.DEFAULT_FUND_NAMES)
        if codes:
            return {c: name_map.get(c, c) for c in codes}
        return name_map

    def __init__(self, cache_dir=None):
        """初始化基金数据获取器

        Args:
            cache_dir: 缓存目录路径
        """
        self.cache_dir = cache_dir or os.path.join("金水谣数据", "fund", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._ak = None
        self._has_akshare = False

        # 熔断器：akshare连续失败3次后自动熔断60秒
        self._breaker = None
        try:
            from core.circuit_breaker import get_breaker
            self._breaker = get_breaker("fund_akshare", failure_threshold=3, recovery_timeout=60)
        except ImportError:
            pass

        # 尝试加载 akshare
        try:
            import akshare as ak
            self._ak = ak
            self._has_akshare = True
            logger.info("akshare 已加载，可使用真实基金数据")
        except ImportError:
            logger.warning("akshare 未安装，基金数据将使用模拟/缓存模式")

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get_fund_list(self, category=None, use_cache=True):
        """获取基金列表

        Args:
            category: 基金类别筛选，如 "股票型"、"混合型"、"债券型"、"指数型"，None表示全部
            use_cache: 是否使用本地缓存

        Returns:
            DataFrame: 基金列表，列包含 [基金代码, 基金名称, 基金类型, 成立日期]
        """
        cache_key = f"list_{category or 'all'}"

        # 尝试从缓存读取
        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                df = self._fetch_fund_list_from_akshare(category)
                if df is not None and not df.empty:
                    self._record_akshare_success()
                    df = self._standardize_fund_list(df)
                    self._write_cache(cache_key, df)
                    return df
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金列表失败: %s", e)

        # 降级：生成模拟基金列表
        logger.info("使用模拟基金列表数据")
        df = self._generate_mock_fund_list(category)
        if use_cache:
            self._write_cache(cache_key, df)
        return df

    def get_fund_nav(self, fund_code, start=None, end=None, use_cache=True):
        """获取基金历史净值数据

        Args:
            fund_code: 基金代码，如 "000001"
            start: 起始日期 "YYYYMMDD"，None 表示默认近1年
            end: 结束日期 "YYYYMMDD"，None 表示今天
            use_cache: 是否使用本地缓存

        Returns:
            DataFrame: 净值数据，列包含 [净值日期, 单位净值, 累计净值, 日增长率]
        """
        fund_code = str(fund_code).strip()
        cache_key = f"nav_{fund_code}"

        # 尝试从缓存读取
        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                # 如果有日期范围，过滤一下
                if start or end:
                    cached = self._filter_by_date(cached, start, end)
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                df = self._fetch_nav_from_akshare(fund_code, start, end)
                if df is not None and not df.empty:
                    self._record_akshare_success()
                    df = self._standardize_nav(df)
                    self._write_cache(cache_key, df)
                    return df
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金净值失败 %s: %s", fund_code, e)

        # 降级：生成模拟净值数据
        logger.info("使用模拟净值数据: %s", fund_code)
        df = self._generate_mock_nav(fund_code, start, end)
        if use_cache:
            self._write_cache(cache_key, df)
        return df

    def get_fund_info(self, fund_code, use_cache=True):
        """获取基金基本信息

        Args:
            fund_code: 基金代码
            use_cache: 是否使用本地缓存

        Returns:
            dict: 基金信息字典，包含基金名称、基金经理、规模、成立日期、基金类型等
        """
        fund_code = str(fund_code).strip()
        cache_key = f"info_{fund_code}"

        if use_cache:
            cached = self._read_cache(cache_key, as_dataframe=False)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                info = self._fetch_fund_info_from_akshare(fund_code)
                if info:
                    self._record_akshare_success()
                    self._write_cache(cache_key, info, as_dataframe=False)
                    return info
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金信息失败 %s: %s", fund_code, e)

        # 降级：生成模拟基金信息
        logger.info("使用模拟基金信息: %s", fund_code)
        info = self._generate_mock_fund_info(fund_code)
        if use_cache:
            self._write_cache(cache_key, info, as_dataframe=False)
        return info

    def get_rank(self, category=None, use_cache=True):
        """获取基金排名数据

        Args:
            category: 基金类别，如 "股票型"、"混合型" 等，None 表示默认混合型
            use_cache: 是否使用本地缓存

        Returns:
            DataFrame: 排名数据，列包含 [基金代码, 基金名称, 近1月, 近3月, 近6月, 近1年, 近3年, 同类排名]
        """
        cache_key = f"rank_{category or 'default'}"

        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                df = self._fetch_rank_from_akshare(category)
                if df is not None and not df.empty:
                    self._record_akshare_success()
                    df = self._standardize_rank(df)
                    self._write_cache(cache_key, df)
                    return df
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金排名失败: %s", e)

        # 降级：生成模拟排名数据
        logger.info("使用模拟基金排名数据")
        df = self._generate_mock_rank(category)
        if use_cache:
            self._write_cache(cache_key, df)
        return df

    def get_fund_holdings(self, fund_code, use_cache=True):
        """获取基金持仓信息（十大重仓股）

        Args:
            fund_code: 基金代码
            use_cache: 是否使用本地缓存

        Returns:
            DataFrame: 持仓数据，列包含 [股票代码, 股票名称, 占净值比例, 持股数, 持仓市值]
        """
        fund_code = str(fund_code).strip()
        cache_key = f"holdings_{fund_code}"

        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                df = self._fetch_holdings_from_akshare(fund_code)
                if df is not None and not df.empty:
                    self._record_akshare_success()
                    df = self._standardize_holdings(df)
                    self._write_cache(cache_key, df)
                    return df
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金持仓失败 %s: %s", fund_code, e)

        # 降级：生成模拟持仓数据
        logger.info("使用模拟基金持仓数据: %s", fund_code)
        df = self._generate_mock_holdings(fund_code)
        if use_cache:
            self._write_cache(cache_key, df)
        return df

    # ------------------------------------------------------------------
    # akshare 实际数据获取
    # ------------------------------------------------------------------

    def _fetch_fund_list_from_akshare(self, category):
        """从 akshare 获取基金列表"""
        try:
            # akshare 基金开放式列表
            df = self._ak.fund_name_em()
            if df is not None and not df.empty:
                if category and "基金类型" in df.columns:
                    df = df[df["基金类型"].str.contains(category, na=False)]
                return df
        except Exception as e:
            logger.debug("akshare fund_name_em 失败: %s", e)
        return None

    def _fetch_nav_from_akshare(self, fund_code, start, end):
        """从 akshare 获取基金净值"""
        try:
            df = self._ak.fund_open_fund_info_em(
                symbol=fund_code,
                indicator="单位净值走势"
            )
            return df
        except Exception as e:
            logger.debug("akshare fund_open_fund_info_em 失败 %s: %s", fund_code, e)
        return None

    def _fetch_fund_info_from_akshare(self, fund_code):
        """从 akshare 获取基金基本信息"""
        try:
            # 尝试从基金列表中查找
            df = self._ak.fund_name_em()
            match = df[df["基金代码"] == fund_code]
            if not match.empty:
                row = match.iloc[0]
                info = {
                    "基金代码": fund_code,
                    "基金名称": row.get("基金简称", ""),
                    "基金类型": row.get("基金类型", ""),
                    "成立日期": str(row.get("成立日期", "")),
                    "基金经理": "",
                    "基金规模": "",
                    "基金公司": row.get("发行日期", ""),
                }
                return info
        except Exception as e:
            logger.debug("akshare 基金信息获取失败 %s: %s", fund_code, e)
        return None

    def _fetch_rank_from_akshare(self, category):
        """从 akshare 获取基金排名"""
        try:
            # 使用基金排行接口
            df = self._ak.fund_open_fund_rank_em(symbol=category or "全部")
            return df
        except Exception as e:
            logger.debug("akshare 基金排行失败: %s", e)
        return None

    def _fetch_holdings_from_akshare(self, fund_code):
        """从 akshare 获取基金持仓"""
        try:
            df = self._ak.fund_portfolio_hold_em(symbol=fund_code, date="2024")
            return df
        except Exception as e:
            logger.debug("akshare 基金持仓失败 %s: %s", fund_code, e)
        return None

    # ------------------------------------------------------------------
    # 数据标准化
    # ------------------------------------------------------------------

    def _standardize_fund_list(self, df):
        """标准化基金列表列名"""
        import pandas as pd
        col_map = {
            "基金代码": "基金代码",
            "基金简称": "基金名称",
            "基金类型": "基金类型",
            "成立日期": "成立日期",
            "发行日期": "发行日期",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        # 确保必要列存在
        required = ["基金代码", "基金名称"]
        for col in required:
            if col not in df.columns:
                df[col] = ""
        return df

    def _standardize_nav(self, df):
        """标准化净值数据列名"""
        col_map = {
            "净值日期": "净值日期",
            "单位净值": "单位净值",
            "累计净值": "累计净值",
            "日增长率": "日增长率",
            "日期": "净值日期",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        if "净值日期" in df.columns:
            df["净值日期"] = df["净值日期"].astype(str)
        return df

    def _standardize_rank(self, df):
        """标准化排名数据列名"""
        col_map = {
            "基金代码": "基金代码",
            "基金简称": "基金名称",
            "近1周": "近1周",
            "近1月": "近1月",
            "近3月": "近3月",
            "近6月": "近6月",
            "近1年": "近1年",
            "近3年": "近3年",
            "今年来": "今年来",
            "成立来": "成立来",
            "同类排名": "同类排名",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df

    def _standardize_holdings(self, df):
        """标准化持仓数据列名"""
        col_map = {
            "股票代码": "股票代码",
            "股票名称": "股票名称",
            "占净值比例": "占净值比例",
            "持股数（万股）": "持股数",
            "持仓市值（万元）": "持仓市值",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df

    # ------------------------------------------------------------------
    # 模拟数据生成（降级模式）
    # ------------------------------------------------------------------

    def _generate_mock_fund_list(self, category=None):
        """生成模拟基金列表"""
        import pandas as pd

        mock_data = [
            {"基金代码": "000001", "基金名称": "华夏成长混合", "基金类型": "混合型", "成立日期": "2001-12-18"},
            {"基金代码": "110011", "基金名称": "易方达中小盘混合", "基金类型": "混合型", "成立日期": "2008-06-19"},
            {"基金代码": "161725", "基金名称": "招商中证白酒指数", "基金类型": "指数型", "成立日期": "2015-05-27"},
            {"基金代码": "005827", "基金名称": "易方达蓝筹精选混合", "基金类型": "混合型", "成立日期": "2018-09-05"},
            {"基金代码": "001102", "基金名称": "前海开源国家比较优势", "基金类型": "股票型", "成立日期": "2015-05-21"},
            {"基金代码": "519674", "基金名称": "银河创新成长混合", "基金类型": "混合型", "成立日期": "2010-12-29"},
            {"基金代码": "003096", "基金名称": "中欧医疗健康混合", "基金类型": "混合型", "成立日期": "2016-09-29"},
            {"基金代码": "001071", "基金名称": "华安媒体互联网混合", "基金类型": "混合型", "成立日期": "2015-05-21"},
            {"基金代码": "001875", "基金名称": "前海开源沪港深优势精选", "基金类型": "混合型", "成立日期": "2016-04-19"},
            {"基金代码": "260108", "基金名称": "景顺长城新兴成长混合", "基金类型": "混合型", "成立日期": "2009-06-18"},
            {"基金代码": "000961", "基金名称": "天弘沪深300ETF联接A", "基金类型": "指数型", "成立日期": "2015-03-02"},
            {"基金代码": "110022", "基金名称": "易方达消费行业股票", "基金类型": "股票型", "成立日期": "2010-08-20"},
            {"基金代码": "000171", "基金名称": "易方达裕丰回报债券", "基金类型": "债券型", "成立日期": "2013-08-23"},
            {"基金代码": "003547", "基金名称": "鹏华丰禄债券", "基金类型": "债券型", "成立日期": "2016-10-27"},
            {"基金代码": "163406", "基金名称": "兴全合润混合", "基金类型": "混合型", "成立日期": "2010-04-22"},
        ]

        df = pd.DataFrame(mock_data)
        if category:
            df = df[df["基金类型"].str.contains(category.replace("型", ""), na=False)]
            if df.empty:
                df = pd.DataFrame(mock_data[:5])  # 兜底
        return df.reset_index(drop=True)

    def _generate_mock_nav(self, fund_code, start=None, end=None, days=365):
        """生成模拟净值数据"""
        import pandas as pd

        random.seed(hash(fund_code) % (2**32))

        if start:
            start_date = datetime.strptime(start, "%Y%m%d")
        else:
            start_date = datetime.now() - timedelta(days=days)
        if end:
            end_date = datetime.strptime(end, "%Y%m%d")
        else:
            end_date = datetime.now()

        total_days = max(30, (end_date - start_date).days)
        dates = pd.date_range(start=start_date, end=end_date, freq="B")[:total_days]

        # 初始净值根据基金代码生成一个介于1-3之间的基准
        base_nav = 1.0 + (hash(fund_code) % 200) / 100.0
        # 年化收益率设定（5%-25%之间）
        annual_return = 0.05 + (hash(fund_code + "r") % 200) / 1000.0
        # 波动率
        volatility = 0.15 + (hash(fund_code + "v") % 200) / 1000.0

        data = []
        nav = base_nav
        cum_nav = base_nav * 1.5  # 累计净值稍高

        daily_return = annual_return / 252
        daily_vol = volatility / (252 ** 0.5)

        for i, date in enumerate(dates):
            # 几何布朗运动模拟
            shock = random.gauss(daily_return, daily_vol)
            nav = nav * (1 + shock)
            cum_nav = cum_nav * (1 + shock)

            # 日增长率
            prev_nav = data[-1]["单位净值"] if data else base_nav
            daily_growth = (nav - prev_nav) / prev_nav * 100 if prev_nav else 0

            data.append({
                "净值日期": date.strftime("%Y-%m-%d"),
                "单位净值": round(nav, 4),
                "累计净值": round(cum_nav, 4),
                "日增长率": round(daily_growth, 2),
            })

        random.seed()  # 重置随机种子
        return pd.DataFrame(data)

    def _generate_mock_fund_info(self, fund_code):
        """生成模拟基金信息"""
        mock_names = {
            "000001": ("华夏成长混合", "王亚伟", "混合型", 150.5, "2001-12-18"),
            "110011": ("易方达中小盘混合", "张坤", "混合型", 280.3, "2008-06-19"),
            "161725": ("招商中证白酒指数", "侯昊", "指数型", 650.8, "2015-05-27"),
            "005827": ("易方达蓝筹精选混合", "张坤", "混合型", 520.6, "2018-09-05"),
            "001102": ("前海开源国家比较优势", "曲扬", "股票型", 85.2, "2015-05-21"),
            "519674": ("银河创新成长混合", "郑巍山", "混合型", 120.4, "2010-12-29"),
            "003096": ("中欧医疗健康混合", "葛兰", "混合型", 410.7, "2016-09-29"),
            "001071": ("华安媒体互联网混合", "胡宜斌", "混合型", 95.6, "2015-05-21"),
            "001875": ("前海开源沪港深优势精选", "曲扬", "混合型", 65.8, "2016-04-19"),
            "260108": ("景顺长城新兴成长混合", "刘彦春", "混合型", 350.2, "2009-06-18"),
        }

        if fund_code in mock_names:
            name, manager, ftype, scale, found_date = mock_names[fund_code]
        else:
            name = f"基金{fund_code}"
            manager = f"经理{fund_code[-2:]}"
            ftype = "混合型"
            scale = round(50 + (hash(fund_code) % 500), 1)
            found_date = f"20{15 + hash(fund_code) % 9}-01-01"

        return {
            "基金代码": fund_code,
            "基金名称": name,
            "基金经理": manager,
            "基金类型": ftype,
            "基金规模(亿元)": scale,
            "成立日期": found_date,
            "基金公司": f"{name[:2]}基金",
            "业绩比较基准": "沪深300指数收益率×60% + 中债总指数收益率×40%",
        }

    def _generate_mock_rank(self, category=None):
        """生成模拟基金排名数据"""
        import pandas as pd

        funds = [
            ("000001", "华夏成长混合", 2.3, 8.5, 12.1, 18.5, 45.2, 35.6),
            ("110011", "易方达中小盘混合", -1.2, 5.3, 9.8, 15.2, 52.3, 42.1),
            ("161725", "招商中证白酒指数", 3.5, 10.2, -5.6, 8.5, 38.9, 28.4),
            ("005827", "易方达蓝筹精选混合", 1.8, 6.7, 11.3, 22.1, 58.6, 48.2),
            ("001102", "前海开源国家比较优势", -2.5, 4.2, 8.9, 12.3, 35.1, 25.8),
            ("519674", "银河创新成长混合", 4.2, 12.5, 15.6, 28.7, 62.4, 55.3),
            ("003096", "中欧医疗健康混合", -3.1, 2.8, 6.5, 10.2, 32.6, 22.1),
            ("001071", "华安媒体互联网混合", 2.9, 9.1, 13.8, 24.5, 55.7, 46.8),
            ("001875", "前海开源沪港深优势精选", 0.5, 7.3, 10.2, 19.8, 48.3, 38.9),
            ("260108", "景顺长城新兴成长混合", -0.8, 5.9, 8.7, 16.5, 42.1, 36.7),
        ]

        data = []
        for i, (code, name, w1, m1, m3, m6, y1, y3) in enumerate(funds):
            data.append({
                "基金代码": code,
                "基金名称": name,
                "近1周": w1,
                "近1月": m1,
                "近3月": m3,
                "近6月": m6,
                "近1年": y1,
                "近3年": y3,
                "同类排名": f"{i+1}/1500",
            })

        return pd.DataFrame(data)

    def _generate_mock_holdings(self, fund_code):
        """生成模拟基金持仓数据"""
        import pandas as pd

        mock_stocks = [
            ("600519", "贵州茅台", 9.85, 120.5, 58600),
            ("000858", "五粮液", 8.32, 180.2, 32400),
            ("601318", "中国平安", 6.75, 250.3, 18900),
            ("000333", "美的集团", 5.42, 165.8, 16200),
            ("600036", "招商银行", 4.98, 210.6, 11500),
            ("002594", "比亚迪", 4.56, 95.3, 28300),
            ("300750", "宁德时代", 4.21, 88.7, 19800),
            ("601899", "紫金矿业", 3.89, 320.4, 7650),
            ("002415", "海康威视", 3.56, 145.2, 8900),
            ("600900", "长江电力", 3.21, 195.6, 6800),
        ]

        # 根据基金代码打乱顺序
        seed = hash(fund_code) % (2**32)
        rng = random.Random(seed)
        shuffled = mock_stocks[:]
        rng.shuffle(shuffled)

        data = []
        for code, name, ratio, shares, value in shuffled:
            # 随机微调比例
            adjusted = round(ratio * (0.8 + rng.random() * 0.4), 2)
            data.append({
                "股票代码": code,
                "股票名称": name,
                "占净值比例": adjusted,
                "持股数(万股)": shares,
                "持仓市值(万元)": value,
            })

        return pd.DataFrame(data)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _can_use_akshare(self):
        """检查是否可以使用 akshare（熔断器状态）"""
        if self._breaker and not self._breaker.can_execute():
            logger.debug("akshare熔断器已打开，跳过真实数据请求")
            return False
        return self._has_akshare

    def _record_akshare_success(self):
        """记录 akshare 调用成功"""
        if self._breaker:
            self._breaker.record_success()

    def _record_akshare_failure(self):
        """记录 akshare 调用失败"""
        if self._breaker:
            self._breaker.record_failure()

    def _filter_by_date(self, df, start, end):
        """按日期过滤DataFrame"""
        if df is None or df.empty or "净值日期" not in df.columns:
            return df
        try:
            date_col = df["净值日期"]
            mask = pd.Series([True] * len(df), index=df.index)
            if start:
                start_str = datetime.strptime(start, "%Y%m%d").strftime("%Y-%m-%d")
                mask &= date_col >= start_str
            if end:
                end_str = datetime.strptime(end, "%Y%m%d").strftime("%Y-%m-%d")
                mask &= date_col <= end_str
            return df[mask].reset_index(drop=True)
        except Exception:
            return df

    # ------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------

    def _cache_path(self, key):
        """缓存文件路径"""
        return os.path.join(self.cache_dir, f"{key}.json")

    def _read_cache(self, key, as_dataframe=True):
        """从本地缓存读取"""
        import pandas as pd
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        try:
            data = safe_load_json(path, default=None)

            # 检查缓存是否过期（超过1天视为过期，需重新抓取）
            mtime = os.path.getmtime(path)
            if datetime.now().timestamp() - mtime > 86400:
                logger.debug("缓存过期: %s", key)
                return None

            if as_dataframe:
                if isinstance(data, list):
                    return pd.DataFrame(data)
                elif isinstance(data, dict) and "records" in data:
                    return pd.DataFrame(data["records"])
                else:
                    return pd.DataFrame([data])
            else:
                return data if isinstance(data, dict) else data[0] if isinstance(data, list) else None
        except Exception as e:
            logger.warning("缓存读取失败 %s: %s", key, e)
            return None

    def _write_cache(self, key, data, as_dataframe=True):
        """写入本地缓存"""
        path = self._cache_path(key)
        try:
            if as_dataframe and hasattr(data, "to_dict"):
                records = data.to_dict(orient="records")
            elif isinstance(data, dict):
                records = data
            elif isinstance(data, list):
                records = data
            else:
                records = {"value": str(data)}

            safe_write_json(path, records)
        except Exception as e:
            logger.warning("缓存写入失败 %s: %s", key, e)
