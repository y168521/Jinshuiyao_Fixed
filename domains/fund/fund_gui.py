# -*- coding: utf-8 -*-
"""金水谣基金分析系统 - 独立GUI窗口

功能：
  - 基金代码输入 + 关注列表（默认基金池）
  - 净值走势图（matplotlib嵌入tkinter，含累计净值）
  - 关键指标面板（最新净值/累计收益/夏普比率/最大回撤/风险等级）
  - 基金推荐列表（评分排序 + 买卖建议 + 综合评级）
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
# 导入路径处理 —— 与 stock_gui.py 保持一致
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


# =======================================================================
# 基金分析主窗口
# =======================================================================
class FundAnalysisWindow:
    """金水谣基金分析系统主窗口"""

    def __init__(self, master=None):
        self.root = master or tk.Tk()
        self.root.title("金水谣基金分析系统")
        self.root.geometry("1400x900")
        self.root.configure(bg=Theme.BG_DEEP)
        self.root.minsize(1200, 700)

        # 业务层
        self._domain = None
        self._current_fund = None
        self._data_cache = {}        # {fund_code: {nav, info, holdings}}
        self._analysis_cache = {}    # {fund_code: analysis_result}

        # 初始化基金域
        self._init_domain()

        # 构建UI
        self._build_ui()

        # 启动时自动刷新数据
        self.root.after(500, self._auto_refresh)

    # ---------------------------------------------------------------
    # 业务初始化
    # ---------------------------------------------------------------

    def _init_domain(self):
        """初始化 FundDomain（不可用时降级提示）"""
        self._domain_err = None
        try:
            from domains.fund.domain import FundDomain
            self._domain = FundDomain()
            ok = self._domain.setup()
            if not ok:
                self._domain_err = "FundDomain.setup() 返回 False"
                print("[WARN] FundDomain.setup() 返回False")
        except Exception as e:
            self._domain_err = str(e)
            print(f"[ERR] 基金子系统初始化失败: {e}")
            self._domain = None

    def _ensure_domain(self):
        """确保基金域已初始化；未初始化则自动重试一次"""
        if self._domain is not None:
            return True
        self._init_domain()
        return self._domain is not None

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
        main_frame.grid_columnconfigure(0, weight=0, minsize=240)
        main_frame.grid_columnconfigure(1, weight=3, minsize=600)
        main_frame.grid_columnconfigure(2, weight=0, minsize=260)
        main_frame.grid_rowconfigure(0, weight=1)

        # 左栏：基金代码输入 + 关注列表
        self._build_left_panel(main_frame)

        # 中栏：净值走势图
        self._build_chart_panel(main_frame)

        # 右栏：关键指标
        self._build_right_panel(main_frame)

        # 底部：基金推荐列表 + 操作按钮
        self._build_bottom_panel()

    def _build_header(self):
        """顶部标题栏"""
        header = tk.Frame(self.root, bg=Theme.BG_CARD, height=50)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        tk.Label(header, text="金水谣基金分析系统",
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
        """左栏：基金代码输入 + 关注列表"""
        left = tk.Frame(parent, bg=Theme.BG_DEEP, width=240)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_propagate(False)

        # --- 基金代码输入 ---
        input_frame = tk.Frame(left, bg=Theme.BG_CARD, padx=10, pady=10)
        input_frame.pack(fill="x", pady=(0, 10))

        tk.Label(input_frame, text="基金代码",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 8))

        code_row = tk.Frame(input_frame, bg=Theme.BG_CARD)
        code_row.pack(fill="x")

        self._code_var = tk.StringVar()
        self._code_entry = tk.Entry(code_row, textvariable=self._code_var,
                                    font=(Theme.FONT_FAMILY, 11),
                                    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
                                    insertbackground=Theme.TEXT_PRIMARY,
                                    relief="flat", width=10)
        self._code_entry.pack(side="left", ipady=4)

        tk.Button(code_row, text="查询",
                  font=(Theme.FONT_FAMILY, 10),
                  fg=Theme.BG_DEEP, bg=Theme.COLOR_PRIMARY,
                  activebackground=Theme.COLOR_PRIMARY,
                  activeforeground=Theme.BG_DEEP,
                  relief="flat", cursor="hand2", padx=10,
                  command=self._on_query_code).pack(side="right")

        # --- 关注列表 ---
        list_frame = tk.Frame(left, bg=Theme.BG_CARD, padx=10, pady=10)
        list_frame.pack(fill="both", expand=True, pady=(0, 10))

        tk.Label(list_frame, text="关注列表",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        # 关注基金滚动列表
        list_wrap = tk.Frame(list_frame, bg=Theme.BG_CARD)
        list_wrap.pack(fill="both", expand=True)

        self._fund_buttons = {}
        # 默认基金池来自 FundDomain（若不可用则使用内置）
        try:
            from domains.fund.domain import FundDomain
            default_funds = FundDomain.DEFAULT_FUNDS
        except Exception:
            default_funds = ["000001", "110011", "161725", "005827",
                             "519674", "003096", "260108"]

        for code in default_funds:
            btn = tk.Button(list_wrap, text=f"{code}",
                            font=(Theme.FONT_FAMILY, 10),
                            fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                            activebackground=Theme.COLOR_PRIMARY,
                            activeforeground=Theme.BG_DEEP,
                            relief="flat", cursor="hand2",
                            command=lambda c=code: self._on_select_fund(c))
            btn.pack(fill="x", pady=(0, 6))
            self._fund_buttons[code] = btn

    def _build_chart_panel(self, parent):
        """中栏：净值走势图"""
        chart_frame = tk.Frame(parent, bg=Theme.BG_CARD)
        chart_frame.grid(row=0, column=1, sticky="nsew")

        # 图表标题
        self._chart_title = tk.Label(chart_frame, text="请选择基金",
                                     font=(Theme.FONT_FAMILY, 13, "bold"),
                                     fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD)
        self._chart_title.pack(anchor="w", padx=15, pady=10)

        # matplotlib 画布（不可用时降级为文字提示）
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
        """右栏：关键指标面板"""
        right = tk.Frame(parent, bg=Theme.BG_DEEP, width=260)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        right.grid_propagate(False)

        # --- 最新净值 ---
        nav_frame = tk.Frame(right, bg=Theme.BG_CARD, padx=12, pady=12)
        nav_frame.pack(fill="x", pady=(0, 10))

        tk.Label(nav_frame, text="最新净值",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        self._nav_main = tk.Label(nav_frame, text="--",
                                  font=(Theme.FONT_FAMILY, 28, "bold"),
                                  fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD)
        self._nav_main.pack(anchor="w")

        self._nav_change = tk.Label(nav_frame, text="--",
                                    font=(Theme.FONT_FAMILY, 12),
                                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self._nav_change.pack(anchor="w", pady=(4, 0))

        # --- 关键指标 ---
        ind_frame = tk.Frame(right, bg=Theme.BG_CARD, padx=12, pady=12)
        ind_frame.pack(fill="x", pady=(0, 10), expand=True)

        tk.Label(ind_frame, text="关键指标",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        self._ind_labels = {}
        ind_items = [
            ("cum_return", "累计收益"),
            ("annual", "年化收益"),
            ("sharpe", "夏普比率"),
            ("max_dd", "最大回撤"),
            ("volatility", "年化波动率"),
            ("risk_level", "风险等级"),
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

        # --- 综合评级 ---
        grade_frame = tk.Frame(right, bg=Theme.BG_CARD, padx=12, pady=12)
        grade_frame.pack(fill="x", pady=(0, 10))

        tk.Label(grade_frame, text="综合评级",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        self._grade_main = tk.Label(grade_frame, text="--",
                                    font=(Theme.FONT_FAMILY, 24, "bold"),
                                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self._grade_main.pack(anchor="w")

        self._grade_score = tk.Label(grade_frame, text="",
                                     font=(Theme.FONT_FAMILY, 10),
                                     fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        self._grade_score.pack(anchor="w", pady=(4, 0))

    def _build_bottom_panel(self):
        """底部：基金推荐列表 + 操作按钮"""
        bottom = tk.Frame(self.root, bg=Theme.BG_DEEP, height=220)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        bottom.pack_propagate(False)

        # 上部分：基金推荐表格
        rec_frame = tk.Frame(bottom, bg=Theme.BG_CARD, padx=10, pady=8)
        rec_frame.pack(fill="both", expand=True, pady=(0, 8))

        tk.Label(rec_frame, text="基金推荐",
                 font=(Theme.FONT_FAMILY, 12, "bold"),
                 fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w")

        # Treeview表格
        columns = ("code", "name", "action", "confidence", "grade",
                   "annual", "sharpe", "reason")
        self._rec_table = ttk.Treeview(rec_frame, columns=columns,
                                       show="headings", height=4)
        self._rec_table.heading("code", text="基金代码")
        self._rec_table.heading("name", text="基金名称")
        self._rec_table.heading("action", text="操作建议")
        self._rec_table.heading("confidence", text="置信度")
        self._rec_table.heading("grade", text="评级")
        self._rec_table.heading("annual", text="年化收益")
        self._rec_table.heading("sharpe", text="夏普比率")
        self._rec_table.heading("reason", text="推荐理由")

        self._rec_table.column("code", width=80, anchor="center")
        self._rec_table.column("name", width=140, anchor="center")
        self._rec_table.column("action", width=80, anchor="center")
        self._rec_table.column("confidence", width=70, anchor="center")
        self._rec_table.column("grade", width=50, anchor="center")
        self._rec_table.column("annual", width=80, anchor="center")
        self._rec_table.column("sharpe", width=70, anchor="center")
        self._rec_table.column("reason", width=380, anchor="w")

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
            ("基金分析", self._cmd_analyze, Theme.COLOR_SECONDARY),
            ("基金推荐", self._cmd_pick, Theme.COLOR_ACCENT),
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

    def _on_query_code(self):
        """查询输入的基金代码"""
        code = self._code_var.get().strip()
        if not code:
            messagebox.showwarning("提示", "请输入基金代码")
            return
        # 校验：基金代码一般为6位数字
        if not code.isdigit() or len(code) != 6:
            messagebox.showwarning("提示", "基金代码应为6位数字")
            return
        self._on_select_fund(code)

    def _on_select_fund(self, code):
        """选择基金"""
        self._current_fund = code

        # 如果不在关注列表中，则动态添加一个按钮
        if code not in self._fund_buttons:
            list_wrap = self._fund_buttons[list(self._fund_buttons.keys())[0]].master
            btn = tk.Button(list_wrap, text=f"{code}",
                            font=(Theme.FONT_FAMILY, 10),
                            fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                            activebackground=Theme.COLOR_PRIMARY,
                            activeforeground=Theme.BG_DEEP,
                            relief="flat", cursor="hand2",
                            command=lambda c=code: self._on_select_fund(c))
            btn.pack(fill="x", pady=(0, 6))
            self._fund_buttons[code] = btn

        # 更新按钮高亮
        for c, btn in self._fund_buttons.items():
            if c == code:
                btn.config(bg=Theme.COLOR_PRIMARY, fg=Theme.BG_DEEP)
            else:
                btn.config(bg=Theme.BG_HOVER, fg=Theme.TEXT_SECONDARY)

        self._chart_title.config(text=f"基金 {code}")

        # 如果有缓存数据直接显示
        if code in self._data_cache:
            self._draw_chart(code, self._data_cache[code])
            if code in self._analysis_cache:
                self._update_indicators(self._analysis_cache[code])
        else:
            self._cmd_refresh()

    def _auto_refresh(self):
        """启动时自动选择第一个基金并刷新"""
        if self._fund_buttons:
            first = list(self._fund_buttons.keys())[0]
            self._on_select_fund(first)

    # ---------------------------------------------------------------
    # 命令按钮
    # ---------------------------------------------------------------

    def _cmd_refresh(self):
        """刷新数据"""
        if not self._current_fund:
            messagebox.showwarning("提示", "请先选择一个基金")
            return

        def do_refresh():
            try:
                if not self._ensure_domain():
                    reason = self._domain_err or "未知原因"
                    self.root.after(0, lambda: messagebox.showerror(
                        "基金子系统初始化失败",
                        f"无法连接基金数据服务：{reason}\n\n请检查项目目录是否完整，或稍后重试。"))
                    return

                result = self._domain.fetch([self._current_fund])
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
        for code, fund_data in data.items():
            self._data_cache[code] = fund_data

        # 更新图表与基金名称
        if self._current_fund in data:
            fund_data = data[self._current_fund]
            info = fund_data.get("info", {})
            name = info.get("基金名称", self._current_fund)
            self._chart_title.config(text=f"{name} ({self._current_fund})")
            self._draw_chart(self._current_fund, fund_data)

        # 更新状态面板
        self._update_status_panel()

    def _cmd_analyze(self):
        """基金分析"""
        if not self._current_fund or self._current_fund not in self._data_cache:
            messagebox.showwarning("提示", "请先刷新数据")
            return

        def do_analyze():
            try:
                data = {self._current_fund: self._data_cache[self._current_fund]}
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
        for code, r in results.items():
            self._analysis_cache[code] = r

        if self._current_fund in results:
            self._update_indicators(results[self._current_fund])

    def _cmd_pick(self):
        """基金推荐"""
        if not self._analysis_cache:
            messagebox.showwarning("提示", "请先执行基金分析")
            return

        def do_pick():
            try:
                params = {"results": self._analysis_cache}
                result = self._domain.generate(params, top_n=10)
                self.root.after(0, lambda: self._on_pick_done(result))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"推荐生成失败: {e}"))

        threading.Thread(target=do_pick, daemon=True).start()

    def _on_pick_done(self, result):
        """推荐完成回调"""
        predictions = result.get("predictions", [])

        # 清空表格
        for item in self._rec_table.get_children():
            self._rec_table.delete(item)

        # 填充数据
        action_map = {"buy": "买入", "hold": "持有", "watch": "观望"}

        for p in predictions:
            code = p.get("fund_code", "")
            name = p.get("fund_name", code)
            action = action_map.get(p.get("action", ""), p.get("action", ""))
            conf = f"{_as_float(p.get('confidence', 0)):.1f}%"
            grade = p.get("grade", "--")
            annual = p.get("annual_return", 0)
            annual_text = f"{annual:.2f}%" if isinstance(annual, (int, float)) else str(annual)
            sharpe = p.get("sharpe_ratio", 0)
            sharpe_text = f"{sharpe:.2f}" if isinstance(sharpe, (int, float)) else str(sharpe)
            reason = p.get("reason", "")

            self._rec_table.insert("", "end", values=(code, name, action, conf,
                                                      grade, annual_text, sharpe_text, reason))

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

    def _draw_chart(self, fund_code, fund_data):
        """绘制净值走势图"""
        if not MATPLOTLIB_OK or self._fig is None:
            return

        self._fig.clear()
        ax = self._fig.add_subplot(1, 1, 1)

        try:
            nav_df = fund_data.get("nav")
            if nav_df is None or not hasattr(nav_df, "columns"):
                ax.text(0.5, 0.5, "无净值数据", ha="center", va="center",
                        color=Theme.TEXT_MUTED, transform=ax.transAxes)
                self._fig.tight_layout()
                self._canvas.draw()
                return

            # 提取日期与净值序列
            if "净值日期" in nav_df.columns:
                dates = nav_df["净值日期"].astype(str).tolist()
            else:
                dates = list(range(len(nav_df)))

            unit_navs = nav_df["单位净值"].astype(float).tolist() if "单位净值" in nav_df.columns else []
            cum_navs = nav_df["累计净值"].astype(float).tolist() if "累计净值" in nav_df.columns else []

            # 只显示最近120个交易日，避免过于密集
            max_points = 120
            if len(dates) > max_points:
                dates = dates[-max_points:]
                unit_navs = unit_navs[-max_points:]
                cum_navs = cum_navs[-max_points:]

            x = range(len(dates))

            # 单位净值主线
            if unit_navs:
                ax.plot(x, unit_navs, color=Theme.COLOR_PRIMARY,
                        linewidth=1.8, label="单位净值")
            # 累计净值辅助线
            if cum_navs:
                ax.plot(x, cum_navs, color=Theme.COLOR_SECONDARY,
                        linewidth=1.2, alpha=0.7, label="累计净值")

            ax.set_ylabel("净值", color=Theme.TEXT_SECONDARY)
            ax.tick_params(colors=Theme.TEXT_SECONDARY)
            ax.set_facecolor(Theme.BG_CARD)
            ax.legend(loc="upper left", facecolor=Theme.BG_CARD, edgecolor=Theme.BORDER,
                      labelcolor=Theme.TEXT_SECONDARY, fontsize=9)
            ax.grid(True, alpha=0.2, color=Theme.BORDER)

            # X轴标签
            step = max(1, len(dates) // 6)
            ax.set_xticks(list(x)[::step])
            ax.set_xticklabels([str(d)[-5:] if len(str(d)) > 5 else str(d)
                                for d in dates[::step]], rotation=30,
                               color=Theme.TEXT_SECONDARY, fontsize=8)

            self._fig.tight_layout()
            self._canvas.draw()

        except Exception as e:
            print(f"[ERR] 净值图绘制失败: {e}")

    # ---------------------------------------------------------------
    # 指标更新
    # ---------------------------------------------------------------

    def _update_indicators(self, result):
        """更新关键指标显示"""
        nav_analysis = result.get("nav_analysis", {})
        returns = nav_analysis.get("returns", {})
        risk = nav_analysis.get("risk", {})
        risk_adj = nav_analysis.get("risk_adjusted", {})
        comp = result.get("composite_score", {})

        # 最新净值 + 日增长率
        fund_data = self._data_cache.get(self._current_fund, {})
        nav_df = fund_data.get("nav")
        latest_nav = None
        daily_growth = None
        if nav_df is not None and hasattr(nav_df, "columns") and "单位净值" in nav_df.columns:
            navs = nav_df["单位净值"].tolist()
            if navs:
                latest_nav = float(navs[-1])
            if "日增长率" in nav_df.columns and len(nav_df) > 0:
                daily_growth = nav_df["日增长率"].iloc[-1]

        if latest_nav is not None:
            self._nav_main.config(text=f"{latest_nav:.4f}")

        if isinstance(daily_growth, (int, float)):
            color = Theme.COLOR_GREEN if daily_growth >= 0 else Theme.COLOR_RED
            self._nav_change.config(
                text=f"日涨跌: {'+' if daily_growth >= 0 else ''}{daily_growth:.2f}%",
                fg=color)
        else:
            self._nav_change.config(text="日涨跌: --", fg=Theme.TEXT_MUTED)

        # 累计收益（成立来）
        cum_ret = returns.get("成立来", returns.get("年化收益率"))
        if isinstance(cum_ret, (int, float)):
            color = Theme.COLOR_GREEN if cum_ret >= 0 else Theme.COLOR_RED
            self._ind_labels["cum_return"].config(
                text=f"{'+' if cum_ret >= 0 else ''}{cum_ret:.2f}%", fg=color)
        else:
            self._ind_labels["cum_return"].config(text="--", fg=Theme.TEXT_MUTED)

        # 年化收益
        annual = returns.get("年化收益率")
        if isinstance(annual, (int, float)):
            color = Theme.COLOR_GREEN if annual >= 0 else Theme.COLOR_RED
            self._ind_labels["annual"].config(
                text=f"{'+' if annual >= 0 else ''}{annual:.2f}%", fg=color)
        else:
            self._ind_labels["annual"].config(text="--", fg=Theme.TEXT_MUTED)

        # 夏普比率
        sharpe = risk_adj.get("夏普比率")
        if isinstance(sharpe, (int, float)):
            color = Theme.COLOR_GREEN if sharpe >= 1.0 else (
                Theme.COLOR_SECONDARY if sharpe >= 0.5 else Theme.COLOR_RED)
            self._ind_labels["sharpe"].config(text=f"{sharpe:.2f}", fg=color)
        else:
            self._ind_labels["sharpe"].config(text="--", fg=Theme.TEXT_MUTED)

        # 最大回撤
        max_dd = risk.get("最大回撤")
        if isinstance(max_dd, (int, float)):
            color = Theme.COLOR_GREEN if max_dd > -15 else (
                Theme.COLOR_SECONDARY if max_dd > -25 else Theme.COLOR_RED)
            self._ind_labels["max_dd"].config(text=f"{max_dd:.2f}%", fg=color)
        else:
            self._ind_labels["max_dd"].config(text="--", fg=Theme.TEXT_MUTED)

        # 年化波动率
        vol = risk.get("波动率(年化)")
        if isinstance(vol, (int, float)):
            self._ind_labels["volatility"].config(text=f"{vol:.2f}%", fg=Theme.TEXT_SECONDARY)
        else:
            self._ind_labels["volatility"].config(text="--", fg=Theme.TEXT_MUTED)

        # 风险等级（由最大回撤推导）
        risk_level, risk_color = self._calc_risk_level(max_dd, vol)
        self._ind_labels["risk_level"].config(text=risk_level, fg=risk_color)

        # 综合评级
        grade = comp.get("等级", "--")
        total = comp.get("总分", 0)
        grade_color_map = {"A+": Theme.COLOR_GREEN, "A": Theme.COLOR_GREEN,
                           "B": Theme.COLOR_SECONDARY, "C": Theme.COLOR_AMBER,
                           "D": Theme.COLOR_RED}
        self._grade_main.config(text=grade,
                                fg=grade_color_map.get(grade, Theme.TEXT_MUTED))
        if isinstance(total, (int, float)):
            self._grade_score.config(text=f"综合评分 {total:.1f}")
        else:
            self._grade_score.config(text="")

    @staticmethod
    def _calc_risk_level(max_dd, volatility):
        """根据最大回撤与波动率推断风险等级

        Args:
            max_dd: 最大回撤（百分比，通常为负数）
            volatility: 年化波动率（百分比）

        Returns:
            tuple: (等级文本, 颜色)
        """
        # 无法计算时返回未知
        if not isinstance(max_dd, (int, float)) and not isinstance(volatility, (int, float)):
            return "未知", Theme.TEXT_MUTED

        dd = max_dd if isinstance(max_dd, (int, float)) else 0
        vol = volatility if isinstance(volatility, (int, float)) else 0

        # 低风险：回撤<10% 且 波动率<15%
        if dd > -10 and vol < 15:
            return "低风险", Theme.COLOR_GREEN
        # 高风险：回撤>25% 或 波动率>30%
        if dd < -25 or vol > 30:
            return "高风险", Theme.COLOR_RED
        # 其余为中风险
        return "中风险", Theme.COLOR_SECONDARY

    def _update_status_panel(self):
        """更新数据源状态（写入顶部状态标签）"""
        if self._domain is None:
            self._source_label.config(text="数据源: 子系统未就绪", fg=Theme.COLOR_RED)
            return

        try:
            status = self._domain.status()
            engines = status.get("engines", [])

            # 判断数据获取器是否就绪
            fetcher_ok = any("FundFetcher" in e and "unavailable" not in e for e in engines)
            cache_size = status.get("cache_size", 0)

            if fetcher_ok:
                self._source_label.config(
                    text=f"数据源: 就绪 | 缓存 {cache_size} 只基金",
                    fg=Theme.COLOR_GREEN)
            else:
                self._source_label.config(
                    text=f"数据源: 降级模式 | 缓存 {cache_size} 只基金",
                    fg=Theme.COLOR_SECONDARY)
        except Exception as e:
            print(f"[WARN] 状态查询失败: {e}")

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
    """基金分析系统入口"""
    root = tk.Tk()
    try:
        from core.tk_style import apply_dark_style
        apply_dark_style(root)
    except Exception:
        pass
    app = FundAnalysisWindow(root)
    app.run()


if __name__ == "__main__":
    main()
