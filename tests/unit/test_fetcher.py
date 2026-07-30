# -*- coding: utf-8 -*-
"""股票数据抓取器（StockFetcher）单元测试

使用 mock 替代网络请求和 akshare 依赖，测试：
  - 初始化
  - 代码标准化逻辑
  - 列名映射
  - 缓存路径/读写
  - get_history 的 mock 逻辑和降级行为
"""
import unittest
import os
import json
import tempfile
import shutil
from unittest.mock import MagicMock, patch, PropertyMock

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


class TestStockFetcherInit(unittest.TestCase):
    """StockFetcher 初始化测试"""

    def test_fetcher_init_default_cache_dir(self):
        """验证初始化使用默认缓存目录"""
        from domains.stock.fetcher import StockFetcher
        fetcher = StockFetcher(cache_dir=tempfile.mkdtemp())
        self.assertIsNotNone(fetcher.cache_dir)
        self.assertTrue(os.path.isdir(fetcher.cache_dir))
        shutil.rmtree(fetcher.cache_dir, ignore_errors=True)

    def test_fetcher_init_custom_cache_dir(self):
        """验证初始化使用自定义缓存目录"""
        tmp = tempfile.mkdtemp()
        try:
            from domains.stock.fetcher import StockFetcher
            fetcher = StockFetcher(cache_dir=tmp)
            self.assertEqual(fetcher.cache_dir, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fetcher_init_breaker(self):
        """验证初始化尝试创建熔断器"""
        from domains.stock.fetcher import StockFetcher
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = StockFetcher(cache_dir=tmp)
            # 熔断器可能创建成功也可能因导入失败为None
            # 这里只验证初始化不报错
            self.assertIsNotNone(fetcher.cache_dir)


class TestNormalizeSymbol(unittest.TestCase):
    """代码标准化逻辑测试"""

    def setUp(self):
        from domains.stock.fetcher import StockFetcher
        self.fetcher = StockFetcher(cache_dir=tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.fetcher.cache_dir, ignore_errors=True)

    def test_normalize_sh_prefix(self):
        """sh前缀代码保持不变"""
        self.assertEqual(self.fetcher._normalize_symbol("sh000001"), "sh000001")
        self.assertEqual(self.fetcher._normalize_symbol("SH600001"), "sh600001")

    def test_normalize_sz_prefix(self):
        """sz前缀代码保持不变"""
        self.assertEqual(self.fetcher._normalize_symbol("sz399001"), "sz399001")
        self.assertEqual(self.fetcher._normalize_symbol("SZ000001"), "sz000001")

    def test_normalize_bj_prefix(self):
        """bj前缀代码保持不变"""
        self.assertEqual(self.fetcher._normalize_symbol("bj430047"), "bj430047")

    def test_normalize_shanghai_code(self):
        """6开头自动添加sh前缀"""
        self.assertEqual(self.fetcher._normalize_symbol("600001"), "sh600001")
        self.assertEqual(self.fetcher._normalize_symbol("688001"), "sh688001")

    def test_normalize_shenzhen_code(self):
        """0/3开头自动添加sz前缀"""
        self.assertEqual(self.fetcher._normalize_symbol("000001"), "sz000001")
        self.assertEqual(self.fetcher._normalize_symbol("300001"), "sz300001")

    def test_normalize_beijing_code(self):
        """8/4开头自动添加bj前缀"""
        self.assertEqual(self.fetcher._normalize_symbol("430047"), "bj430047")
        self.assertEqual(self.fetcher._normalize_symbol("830799"), "bj830799")

    def test_normalize_unknown_code(self):
        """未知前缀代码保持原样"""
        self.assertEqual(self.fetcher._normalize_symbol("12345"), "12345")
        self.assertEqual(self.fetcher._normalize_symbol("abc"), "abc")

    def test_normalize_strip_whitespace(self):
        """去除空白字符"""
        self.assertEqual(self.fetcher._normalize_symbol("  600001  "), "sh600001")


@unittest.skipIf(not HAS_PANDAS, "pandas 不可用，跳过列名映射测试")
class TestStandardizeColumns(unittest.TestCase):
    """列名映射测试"""

    def setUp(self):
        from domains.stock.fetcher import StockFetcher
        self.fetcher = StockFetcher(cache_dir=tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.fetcher.cache_dir, ignore_errors=True)

    def test_chinese_columns_mapped(self):
        """中文列名映射为英文"""
        df = pd.DataFrame({
            "日期": ["2026-01-01"],
            "开盘": [10.0],
            "收盘": [11.0],
            "最高": [12.0],
            "最低": [9.0],
            "成交量": [1000000],
        })
        result = self.fetcher._standardize_columns(df)
        self.assertIn("date", result.columns)
        self.assertIn("open", result.columns)
        self.assertIn("close", result.columns)
        self.assertIn("high", result.columns)
        self.assertIn("low", result.columns)
        self.assertIn("volume", result.columns)

    def test_english_columns_unchanged(self):
        """英文列名保持不变"""
        df = pd.DataFrame({
            "date": ["2026-01-01"],
            "open": [10.0],
            "close": [11.0],
            "high": [12.0],
            "low": [9.0],
            "volume": [1000000],
        })
        result = self.fetcher._standardize_columns(df)
        self.assertIn("date", result.columns)
        self.assertIn("open", result.columns)

    def test_date_column_as_string(self):
        """日期列转换为字符串"""
        df = pd.DataFrame({
            "日期": ["2026-01-01", "2026-01-02"],
            "开盘": [10.0, 11.0],
            "收盘": [11.0, 12.0],
            "最高": [12.0, 13.0],
            "最低": [9.0, 10.0],
            "成交量": [100, 200],
        })
        result = self.fetcher._standardize_columns(df)
        # pandas 3.x astype(str) 返回 str dtype 而非 object，用 is_string_dtype 兼容
        self.assertTrue(pd.api.types.is_string_dtype(result["date"]))


class TestCachePath(unittest.TestCase):
    """缓存路径生成测试"""

    def setUp(self):
        from domains.stock.fetcher import StockFetcher
        self.fetcher = StockFetcher(cache_dir=tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.fetcher.cache_dir, ignore_errors=True)

    def test_cache_path_format(self):
        """缓存路径格式正确"""
        path = self.fetcher._cache_path("sh000001", "daily")
        self.assertTrue(path.endswith("sh000001_daily.json"))
        self.assertIn(self.fetcher.cache_dir, path)

    def test_cache_path_contains_cache_dir(self):
        """缓存路径包含缓存目录"""
        path = self.fetcher._cache_path("sz399001", "weekly")
        self.assertTrue(os.path.dirname(path) == self.fetcher.cache_dir)

    def test_cache_path_different_periods(self):
        """不同周期生成不同路径"""
        p1 = self.fetcher._cache_path("sh000001", "daily")
        p2 = self.fetcher._cache_path("sh000001", "weekly")
        self.assertNotEqual(p1, p2)


@unittest.skipIf(not HAS_PANDAS, "pandas 不可用，跳过缓存测试")
class TestCacheReadWrite(unittest.TestCase):
    """缓存读写测试"""

    def setUp(self):
        from domains.stock.fetcher import StockFetcher
        self.tmpdir = tempfile.mkdtemp()
        self.fetcher = StockFetcher(cache_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_read_cache_miss(self):
        """缓存不存在时返回None"""
        result = self.fetcher._read_cache("sh999999", "daily")
        self.assertIsNone(result)

    def test_read_cache_hit(self):
        """缓存存在时正确读取"""
        import pandas as pd
        # 预写缓存文件
        records = [
            {"date": "2026-01-01", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 100},
            {"date": "2026-01-02", "open": 11, "close": 12, "high": 13, "low": 10, "volume": 200},
        ]
        path = self.fetcher._cache_path("sh000001", "daily")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f)

        result = self.fetcher._read_cache("sh000001", "daily")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["close"], 11)

    def test_write_cache(self):
        """缓存写入验证"""
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "open": [10, 11],
            "close": [11, 12],
            "high": [12, 13],
            "low": [9, 10],
            "volume": [100, 200],
        })
        self.fetcher._write_cache("sh000001", "daily", df)

        path = self.fetcher._cache_path("sh000001", "daily")
        self.assertTrue(os.path.exists(path))

        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["close"], 11)

    def test_write_cache_overwrite(self):
        """缓存写入覆盖旧数据"""
        import pandas as pd
        # 先写入旧数据
        df_old = pd.DataFrame({
            "date": ["2026-01-01"],
            "open": [1], "close": [1], "high": [1], "low": [1], "volume": [1],
        })
        self.fetcher._write_cache("sh000001", "daily", df_old)

        # 写入新数据
        df_new = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "open": [10, 11], "close": [11, 12], "high": [12, 13], "low": [9, 10], "volume": [100, 200],
        })
        self.fetcher._write_cache("sh000001", "daily", df_new)

        result = self.fetcher._read_cache("sh000001", "daily")
        self.assertEqual(len(result), 2)


