# -*- coding: utf-8 -*-
"""股票数据获取模块

优先使用 akshare（免费开源A股数据），不可用时提供模拟数据降级。
"""
import os
import json
import logging
from utils.safe_json import safe_load_json, safe_write_json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class StockFetcher:
    """A股数据获取器

    支持数据源：
      - akshare: 免费A股历史/实时数据（首选）
      - 本地缓存: JSON格式历史数据
      - 模拟数据: 降级模式
    """

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or os.path.join("金水谣数据", "stock", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._ak = None
        self._has_akshare = False

        # 熔断器：akshare连续失败3次后自动熔断60秒，期间直接走缓存/模拟
        self._breaker = None
        try:
            from core.circuit_breaker import get_breaker
            self._breaker = get_breaker("stock_akshare", failure_threshold=3, recovery_timeout=60)
        except ImportError:
            pass

        # 尝试加载 akshare
        try:
            import akshare as ak
            self._ak = ak
            self._has_akshare = True
            logger.info("akshare 已加载，可使用真实A股数据")
        except ImportError:
            logger.warning("akshare 未安装，股票数据将使用模拟/缓存模式")

    def get_history(self, symbol, period="daily", start=None, end=None, use_cache=True):
        """获取历史K线数据

        Args:
            symbol: 股票代码，如 "sh000001"（上证）或 "000001"（平安银行）
            period: daily/weekly/monthly
            start: 起始日期 "YYYYMMDD"
            end: 结束日期 "YYYYMMDD"
            use_cache: 是否使用本地缓存

        Returns:
            DataFrame: columns=[date, open, close, high, low, volume]
        """
        # 标准化代码
        symbol = self._normalize_symbol(symbol)

        # 尝试从缓存读取
        if use_cache:
            cached = self._read_cache(symbol, period)
            if cached is not None:
                return cached

        # 尝试从 akshare 获取
        if self._has_akshare:
            # 熔断器保护：连续失败自动熔断
            if self._breaker and not self._breaker.can_execute():
                logger.warning("akshare熔断器已打开，跳过真实数据请求，使用缓存/降级")
                try:
                    from core.audit_log import log_fetch
                    log_fetch("stock", f"akshare_{symbol}", False, 0, fallback=True)
                except Exception:
                    pass
            else:
                try:
                    df = self._fetch_from_akshare(symbol, period, start, end)
                    if df is not None and not df.empty:
                        if self._breaker:
                            self._breaker.record_success()
                        self._write_cache(symbol, period, df)
                        try:
                            from core.audit_log import log_fetch
                            log_fetch("stock", f"akshare_{symbol}", True, len(df))
                        except Exception:
                            pass
                        return df
                    else:
                        if self._breaker:
                            self._breaker.record_failure()
                except Exception as e:
                    if self._breaker:
                        self._breaker.record_failure()
                    logger.warning("akshare获取失败: %s", e)
                    try:
                        from core.audit_log import log_fetch
                        log_fetch("stock", f"akshare_{symbol}", False, 0, fallback=True)
                    except Exception:
                        pass

        # 降级：无数据可用
        logger.warning("无法获取 %s 数据（无akshare且无缓存）", symbol)
        return None

    def get_realtime(self, symbol):
        """获取实时行情（需akshare）"""
        if not self._has_akshare:
            return None
        try:
            # 使用 akshare 实时行情接口
            df = self._ak.stock_zh_a_spot_em()
            # 匹配代码
            match = df[df["代码"] == symbol.replace("sh", "").replace("sz", "")]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "symbol": symbol,
                    "name": row.get("名称", ""),
                    "price": row.get("最新价", 0),
                    "change_pct": row.get("涨跌幅", 0),
                    "volume": row.get("成交量", 0),
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
        except Exception as e:
            logger.error("实时行情获取失败: %s", e)
        return None

    def _normalize_symbol(self, symbol):
        """标准化股票代码"""
        symbol = str(symbol).strip().lower()
        # 如果已经是 sh/sz 前缀，直接返回
        if symbol.startswith(("sh", "sz", "bj")):
            return symbol
        # 6开头 = 上海，0/3开头 = 深圳，8/4开头 = 北京
        if symbol.startswith("6"):
            return f"sh{symbol}"
        elif symbol.startswith(("0", "3")):
            return f"sz{symbol}"
        elif symbol.startswith(("8", "4")):
            return f"bj{symbol}"
        return symbol

    def _fetch_from_akshare(self, symbol, period, start, end):
        """通过 akshare 获取数据"""
        try:
            # 指数数据
            if symbol in ["sh000001", "sz399001", "sh000300"]:
                if symbol == "sh000001":
                    df = self._ak.stock_zh_index_daily(symbol="sh000001")
                elif symbol == "sz399001":
                    df = self._ak.stock_zh_index_daily(symbol="sz399001")
                elif symbol == "sh000300":
                    df = self._ak.stock_zh_index_daily(symbol="sh000300")
            else:
                # 个股数据
                code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
                df = self._ak.stock_zh_a_hist(symbol=code, period=period,
                                               start_date=start or "",
                                               end_date=end or "",
                                               adjust="qfq")

            if df is not None and not df.empty:
                # 统一列名
                df = self._standardize_columns(df)
                return df
        except Exception as e:
            logger.warning("akshare 获取 %s 失败: %s", symbol, e)
        return None

    def _standardize_columns(self, df):
        """统一DataFrame列名 + 转换日期类型"""
        col_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            # 英文列名映射
            "date": "date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "volume": "volume",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        # 确保 date 列是字符串（JSON序列化兼容）
        if "date" in df.columns:
            df["date"] = df["date"].astype(str)
        # 确保必要列存在
        required = ["date", "open", "close", "high", "low", "volume"]
        for col in required:
            if col not in df.columns:
                logger.warning("数据缺少列: %s", col)
        return df

    def _cache_path(self, symbol, period):
        """缓存文件路径"""
        return os.path.join(self.cache_dir, f"{symbol}_{period}.json")

    def _read_cache(self, symbol, period):
        """从本地缓存读取（超过 1 天视为过期，强制重新抓取，债务-205）"""
        path = self._cache_path(symbol, period)
        if not os.path.exists(path):
            return None
        try:
            mtime = os.path.getmtime(path)
            if datetime.now().timestamp() - mtime > 86400:
                logger.info("缓存过期（>1天），重新抓取: %s", symbol)
                return None
            records = safe_load_json(path, default=None)
            if not records:
                return None
            import pandas as pd
            return pd.DataFrame(records)
        except Exception as e:
            logger.warning("缓存读取失败 %s: %s", symbol, e)
            return None

    def _write_cache(self, symbol, period, df):
        """写入本地缓存"""
        path = self._cache_path(symbol, period)
        try:
            records = df.to_dict(orient="records")
            safe_write_json(path, records)
        except Exception as e:
            logger.warning("缓存写入失败 %s: %s", symbol, e)
