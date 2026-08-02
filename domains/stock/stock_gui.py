# -*- coding: utf-8 -*-
"""金水谣股票分析系统 - 独立GUI窗口

功能：
  - 三大指数实时行情看板（上证/深证/沪深300）
  - K线图 + 成交量（matplotlib嵌入tkinter）
  - 技术指标面板（MA5/MA20/MA60 + 趋势方向 + 交易信号）
  - 选股推荐列表（评分排序 + 买卖信号 + 置信度）
  - 数据状态指示（akshare/模拟/缓存 + 熔断器状态）
  - 一键数据真实性检测

数据源：优先akshare真实数据，不可用时自动降级模拟数据
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

# -----------------------------------------------------------------------
# 导入路径处理
# -----------------------------------------------------------------------
_this_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.normpath(os.path.join(_this_dir, "..", ".."))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from core.theme import Theme


def _as_float(v, default=0.0):
    """统一把任意类型转 float，避免缓存里 confidence 为字符串时 f-string 报 'Unknown format code'。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

# -----------------------------------------------------------------------
# matplotlib 配置（必须在创建Figure之前）
# -----------------------------------------------------------------------
MATPLOTLIB_OK = False
try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    MATPLOTLIB_OK = True
except Exception as e:
    print(f"[WARN] matplotlib 不可用: {e}")

# -----------------------------------------------------------------------
# 符号名称映射
# -----------------------------------------------------------------------
SYMBOL_NAMES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sh000300": "沪深300",
}