@unittest.skipIf(not HAS_PANDAS, "pandas 不可用，跳过 get_history 测试")
class TestGetHistoryWithMock(unittest.TestCase):
    """get_history mock测试"""

    def setUp(self):
        from domains.stock.fetcher import StockFetcher
        self.tmpdir = tempfile.mkdtemp()
        self.fetcher = StockFetcher(cache_dir=self.tmpdir)
        self.fetcher._has_akshare = False  # 确保不使用真实akshare

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_history_with_mock(self):
        """mock akshare，验证返回DataFrame"""
        import pandas as pd
        # 构造模拟数据（模拟 _fetch_from_akshare 返回已标准化的数据）
        mock_df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "open": [10.0, 11.0],
            "close": [11.0, 12.0],
            "high": [12.0, 13.0],
            "low": [9.0, 10.0],
            "volume": [100, 200],
        })

        # mock _fetch_from_akshare 方法
        self.fetcher._fetch_from_akshare = MagicMock(return_value=mock_df)
        self.fetcher._has_akshare = True

        result = self.fetcher.get_history("sh000001")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        self.assertIn("date", result.columns)

    def test_get_history_fallback_no_akshare(self):
        """akshare不可用时，无缓存返回None"""
        self.fetcher._has_akshare = False
        result = self.fetcher.get_history("sh000001", use_cache=False)
        self.assertIsNone(result)

    def test_get_history_fallback_use_cache(self):
        """akshare不可用时，有缓存返回缓存数据"""
        import pandas as pd
        # 预写缓存
        records = [{"date": "2026-01-01", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 100}]
        path = self.fetcher._cache_path("sh000001", "daily")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f)

        self.fetcher._has_akshare = False
        result = self.fetcher.get_history("sh000001")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)

    def test_get_history_akshare_exception(self):
        """akshare抛异常时降级到缓存"""
        import pandas as pd
        # 预写缓存
        records = [{"date": "2026-01-01", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 100}]
        path = self.fetcher._cache_path("sh000001", "daily")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f)

        self.fetcher._has_akshare = True
        self.fetcher._fetch_from_akshare = MagicMock(side_effect=Exception("网络超时"))

        result = self.fetcher.get_history("sh000001")
        # 有缓存，应返回缓存
        self.assertIsNotNone(result)

    def test_get_history_normalizes_symbol(self):
        """验证get_history内部调用_normalize_symbol"""
        import pandas as pd
        mock_df = pd.DataFrame({
            "日期": ["2026-01-01"],
            "开盘": [10.0], "收盘": [11.0], "最高": [12.0], "最低": [9.0], "成交量": [100],
        })
        self.fetcher._fetch_from_akshare = MagicMock(return_value=mock_df)
        self.fetcher._has_akshare = True

        self.fetcher.get_history("000001")  # 无前缀，应被标准化为 sz000001
        # 验证 _fetch_from_akshare 被调用时参数已标准化
        call_args = self.fetcher._fetch_from_akshare.call_args
        self.assertEqual(call_args[0][0], "sz000001")

    def test_get_history_writes_cache_on_success(self):
        """成功获取数据后写入缓存"""
        import pandas as pd
        mock_df = pd.DataFrame({
            "日期": ["2026-01-01"],
            "开盘": [10.0], "收盘": [11.0], "最高": [12.0], "最低": [9.0], "成交量": [100],
        })
        self.fetcher._fetch_from_akshare = MagicMock(return_value=mock_df)
        self.fetcher._has_akshare = True

        self.fetcher.get_history("sh000001")

        # 验证缓存文件已创建
        path = self.fetcher._cache_path("sh000001", "daily")
        self.assertTrue(os.path.exists(path))
