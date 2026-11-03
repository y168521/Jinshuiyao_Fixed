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
import logging
from datetime import datetime

# 缓存层与来源标记拆到 domains/fund/fund_cache.py（JS-20261021-04，与 fund_mock.py
# 同一路拆包）：本文件只负责"取数"，落盘/读盘的规矩集中在缓存层。
# SOURCE_* 在这里转手给上层，唯一真源是 fund_cache.py。
from domains.fund.fund_cache import (
    FundCache, SOURCE_REAL, SOURCE_MOCK, SOURCE_UNKNOWN,
)
from domains.fund.fund_standardize import (
    standardize_fund_list, standardize_nav, standardize_rank, standardize_holdings,
)

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
            cached = self._read_cache("list_all", source_key=("list", ""))
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
        self._cache = FundCache(self.cache_dir)
        self._ak = None
        self._has_akshare = False
        # 最近一次取数的来源标记 {(kind, code): real/mock/unknown}
        # kind: list / nav / info / holdings / rank；上层用 get_source() 读
        self._source = {}

        # 熔断器：akshare连续失败3次后自动熔断60秒
        self._breaker = None
        try:
            from core.infra.circuit_breaker import get_breaker
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

    def get_source(self, kind, code=""):
        """查询某类数据最近一次取数的来源（JS-20261021-04）

        Args:
            kind: "list" | "nav" | "info" | "holdings" | "rank"
            code: 基金代码（list/rank 可传 None 或分类名）

        Returns:
            "real" | "mock" | "unknown"
        """
        return self._source.get((kind, str(code) if code is not None else ""), SOURCE_UNKNOWN)

    def get_fund_list(self, category=None, use_cache=True, real_only=False):
        """获取基金列表

        Args:
            category: 基金类别筛选，如 "股票型"、"混合型"、"债券型"、"指数型"，None表示全部
            use_cache: 是否使用本地缓存
            real_only: 仅返回真实数据。为 True 时，若 akshare 不可用/失败，
                直接返回 None 而非模拟列表（诚实铁律，与 get_rank 口径一致）

        Returns:
            DataFrame: 基金列表，列包含 [基金代码, 基金名称, 基金类型, 成立日期]
        """
        cache_key = f"list_{category or 'all'}"
        source_key = ("list", category or "")

        # 尝试从缓存读取
        if use_cache:
            cached = self._read_cache(cache_key, source_key=source_key)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                df = self._fetch_fund_list_from_akshare(category)
                if df is not None and not df.empty:
                    self._record_akshare_success()
                    df = self._standardize_fund_list(df)
                    self._source[source_key] = SOURCE_REAL
                    self._write_cache(cache_key, df, source=SOURCE_REAL)
                    return df
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金列表失败: %s", e)

        # 真实数据不可用
        if real_only:
            logger.info("真实基金列表不可用，返回 None（不编造模拟列表）")
            return None

        # 降级：生成模拟基金列表（JS-20261021-04：模拟数据永不写缓存）
        logger.info("使用模拟基金列表数据")
        df = self._generate_mock_fund_list(category)
        self._source[source_key] = SOURCE_MOCK
        return df

    def get_fund_nav(self, fund_code, start=None, end=None, use_cache=True, real_only=False):
        """获取基金历史净值数据

        Args:
            fund_code: 基金代码，如 "000001"
            start: 起始日期 "YYYYMMDD"，None 表示默认近1年
            end: 结束日期 "YYYYMMDD"，None 表示今天
            use_cache: 是否使用本地缓存
            real_only: 仅返回真实数据。为 True 时，若 akshare 不可用/失败，
                直接返回 None 而非模拟净值（诚实铁律，与 get_rank 口径一致）

        Returns:
            DataFrame: 净值数据，列包含 [净值日期, 单位净值, 累计净值, 日增长率]
        """
        fund_code = str(fund_code).strip()
        cache_key = f"nav_{fund_code}"
        source_key = ("nav", fund_code)

        # 尝试从缓存读取
        if use_cache:
            cached = self._read_cache(cache_key, source_key=source_key)
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
                    self._source[source_key] = SOURCE_REAL
                    self._write_cache(cache_key, df, source=SOURCE_REAL)
                    return df
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金净值失败 %s: %s", fund_code, e)

        # 真实数据不可用
        if real_only:
            logger.info("真实基金净值不可用，返回 None（不编造模拟净值）: %s", fund_code)
            return None

        # 降级：生成模拟净值数据（JS-20261021-04：模拟数据永不写缓存）
        logger.info("使用模拟净值数据: %s", fund_code)
        df = self._generate_mock_nav(fund_code, start, end)
        self._source[source_key] = SOURCE_MOCK
        return df

    def get_fund_info(self, fund_code, use_cache=True, real_only=False):
        """获取基金基本信息

        Args:
            fund_code: 基金代码
            use_cache: 是否使用本地缓存
            real_only: 仅返回真实数据。为 True 时，若 akshare 不可用/失败，
                直接返回 None 而非模拟信息（诚实铁律，与 get_rank 口径一致）

        Returns:
            dict: 基金信息字典，包含基金名称、基金经理、规模、成立日期、基金类型等
        """
        fund_code = str(fund_code).strip()
        cache_key = f"info_{fund_code}"
        source_key = ("info", fund_code)

        if use_cache:
            cached = self._read_cache(cache_key, as_dataframe=False, source_key=source_key)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                info = self._fetch_fund_info_from_akshare(fund_code)
                if info:
                    self._record_akshare_success()
                    self._source[source_key] = SOURCE_REAL
                    self._write_cache(cache_key, info, as_dataframe=False, source=SOURCE_REAL)
                    return info
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金信息失败 %s: %s", fund_code, e)

        # 真实数据不可用
        if real_only:
            logger.info("真实基金信息不可用，返回 None（不编造模拟信息）: %s", fund_code)
            return None

        # 降级：生成模拟基金信息（JS-20261021-04：模拟数据永不写缓存）
        logger.info("使用模拟基金信息: %s", fund_code)
        info = self._generate_mock_fund_info(fund_code)
        self._source[source_key] = SOURCE_MOCK
        return info

    def get_rank(self, category=None, use_cache=True, real_only=False):
        """获取基金排名数据

        Args:
            category: 基金类别，如 "股票型"、"混合型" 等，None 表示默认混合型
            use_cache: 是否使用本地缓存
            real_only: 仅返回真实数据。为 True 时，若 akshare 不可用/失败，
                直接返回 None 而非模拟排名（避免日报编造排名，违背诚实铁律）

        Returns:
            DataFrame: 排名数据，列包含 [基金代码, 基金名称, 近1月, 近3月, 近6月, 近1年, 近3年, 同类排名]
            若 real_only=True 且真实数据不可用，返回 None
        """
        cache_key = f"rank_{category or 'default'}"
        source_key = ("rank", category or "")

        # real_only 时不读缓存：缓存可能是旧的次级/模拟数据，绝不能冒充当真实排名返回
        if use_cache and not real_only:
            cached = self._read_cache(cache_key, source_key=source_key)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                df = self._fetch_rank_from_akshare(category)
                if df is not None and not df.empty:
                    self._record_akshare_success()
                    df = self._standardize_rank(df)
                    self._source[source_key] = SOURCE_REAL
                    self._write_cache(cache_key, df, source=SOURCE_REAL)
                    return df
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金排名失败: %s", e)

        # 真实数据不可用
        if real_only:
            logger.info("真实基金排名数据不可用，返回 None（不编造模拟排名）")
            return None

        # 降级：生成模拟排名数据（JS-20261021-04：模拟数据永不写缓存）
        logger.info("使用模拟基金排名数据")
        df = self._generate_mock_rank(category)
        self._source[source_key] = SOURCE_MOCK
        return df

    def get_fund_holdings(self, fund_code, use_cache=True, real_only=False):
        """获取基金持仓信息（十大重仓股）

        Args:
            fund_code: 基金代码
            use_cache: 是否使用本地缓存
            real_only: 仅返回真实数据。为 True 时，若 akshare 不可用/失败，
                直接返回 None 而非模拟持仓（诚实铁律，与 get_rank 口径一致）

        Returns:
            DataFrame: 持仓数据，列包含 [股票代码, 股票名称, 占净值比例, 持股数, 持仓市值]
        """
        fund_code = str(fund_code).strip()
        cache_key = f"holdings_{fund_code}"
        source_key = ("holdings", fund_code)

        if use_cache:
            cached = self._read_cache(cache_key, source_key=source_key)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare and self._can_use_akshare():
            try:
                df = self._fetch_holdings_from_akshare(fund_code)
                if df is not None and not df.empty:
                    self._record_akshare_success()
                    df = self._standardize_holdings(df)
                    self._source[source_key] = SOURCE_REAL
                    self._write_cache(cache_key, df, source=SOURCE_REAL)
                    return df
                else:
                    self._record_akshare_failure()
            except Exception as e:
                self._record_akshare_failure()
                logger.warning("akshare获取基金持仓失败 %s: %s", fund_code, e)

        # 真实数据不可用
        if real_only:
            logger.info("真实基金持仓不可用，返回 None（不编造模拟持仓）: %s", fund_code)
            return None

        # 降级：生成模拟持仓数据（JS-20261021-04：模拟数据永不写缓存）
        logger.info("使用模拟基金持仓数据: %s", fund_code)
        df = self._generate_mock_holdings(fund_code)
        self._source[source_key] = SOURCE_MOCK
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
                    "基金公司": str(row.get("基金公司", "")),
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
    # 数据标准化：列名映射拆到 domains/fund/fund_standardize.py
    # （JS-20261021-04，与 fund_mock.py / fund_cache.py 同一路拆包）
    # ------------------------------------------------------------------

    def _standardize_fund_list(self, df):
        return standardize_fund_list(df)

    def _standardize_nav(self, df):
        return standardize_nav(df)

    def _standardize_rank(self, df):
        return standardize_rank(df)

    def _standardize_holdings(self, df):
        return standardize_holdings(df)

    # ------------------------------------------------------------------
    # 模拟数据生成（降级模式）
    # ------------------------------------------------------------------

    # mock 数据生成委托给 domains.fund.fund_mock 模块（JS-20260924-28 拆包降复杂度）
    def _generate_mock_fund_list(self, category=None):
        from domains.fund.fund_mock import generate_mock_fund_list
        return generate_mock_fund_list(category)

    def _generate_mock_nav(self, fund_code, start=None, end=None, days=365):
        from domains.fund.fund_mock import generate_mock_nav
        return generate_mock_nav(fund_code, start, end, days)

    def _generate_mock_fund_info(self, fund_code):
        from domains.fund.fund_mock import generate_mock_fund_info
        return generate_mock_fund_info(fund_code)

    def _generate_mock_rank(self, category=None):
        from domains.fund.fund_mock import generate_mock_rank
        return generate_mock_rank(category)

    def _generate_mock_holdings(self, fund_code):
        from domains.fund.fund_mock import generate_mock_holdings
        return generate_mock_holdings(fund_code)

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
        """按日期过滤DataFrame

        JS-20261021-04（P1-12）：原实现里 `pd` 从没在模块作用域导入过
        （只在 _read_cache / _standardize_* 等函数内 import），一进这个函数就
        NameError，又被下面的 `except Exception: return df` 吞掉 ——
        用户按日期区间取数，拿回来的却是**全量历史**，而且一声不响。
        现在：①pd 提到本函数开头导入（放在 try 外，导入失败要照实炸出来，
        不能冒充"过滤失败"）；②过滤失败一律打 warning，明确告知返回的是
        未过滤数据，不许静默。
        """
        if df is None or df.empty or "净值日期" not in df.columns:
            return df
        import pandas as pd  # 局部导入：与 _read_cache 保持一致，模块顶层不强依赖 pandas
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
        except Exception as e:
            logger.warning(
                "基金净值日期过滤失败(start=%s, end=%s): %s —— 返回的是未过滤的全量数据，"
                "请确认日期格式应为 YYYYMMDD", start, end, e)
            return df

    # ------------------------------------------------------------------
    # 缓存管理（薄委托：规矩都在 domains/fund/fund_cache.py，JS-20261021-04 拆出）
    # ------------------------------------------------------------------

    def _cache_path(self, key):
        """缓存文件路径"""
        return self._cache.path(key)

    def _read_cache(self, key, as_dataframe=True, source_key=None):
        """从本地缓存读取，并把来源标记记到 self._source（source_key 形如 ("nav","000001")）

        未命中 / 已过期 / 旧格式无来源标记，一律返回 None（旧格式按未命中处理，
        它很可能是修复前写入的模拟数据，不能冒充当真实数据返回）。
        """
        data, source = self._cache.read(key, as_dataframe=as_dataframe)
        if data is None:
            return None
        if source_key is not None:
            self._source[source_key] = source
        return data

    def _write_cache(self, key, data, as_dataframe=True, source=SOURCE_REAL):
        """写入本地缓存：只有真实数据才准落盘（模拟数据落盘即被当成真实数据用）"""
        self._cache.write(key, data, as_dataframe=as_dataframe, source=source)