# =======================================================================
# 股票分析主窗口
# =======================================================================
class StockAnalysisWindow:
    """金水谣股票分析系统主窗口"""

    def __init__(self, master=None):
        self.root = master or tk.Tk()
        self.root.title("金水谣股票分析系统")
        self.root.geometry("1400x900")
        self.root.configure(bg=Theme.BG_DEEP)
        self.root.minsize(1200, 700)

        # 业务层
        self._domain = None
        self._current_symbol = None
        self._data_cache = {}      # {symbol: df}
        self._analysis_cache = {}  # {symbol: result}

        # 初始化股票域
        self._init_domain()

        # 构建UI
        self._build_ui()

        # 启动时自动刷新数据
        self.root.after(500, self._auto_refresh)

    # ---------------------------------------------------------------
    # 业务初始化
    # ---------------------------------------------------------------

    def _init_domain(self):
        """初始化StockDomain"""
        try:
            from domains.stock.domain import StockDomain
            self._domain = StockDomain()
            ok = self._domain.setup()
            if not ok:
                print("[WARN] StockDomain.setup() 返回False")
        except Exception as e:
            print(f"[ERR] 股票子系统初始化失败: {e}")
            self._domain = None

    # ---------------------------------------------------------------
    # UI构建
    # ---------------------------------------------------------------

    def _build_ui(self):
        """构建主界面"""
        # 顶部标题栏
        self._build_header()

        # 主体三栏布局
        main_frame = tk.Frame(self.root, bg=Theme.BG_DEEP)
        main_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        main_frame.grid_columnconfigure(0, weight=0, minsize=220)
        main_frame.grid_columnconfigure(1, weight=3, minsize=600)
        main_frame.grid_columnconfigure(2, weight=0, minsize=260)
        main_frame.grid_rowconfigure(0, weight=1)

        # 左栏：指数列表 + 状态
        self._build_left_panel(main_frame)

        # 中栏：K线图
        self._build_chart_panel(main_frame)

        # 右栏：技术指标
        self._build_right_panel(main_frame)

        # 底部：选股推荐 + 操作按钮
        self._build_bottom_panel()

    def _build_header(self):
        """顶部标题栏"""
        header = tk.Frame(self.root, bg=Theme.BG_CARD, height=50)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        tk.Label(header, text="金水谣股票分析系统",
                 font=(Theme.FONT_FAMILY, 16, "bold"),
                 fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(side="left", padx=20, pady=8)

        # 数据源状态指示
        self._source_label = tk.Label(header, text="数据源: 初始化中...",
                                      font=(Theme.FONT_FAMILY, 10),
                                      fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        self._source_label.pack(side="right", padx=20)

        # 当前时间
        self._time_label = tk.Label(header,
                                    font=(Theme.FONT_FAMILY, 10),
                                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self._time_label.pack(side="right", padx=10)
        self._update_clock()

    def _update_clock(self):
        """更新时钟"""
        self._time_label.config(text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.root.after(1000, self._update_clock)

    def _build_left_panel(self, parent):
        """左栏：指数列表 + 数据状态"""
        left = tk.Frame(parent, bg=Theme.BG_DEEP, width=220)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_propagate(False)

        # --- 指数列表 ---
        list_frame = tk.Frame(left, bg=Theme.BG_CARD, padx=10, pady=10)
        list_frame.pack(fill="x", pady=(0, 10))

        tk.Label(list_frame, text="关注指数",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        self._symbol_buttons = {}
        for sym, name in SYMBOL_NAMES.items():
            btn = tk.Button(list_frame, text=f"{name}\n({sym})",
                            font=(Theme.FONT_FAMILY, 10),
                            fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                            activebackground=Theme.COLOR_PRIMARY,
                            activeforeground=Theme.BG_DEEP,
                            relief="flat", cursor="hand2",
                            command=lambda s=sym: self._on_select_symbol(s))
            btn.pack(fill="x", pady=(0, 6))
            self._symbol_buttons[sym] = btn

        # --- 数据状态面板 ---
        status_frame = tk.Frame(left, bg=Theme.BG_CARD, padx=10, pady=10)
        status_frame.pack(fill="x", pady=(0, 10))

        tk.Label(status_frame, text="数据状态",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        self._status_labels = {}
        status_items = [
            ("akshare", "akshare数据源"),
            ("breaker", "熔断器状态"),
            ("cache", "本地缓存"),
            ("mode", "当前模式"),
        ]
        for key, label in status_items:
            row = tk.Frame(status_frame, bg=Theme.BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"● {label}:",
                     font=(Theme.FONT_FAMILY, 9),
                     fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD).pack(side="left")
            lbl = tk.Label(row, text="检测中",
                           font=(Theme.FONT_FAMILY, 9),
                           fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
            lbl.pack(side="right")
            self._status_labels[key] = lbl

    def _build_chart_panel(self, parent):
        """中栏：K线图"""
        chart_frame = tk.Frame(parent, bg=Theme.BG_CARD)
        chart_frame.grid(row=0, column=1, sticky="nsew")

        # 图表标题
        self._chart_title = tk.Label(chart_frame, text="请选择指数",
                                     font=(Theme.FONT_FAMILY, 13, "bold"),
                                     fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD)
        self._chart_title.pack(anchor="w", padx=15, pady=10)

        # matplotlib 画布
        if MATPLOTLIB_OK:
            self._fig = Figure(figsize=(8, 5.5), dpi=100, facecolor=Theme.BG_CARD)
            self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
            self._canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0, 10))
        else:
            self._fig = None
            self._canvas = None
            tk.Label(chart_frame, text="matplotlib 未安装，无法显示图表\n请执行: pip install matplotlib",
                     font=(Theme.FONT_FAMILY, 12),
                     fg=Theme.COLOR_RED, bg=Theme.BG_CARD).pack(expand=True)

    def _build_right_panel(self, parent):
        """右栏：技术指标面板"""
        right = tk.Frame(parent, bg=Theme.BG_DEEP, width=260)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        right.grid_propagate(False)

        # --- 价格信息 ---
        price_frame = tk.Frame(right, bg=Theme.BG_CARD, padx=12, pady=12)
        price_frame.pack(fill="x", pady=(0, 10))

        tk.Label(price_frame, text="最新行情",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        self._price_main = tk.Label(price_frame, text="--",
                                    font=(Theme.FONT_FAMILY, 28, "bold"),
                                    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD)
        self._price_main.pack(anchor="w")

        self._price_change = tk.Label(price_frame, text="--",
                                      font=(Theme.FONT_FAMILY, 12),
                                      fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self._price_change.pack(anchor="w", pady=(4, 0))

        # --- 技术指标 ---
        ind_frame = tk.Frame(right, bg=Theme.BG_CARD, padx=12, pady=12)
        ind_frame.pack(fill="x", pady=(0, 10), expand=True)

        tk.Label(ind_frame, text="技术指标",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        self._ind_labels = {}
        ind_items = [
            ("ma5", "MA5"),
            ("ma20", "MA20"),
            ("ma60", "MA60"),
            ("trend", "趋势方向"),
            ("strength", "趋势强度"),
        ]
        for key, label in ind_items:
            row = tk.Frame(ind_frame, bg=Theme.BG_CARD)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=f"{label}:",
                     font=(Theme.FONT_FAMILY, 10),
                     fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD).pack(side="left")
            lbl = tk.Label(row, text="--",
                           font=(Theme.FONT_FAMILY, 10, "bold"),
                           fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
            lbl.pack(side="right")
            self._ind_labels[key] = lbl

        # --- 交易信号 ---
        signal_frame = tk.Frame(right, bg=Theme.BG_CARD, padx=12, pady=12)
        signal_frame.pack(fill="x", pady=(0, 10))

        tk.Label(signal_frame, text="交易信号",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        self._signal_list = tk.Frame(signal_frame, bg=Theme.BG_CARD)
        self._signal_list.pack(fill="x")

        # 默认显示无信号
        self._update_signals([])

    def _build_bottom_panel(self):
        """底部：选股推荐 + 操作按钮"""
        bottom = tk.Frame(self.root, bg=Theme.BG_DEEP, height=200)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        bottom.pack_propagate(False)

        # 上部分：选股推荐表格
        rec_frame = tk.Frame(bottom, bg=Theme.BG_CARD, padx=10, pady=8)
        rec_frame.pack(fill="both", expand=True, pady=(0, 8))

        tk.Label(rec_frame, text="选股推荐",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w")

        # Treeview表格
        columns = ("symbol", "name", "action", "confidence", "reason")
        self._rec_table = ttk.Treeview(rec_frame, columns=columns,
                                        show="headings", height=4)
        self._rec_table.heading("symbol", text="代码")
        self._rec_table.heading("name", text="名称")
        self._rec_table.heading("action", text="操作建议")
        self._rec_table.heading("confidence", text="置信度")
        self._rec_table.heading("reason", text="分析理由")

        self._rec_table.column("symbol", width=100, anchor="center")
        self._rec_table.column("name", width=120, anchor="center")
        self._rec_table.column("action", width=80, anchor="center")
        self._rec_table.column("confidence", width=80, anchor="center")
        self._rec_table.column("reason", width=500, anchor="w")

        # 样式
        style = ttk.Style()
        style.configure("Treeview",
                        background=Theme.BG_CARD,
                        foreground=Theme.TEXT_PRIMARY,
                        fieldbackground=Theme.BG_CARD,
                        rowheight=26)
        style.configure("Treeview.Heading",
                        background=Theme.BG_HOVER,
                        foreground=Theme.TEXT_PRIMARY,
                        font=(Theme.FONT_FAMILY, 10, "bold"))

        self._rec_table.pack(fill="both", expand=True, pady=(8, 0))

        # 下部分：操作按钮
        btn_frame = tk.Frame(bottom, bg=Theme.BG_DEEP)
        btn_frame.pack(fill="x")

        buttons = [
            ("刷新数据", self._cmd_refresh, Theme.COLOR_PRIMARY),
            ("技术分析", self._cmd_analyze, Theme.COLOR_SECONDARY),
            ("选股推荐", self._cmd_pick, Theme.COLOR_ACCENT),
            ("数据真实性检测", self._cmd_truth_check, Theme.COLOR_PURPLE),
        ]
        for text, cmd, color in buttons:
            btn = tk.Button(btn_frame, text=text,
                            font=(Theme.FONT_FAMILY, 11, "bold"),
                            fg=Theme.BG_DEEP, bg=color,
                            activebackground=color,
                            activeforeground=Theme.BG_DEEP,
                            relief="flat", padx=20, pady=8,
                            cursor="hand2", command=cmd)
            btn.pack(side="left", padx=(0, 10))

    # ---------------------------------------------------------------
    # 事件处理
    # ---------------------------------------------------------------

    def _on_select_symbol(self, symbol):
        """选择指数"""
        self._current_symbol = symbol

        # 更新按钮高亮
        for sym, btn in self._symbol_buttons.items():
            if sym == symbol:
                btn.config(bg=Theme.COLOR_PRIMARY, fg=Theme.BG_DEEP)
            else:
                btn.config(bg=Theme.BG_HOVER, fg=Theme.TEXT_SECONDARY)

        name = SYMBOL_NAMES.get(symbol, symbol)
        self._chart_title.config(text=f"{name} ({symbol})")

        # 如果有缓存数据直接显示
        if symbol in self._data_cache:
            self._draw_chart(symbol, self._data_cache[symbol])
            if symbol in self._analysis_cache:
                self._update_indicators(self._analysis_cache[symbol])
        else:
            self._cmd_refresh()

    def _auto_refresh(self):
        """启动时自动选择第一个指数并刷新"""
        if self._symbol_buttons:
            first = list(self._symbol_buttons.keys())[0]
            self._on_select_symbol(first)

    # ---------------------------------------------------------------
    # 命令按钮
    # ---------------------------------------------------------------

    def _cmd_refresh(self):
        """刷新数据"""
        if not self._current_symbol:
            messagebox.showwarning("提示", "请先选择一个指数")
            return

        def do_refresh():
            try:
                if self._domain is None:
                    self.root.after(0, lambda: messagebox.showerror("错误", "股票子系统未初始化"))
                    return

                result = self._domain.fetch([self._current_symbol])
                self.root.after(0, lambda: self._on_data_fetched(result))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"数据获取失败: {e}"))

        threading.Thread(target=do_refresh, daemon=True).start()

    def _on_data_fetched(self, result):
        """数据获取完成回调"""
        if not result.get("success"):
            messagebox.showerror("错误", result.get("message", "获取失败"))
            return

        data = result.get("data", {})
        mode = result.get("mode", "unknown")

        # 更新数据源标签
        mode_text = {"real": "真实数据(akshare)", "mock": "模拟数据(降级)"}
        self._source_label.config(
            text=f"数据源: {mode_text.get(mode, mode)}",
            fg=Theme.COLOR_GREEN if mode == "real" else Theme.COLOR_SECONDARY
        )

        # 缓存数据
        for sym, df in data.items():
            self._data_cache[sym] = df

        # 更新图表
        if self._current_symbol in data:
            self._draw_chart(self._current_symbol, data[self._current_symbol])

        # 更新状态
        self._update_status_panel()

    def _cmd_analyze(self):
        """技术分析"""
        if not self._current_symbol or self._current_symbol not in self._data_cache:
            messagebox.showwarning("提示", "请先刷新数据")
            return

        def do_analyze():
            try:
                data = {self._current_symbol: self._data_cache[self._current_symbol]}
                result = self._domain.analyze(data)
                self.root.after(0, lambda: self._on_analysis_done(result))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"分析失败: {e}"))

        threading.Thread(target=do_analyze, daemon=True).start()

    def _on_analysis_done(self, result):
        """分析完成回调"""
        if result.get("status") != "ok":
            messagebox.showwarning("提示", "分析未返回有效结果")
            return

        results = result.get("results", {})
        for sym, r in results.items():
            self._analysis_cache[sym] = r

        if self._current_symbol in results:
            self._update_indicators(results[self._current_symbol])

    def _cmd_pick(self):
        """选股推荐"""
        if not self._analysis_cache:
            messagebox.showwarning("提示", "请先执行技术分析")
            return

        def do_pick():
            try:
                params = {"results": self._analysis_cache}
                result = self._domain.generate(params, top_n=5)
                self.root.after(0, lambda: self._on_pick_done(result))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"选股失败: {e}"))

        threading.Thread(target=do_pick, daemon=True).start()

    def _on_pick_done(self, result):
        """选股完成回调"""
        predictions = result.get("predictions", [])

        # 清空表格
        for item in self._rec_table.get_children():
            self._rec_table.delete(item)

        # 填充数据
        action_map = {"buy": "买入", "hold": "持有", "watch": "观望"}
        action_color = {"buy": Theme.COLOR_GREEN, "hold": Theme.COLOR_SECONDARY, "watch": Theme.TEXT_MUTED}

        for p in predictions:
            sym = p.get("symbol", "")
            name = SYMBOL_NAMES.get(sym, sym)
            action = action_map.get(p.get("action", ""), p.get("action", ""))
            conf = f"{_as_float(p.get('confidence', 0)):.1f}%"
            reason = p.get("reason", "")

            self._rec_table.insert("", "end", values=(sym, name, action, conf, reason))

    def _cmd_truth_check(self):
        """数据真实性检测"""
        try:
            from core.data_truth_guard import run_truth_check, format_truth_report
            report = run_truth_check()
            text = format_truth_report(report)

            # 弹窗显示报告
            dialog = tk.Toplevel(self.root)
            dialog.title("数据真实性检测报告")
            dialog.geometry("700x600")
            dialog.configure(bg=Theme.BG_DEEP)

            txt = tk.Text(dialog, bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                          font=("Consolas", 10), padx=15, pady=15,
                          wrap="word", state="normal")
            txt.pack(fill="both", expand=True, padx=10, pady=10)
            txt.insert("1.0", text)
            txt.config(state="disabled")

        except Exception as e:
            messagebox.showerror("错误", f"检测失败: {e}")

    # ---------------------------------------------------------------
    # 图表绘制
    # ---------------------------------------------------------------

    def _draw_chart(self, symbol, df):
        """绘制K线图"""
        if not MATPLOTLIB_OK or self._fig is None:
            return

        self._fig.clear()

        # 创建子图：价格 + 成交量
        ax1 = self._fig.add_subplot(2, 1, 1)
        ax2 = self._fig.add_subplot(2, 1, 2, sharex=ax1)

        # 确保数据格式正确
        try:
            dates = df["date"].tolist() if "date" in df.columns else list(range(len(df)))
            closes = df["close"].astype(float).tolist() if "close" in df.columns else []
            opens = df["open"].astype(float).tolist() if "open" in df.columns else []
            highs = df["high"].astype(float).tolist() if "high" in df.columns else []
            lows = df["low"].astype(float).tolist() if "low" in df.columns else []
            volumes = df["volume"].astype(float).tolist() if "volume" in df.columns else []

            # 只显示最近60天
            max_points = 60
            if len(dates) > max_points:
                dates = dates[-max_points:]
                closes = closes[-max_points:]
                opens = opens[-max_points:]
                highs = highs[-max_points:]
                lows = lows[-max_points:]
                volumes = volumes[-max_points:]

            x = range(len(dates))

            # 价格线
            ax1.plot(x, closes, color=Theme.COLOR_PRIMARY, linewidth=1.5, label="收盘价")

            # 如果有MA数据也画出来
            if symbol in self._analysis_cache:
                ind = self._analysis_cache[symbol].get("indicators", {})
                for ma_key, ma_color in [("ma5_list", Theme.COLOR_SECONDARY),
                                          ("ma20_list", Theme.COLOR_ACCENT),
                                          ("ma60_list", Theme.COLOR_PURPLE)]:
                    ma_list = ind.get(ma_key)
                    if ma_list:
                        ma_label = ma_key.replace("_list", "").upper()
                        # 对齐到收盘价数组
                        ma_aligned = [None] * (len(closes) - len(ma_list)) + ma_list[-len(closes):]
                        ax1.plot(x, ma_aligned, color=ma_color, linewidth=1, alpha=0.7, label=ma_label)

            ax1.set_ylabel("价格", color=Theme.TEXT_SECONDARY)
            ax1.tick_params(colors=Theme.TEXT_SECONDARY)
            ax1.set_facecolor(Theme.BG_CARD)
            ax1.legend(loc="upper left", facecolor=Theme.BG_CARD, edgecolor=Theme.BORDER,
                       labelcolor=Theme.TEXT_SECONDARY, fontsize=8)
            ax1.grid(True, alpha=0.2, color=Theme.BORDER)

            # 成交量
            if volumes:
                colors = [Theme.COLOR_GREEN if closes[i] >= opens[i] else Theme.COLOR_RED
                          for i in range(len(closes))]
                ax2.bar(x, volumes, color=colors, alpha=0.6, width=0.8)
                ax2.set_ylabel("成交量", color=Theme.TEXT_SECONDARY)
                ax2.tick_params(colors=Theme.TEXT_SECONDARY)
                ax2.set_facecolor(Theme.BG_CARD)
                ax2.grid(True, alpha=0.2, color=Theme.BORDER)

            # X轴标签
            step = max(1, len(dates) // 6)
            ax2.set_xticks(x[::step])
            ax2.set_xticklabels([str(d)[-5:] if len(str(d)) > 5 else str(d)
                                 for d in dates[::step]], rotation=30,
                                color=Theme.TEXT_SECONDARY, fontsize=8)

            self._fig.tight_layout()
            self._canvas.draw()

        except Exception as e:
            print(f"[ERR] 图表绘制失败: {e}")

    # ---------------------------------------------------------------
    # 指标更新
    # ---------------------------------------------------------------

    def _update_indicators(self, result):
        """更新技术指标显示"""
        indicators = result.get("indicators", {})
        trend = result.get("trend", {})

        # 最新价格
        latest = indicators.get("latest_price")
        if latest is not None:
            self._price_main.config(text=f"{latest:.2f}")

        # 涨跌（简化：和前一天比较）
        ma5 = indicators.get("ma5")
        if latest and ma5:
            change = (latest - ma5) / ma5 * 100
            color = Theme.COLOR_GREEN if change >= 0 else Theme.COLOR_RED
            self._price_change.config(text=f"{'+' if change >= 0 else ''}{change:.2f}%",
                                      fg=color)

        # MA指标
        for key, fmt in [("ma5", "{:.2f}"), ("ma20", "{:.2f}"), ("ma60", "{:.2f}")]:
            val = indicators.get(key)
            if val is not None:
                self._ind_labels[key].config(text=fmt.format(val))
            else:
                self._ind_labels[key].config(text="--")

        # 趋势方向
        direction = trend.get("direction", "unknown")
        dir_map = {"up": ("上涨", Theme.COLOR_GREEN),
                   "down": ("下跌", Theme.COLOR_RED),
                   "sideways": ("震荡", Theme.COLOR_SECONDARY),
                   "unknown": ("未知", Theme.TEXT_MUTED)}
        dir_text, dir_color = dir_map.get(direction, ("未知", Theme.TEXT_MUTED))
        self._ind_labels["trend"].config(text=dir_text, fg=dir_color)

        # 趋势强度
        strength = trend.get("strength", 0)
        self._ind_labels["strength"].config(text=f"{strength:.1f}")

        # 交易信号
        signals = result.get("signals", [])
        self._update_signals(signals)

    def _update_signals(self, signals):
        """更新交易信号列表"""
        # 清空
        for widget in self._signal_list.winfo_children():
            widget.destroy()

        if not signals:
            tk.Label(self._signal_list, text="暂无信号",
                     font=(Theme.FONT_FAMILY, 10),
                     fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="w")
            return

        for sig in signals:
            color = Theme.COLOR_GREEN if "多" in sig or "涨" in sig else Theme.COLOR_RED if "空" in sig or "跌" in sig else Theme.TEXT_SECONDARY
            tk.Label(self._signal_list, text=f"▸ {sig}",
                     font=(Theme.FONT_FAMILY, 10),
                     fg=color, bg=Theme.BG_CARD).pack(anchor="w", pady=2)

    def _update_status_panel(self):
        """更新数据状态面板"""
        if self._domain is None:
            return

        status = self._domain.status()
        engines = status.get("engines", [])

        # akshare状态
        ak_ok = any("unavailable" not in e for e in engines if "Fetcher" in e)
        self._status_labels["akshare"].config(
            text="就绪" if ak_ok else "不可用",
            fg=Theme.COLOR_GREEN if ak_ok else Theme.COLOR_RED)

        # 熔断器
        try:
            from core.circuit_breaker import CircuitBreakerRegistry
            registry = CircuitBreakerRegistry()
            breaker = registry.get("stock_akshare")
            stats = breaker.get_stats()
            state = stats.get("state", "closed")
            state_text = {"closed": "正常", "open": "熔断中", "half_open": "恢复探测"}
            self._status_labels["breaker"].config(
                text=state_text.get(state, state),
                fg=Theme.COLOR_GREEN if state == "closed" else Theme.COLOR_RED)
        except Exception:
            self._status_labels["breaker"].config(text="未初始化", fg=Theme.TEXT_MUTED)

        # 缓存
        cache_size = status.get("cache_size", 0)
        self._status_labels["cache"].config(text=f"{cache_size}只股票", fg=Theme.TEXT_SECONDARY)

        # 模式
        mode = "模拟" if not ak_ok else "真实"
        self._status_labels["mode"].config(text=mode,
                                           fg=Theme.COLOR_SECONDARY if mode == "模拟" else Theme.COLOR_GREEN)

    # ---------------------------------------------------------------
    # 运行
    # ---------------------------------------------------------------

    def run(self):
        """启动GUI主循环"""
        self.root.mainloop()


# =======================================================================
# 入口
# =======================================================================
def main():
    """股票分析系统入口"""
    root = tk.Tk()
    try:
        from core.tk_style import apply_dark_style
        apply_dark_style(root)
    except Exception:
        pass
    app = StockAnalysisWindow(root)
    app.run()


if __name__ == "__main__":
    main()
