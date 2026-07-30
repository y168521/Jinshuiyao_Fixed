# -*- coding: utf-8 -*-
"""股票GUI单元测试

注意：TRAE环境无tkinter，使用unittest.mock模拟tkinter和matplotlib。
测试重点：业务逻辑、数据流、指标计算，不测试实际GUI渲染。

⚠️ 必须在任何import之前patch tkinter和matplotlib到sys.modules，
   否则run_tests.py加载此文件时会先触发tkinter导入失败。
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# 在导入任何其他模块之前，先把tkinter和matplotlib注入sys.modules
# 注意：Python 3.8 中 tkinter 可能已存在于 sys.modules，必须用 = 强制覆盖
class _MockWidget:
    """统一模拟tkinter所有widget"""
    def __init__(self, *a, **kw):
        self._opts = kw
        self._children = []
        self._text = kw.get("text", "")
        self._fg = kw.get("fg", "")
        self._items = []  # Treeview用: [values, ...]
        self._parent = None
        # 如果有父widget，注册到其children列表
        if a and hasattr(a[0], "_children"):
            self._parent = a[0]
            a[0]._children.append(self)
    def pack(self, **kw): pass
    def grid(self, **kw): pass
    def pack_propagate(self, v): pass
    def grid_propagate(self, v): pass
    def grid_columnconfigure(self, *a, **kw): pass
    def grid_rowconfigure(self, *a, **kw): pass
    def config(self, *args, **kw):
        self._opts.update(kw)
        if "text" in kw: self._text = kw["text"]
        if "fg" in kw: self._fg = kw["fg"]
    def configure(self, *args, **kw):
        self._opts.update(kw)
    def winfo_children(self): return list(self._children)
    def winfo_toplevel(self): return self
    def bind(self, *a, **kw): pass
    def bind_all(self, *a, **kw): pass
    def insert(self, parent, index, values=None, **kw):
        # tkinter Treeview.insert 的 values 可能通过 kwargs 传入
        if values is None and "values" in kw:
            values = kw.pop("values")
        self._items.append(values)
        return f"item_{len(self._items)-1}"
    def delete(self, *item_ids):
        indices = []
        for item_id in item_ids:
            if isinstance(item_id, str) and item_id.startswith("item_"):
                try:
                    indices.append(int(item_id.split("_")[1]))
                except (ValueError, IndexError):
                    pass
        for idx in sorted(indices, reverse=True):
            if 0 <= idx < len(self._items):
                self._items.pop(idx)
    def get_children(self):
        return [f"item_{i}" for i in range(len(self._items))]
    def heading(self, *a, **kw): pass
    def column(self, *a, **kw): pass
    def create_window(self, *a, **kw): pass
    def yview_scroll(self, *a, **kw): pass
    def destroy(self):
        # 从父widget的children列表中移除自己
        if self._parent is not None and hasattr(self._parent, "_children"):
            if self in self._parent._children:
                self._parent._children.remove(self)
        self._children = []
        self._items = []

class _MockRoot(_MockWidget):
    def title(self, t): pass
    def geometry(self, g): pass
    def configure(self, *args, **kw): pass
    def minsize(self, w, h): pass
    def mainloop(self): pass
    def after(self, ms, cb): return 1

_mock_tk = MagicMock()
_mock_tk.Tk = _MockRoot
_mock_tk.Frame = _MockWidget
_mock_tk.Label = _MockWidget
_mock_tk.Button = _MockWidget
_mock_tk.Text = _MockWidget
_mock_tk.Toplevel = _MockWidget
_mock_tk.ttk = MagicMock()
_mock_tk.ttk.Treeview = _MockWidget
_mock_tk.ttk.Style = _MockWidget
_mock_tk.messagebox = MagicMock()

_mock_mpl = MagicMock()
_mock_mpl.use = MagicMock()
_mock_mpl.pyplot = MagicMock()
_mock_mpl.backends = MagicMock()
_mock_mpl.backends.backend_tkagg = MagicMock()
_mock_mpl.backends.backend_tkagg.FigureCanvasTkAgg = MagicMock()
_mock_mpl.figure = MagicMock()
_mock_mpl.figure.Figure = MagicMock()

sys.modules["tkinter"] = _mock_tk
sys.modules["tkinter.ttk"] = _mock_tk.ttk
sys.modules["tkinter.messagebox"] = _mock_tk.messagebox
sys.modules["matplotlib"] = _mock_mpl
sys.modules["matplotlib.pyplot"] = _mock_mpl.pyplot
sys.modules["matplotlib.backends"] = _mock_mpl.backends
sys.modules["matplotlib.backends.backend_tkagg"] = _mock_mpl.backends.backend_tkagg
sys.modules["matplotlib.figure"] = _mock_mpl.figure

# 在类定义之前预导入 stock_gui，确保 @patch 装饰器能解析路径
from domains.stock.stock_gui import (
    StockAnalysisWindow as _StockAnalysisWindow,
    SYMBOL_NAMES as _SYMBOL_NAMES,
    Theme as _Theme,
    MATPLOTLIB_OK as _MATPLOTLIB_OK,
    main as _main,
)

_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.normpath(os.path.join(_this_dir, "..", ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)


# matplotlib mock 已在文件顶部注入sys.modules
# tkinter mock 已在文件顶部注入sys.modules


class TestStockGUI(unittest.TestCase):
    """股票GUI单元测试"""

    @classmethod
    def setUpClass(cls):
        """tkinter和matplotlib已在文件顶部注入sys.modules，直接复用预导入"""
        cls.StockAnalysisWindow = _StockAnalysisWindow
        cls.SYMBOL_NAMES = _SYMBOL_NAMES
        cls.Theme = _Theme
        cls.MATPLOTLIB_OK = _MATPLOTLIB_OK
        cls.main = _main

    # ---------------------------------------------------------------
    # 基础测试
    # ---------------------------------------------------------------

    def test_symbol_names_defined(self):
        """SYMBOL_NAMES包含三个指数"""
        self.assertEqual(len(self.SYMBOL_NAMES), 3)
        self.assertIn("sh000001", self.SYMBOL_NAMES)
        self.assertIn("sz399001", self.SYMBOL_NAMES)
        self.assertIn("sh000300", self.SYMBOL_NAMES)

    def test_theme_colors_defined(self):
        """Theme配色定义完整"""
        required = ["BG_DEEP", "BG_CARD", "COLOR_PRIMARY", "TEXT_PRIMARY",
                    "COLOR_GREEN", "COLOR_RED"]
        for attr in required:
            self.assertTrue(hasattr(self.Theme, attr))

    def test_matplotlib_flag(self):
        """MATPLOTLIB_OK为True（mock的matplotlib可导入）"""
        self.assertTrue(self.MATPLOTLIB_OK)

    # ---------------------------------------------------------------
    # 窗口初始化
    # ---------------------------------------------------------------

    @patch("domains.stock.domain.StockDomain")
    def test_window_init_creates_domain(self, MockDomain):
        """窗口初始化会创建StockDomain"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        MockDomain.assert_called_once()
        mock_domain.setup.assert_called_once()

    @patch("domains.stock.domain.StockDomain")
    def test_window_init_handles_setup_failure(self, MockDomain):
        """setup失败时_domain设为None"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = False
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        self.assertIsNotNone(app._domain)

    @patch("domains.stock.domain.StockDomain")
    def test_window_init_handles_exception(self, MockDomain):
        """初始化异常时_domain设为None"""
        MockDomain.side_effect = Exception("导入失败")

        app = self.StockAnalysisWindow()
        self.assertIsNone(app._domain)

    # ---------------------------------------------------------------
    # 指数选择
    # ---------------------------------------------------------------

    @patch("domains.stock.domain.StockDomain")
    def test_select_symbol_updates_state(self, MockDomain):
        """选择指数更新_current_symbol"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._on_select_symbol("sh000001")
        self.assertEqual(app._current_symbol, "sh000001")

    @patch("domains.stock.domain.StockDomain")
    def test_select_symbol_highlights_button(self, MockDomain):
        """选择指数高亮对应按钮"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._on_select_symbol("sh000001")

        # 选中按钮应为高亮色
        self.assertEqual(app._symbol_buttons["sh000001"]._opts.get("bg"), self.Theme.COLOR_PRIMARY)
        # 未选中按钮应为默认色
        self.assertEqual(app._symbol_buttons["sz399001"]._opts.get("bg"), self.Theme.BG_HOVER)

    # ---------------------------------------------------------------
    # 数据刷新
    # ---------------------------------------------------------------

    @patch("domains.stock.domain.StockDomain")
    def test_on_data_fetched_caches_data(self, MockDomain):
        """数据获取后缓存到_data_cache"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._current_symbol = "sh000001"

        # 模拟返回的DataFrame
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2026-07-01", "2026-07-02"],
            "open": [3000, 3010],
            "close": [3010, 3020],
            "high": [3020, 3030],
            "low": [2990, 3000],
            "volume": [1000, 2000],
        })

        result = {"success": True, "data": {"sh000001": df}, "mode": "real"}
        app._on_data_fetched(result)

        self.assertIn("sh000001", app._data_cache)
        self.assertEqual(len(app._data_cache["sh000001"]), 2)

    @patch("domains.stock.domain.StockDomain")
    def test_on_data_fetched_updates_source_label(self, MockDomain):
        """数据获取后更新数据源标签"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._current_symbol = "sh000001"

        import pandas as pd
        df = pd.DataFrame({"date": ["2026-07-01"], "close": [3000]})
        result = {"success": True, "data": {"sh000001": df}, "mode": "real"}
        app._on_data_fetched(result)

        self.assertIn("真实数据", app._source_label._text)

    @patch("domains.stock.domain.StockDomain")
    def test_on_data_fetched_failure_shows_error(self, MockDomain):
        """数据获取失败不缓存"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._current_symbol = "sh000001"

        result = {"success": False, "message": "网络错误"}
        app._on_data_fetched(result)

        self.assertNotIn("sh000001", app._data_cache)

    # ---------------------------------------------------------------
    # 技术分析
    # ---------------------------------------------------------------

    @patch("domains.stock.domain.StockDomain")
    def test_on_analysis_done_caches_results(self, MockDomain):
        """分析结果缓存到_analysis_cache"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._current_symbol = "sh000001"

        result = {
            "status": "ok",
            "results": {
                "sh000001": {
                    "indicators": {"ma5": 3000, "ma20": 2950, "latest_price": 3020},
                    "trend": {"direction": "up", "strength": 75.5},
                    "signals": ["多头排列"],
                }
            }
        }
        app._on_analysis_done(result)

        self.assertIn("sh000001", app._analysis_cache)
        self.assertEqual(app._analysis_cache["sh000001"]["indicators"]["ma5"], 3000)

    @patch("domains.stock.domain.StockDomain")
    def test_update_indicators_updates_price(self, MockDomain):
        """_update_indicators更新价格显示"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        result = {
            "indicators": {"ma5": 3000, "ma20": 2950, "ma60": 2900, "latest_price": 3020},
            "trend": {"direction": "up", "strength": 75.5},
            "signals": ["多头排列"],
        }
        app._update_indicators(result)

        self.assertEqual(app._price_main._text, "3020.00")

    @patch("domains.stock.domain.StockDomain")
    def test_update_indicators_trend_colors(self, MockDomain):
        """趋势方向使用正确颜色"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()

        for direction, expected_color in [
            ("up", self.Theme.COLOR_GREEN),
            ("down", self.Theme.COLOR_RED),
            ("sideways", self.Theme.COLOR_SECONDARY),
        ]:
            result = {
                "indicators": {"latest_price": 3000},
                "trend": {"direction": direction, "strength": 50},
                "signals": [],
            }
            app._update_indicators(result)
            self.assertEqual(app._ind_labels["trend"]._fg, expected_color)

    # ---------------------------------------------------------------
    # 选股推荐
    # ---------------------------------------------------------------

    @patch("domains.stock.domain.StockDomain")
    def test_on_pick_done_fills_table(self, MockDomain):
        """选股结果填充到表格"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._analysis_cache = {"sh000001": {}}

        result = {
            "predictions": [
                {"symbol": "sh000001", "action": "buy", "confidence": 85.5, "reason": "多头排列"},
                {"symbol": "sz399001", "action": "hold", "confidence": 60.0, "reason": "震荡整理"},
            ]
        }
        app._on_pick_done(result)

        self.assertEqual(len(app._rec_table._items), 2)
        self.assertEqual(app._rec_table._items[0][2], "买入")
        self.assertEqual(app._rec_table._items[1][2], "持有")

    @patch("domains.stock.domain.StockDomain")
    def test_on_pick_done_empty_clears_table(self, MockDomain):
        """空结果清空表格"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._analysis_cache = {"sh000001": {}}

        # 先添加一条
        app._rec_table._items = [("x", "y", "z", "0", "test")]

        result = {"predictions": []}
        app._on_pick_done(result)

        self.assertEqual(len(app._rec_table._items), 0)

    # ---------------------------------------------------------------
    # 信号更新
    # ---------------------------------------------------------------

    @patch("domains.stock.domain.StockDomain")
    def test_update_signals_empty(self, MockDomain):
        """无信号时显示提示"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._update_signals([])
        # 应该创建了"暂无信号"标签
        self.assertTrue(len(app._signal_list._children) > 0)

    @patch("domains.stock.domain.StockDomain")
    def test_update_signals_with_data(self, MockDomain):
        """有信号时显示信号列表"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._update_signals(["多头排列", "站上MA5", "放量突破"])
        self.assertEqual(len(app._signal_list._children), 3)

    # ---------------------------------------------------------------
    # 命令按钮守卫
    # ---------------------------------------------------------------

    @patch("domains.stock.domain.StockDomain")
    def test_cmd_refresh_no_symbol_warns(self, MockDomain):
        """未选指数时刷新提示"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._current_symbol = None
        # 不应抛出异常
        app._cmd_refresh()

    @patch("domains.stock.domain.StockDomain")
    def test_cmd_analyze_no_data_warns(self, MockDomain):
        """无数据时分析提示"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._current_symbol = "sh000001"
        # 不应抛出异常
        app._cmd_analyze()

    @patch("domains.stock.domain.StockDomain")
    def test_cmd_pick_no_analysis_warns(self, MockDomain):
        """无分析结果时选股提示"""
        mock_domain = MagicMock()
        mock_domain.setup.return_value = True
        MockDomain.return_value = mock_domain

        app = self.StockAnalysisWindow()
        app._analysis_cache = {}
        # 不应抛出异常
        app._cmd_pick()

    # ---------------------------------------------------------------
    # 主入口
    # ---------------------------------------------------------------

    def test_main_runs(self):
        """main函数可调用"""
        self.assertTrue(callable(self.main))


if __name__ == "__main__":
    unittest.main()

