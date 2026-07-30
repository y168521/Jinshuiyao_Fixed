# -*- coding: utf-8 -*-
"""金水谣万物引擎 - 主窗口GUI

使用 customtkinter + ttkbootstrap 构建现代化暗色科技风界面。
包含：预测生成、数据抓取、数据导入、热度统计、走势图、足彩入口等功能。

依赖模块：
  config / models.lottery_data / fetchers.fetcher / engines.* / controllers.* / utils.* / importers.*
"""

# ==================== sys.path 设置（根因修复：确保项目根目录在搜索路径中） ====================
import os, sys
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_THIS_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

# ==================== 标准库导入 ====================
import datetime
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

# ==================== 可选第三方库导入 ====================
try:
    import customtkinter as ctk
    CTk_AVAILABLE = True
except ImportError:
    CTk_AVAILABLE = False
    ctk = None

try:
    import ttkbootstrap as tb
    TB_AVAILABLE = True
except ImportError:
    TB_AVAILABLE = False
    tb = None

try:
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import pyperclip
except ImportError:
    pyperclip = None

# ==================== 项目模块导入 ====================
from config import (VERSION, LOT_ALL, LOT_ALIAS, LOTTERY_RULES, ENGINE_NAMES,
                    DATA_SAVE, PRED_CACHE, ENGINE_SET, SCHEME_CACHE, REFERENCE_CACHE,
                    LOG_DIR, ERR_LOG_DIR, DEFAULT_MAX_BUDGET, MAX_BUDGET_LIMIT,
                    DEFAULT_HOT_WINDOW, TICKET_PRICE)
from models.lottery_data import Data
from fetchers.fetcher import Fetcher
from engines.killer import Killer
from engines.evolve import Evolve
from controllers.scheme_manager import SchemeManager
from engines.prediction_service import PredictionService
from engines.format_gen import FormatGen
from utils.safe_json import safe_load_json, safe_write_json
from utils.locks import json_lock, preds_lock
from utils.number_utils import clean_nums, parse_reds, fmt_period, format_display
from importers.lottery_data_importer import LotteryDataImporter


# ==================== 现代深色科技风主题配置 ====================
class ModernTheme:
    """现代深色科技风主题配置 — 颜色常量与圆角参数"""

    # 背景色
    BG_DEEP = '#0a0e1a'
    BG_CARD = '#111827'
    BG_HOVER = '#1f2937'
    BG_INPUT = '#1a1a2e'
    BG_ACTIVE = '#374151'

    # 文字色
    TEXT_PRIMARY = '#f9fafb'
    TEXT_SECONDARY = '#9ca3af'
    TEXT_MUTED = '#6b7280'

    # 功能色
    COLOR_PRIMARY = '#06b6d4'
    COLOR_PRIMARY_DARK = '#0891b2'
    COLOR_SECONDARY = '#f59e0b'
    COLOR_ACCENT = '#10b981'
    COLOR_PURPLE = '#8b5cf6'
    COLOR_RED = '#ef4444'
    SUCCESS = '#10b981'

    # 字体与圆角
    FONT_FAMILY = 'Microsoft YaHei'
    CORNER_RADIUS = 8
    CORNER_RADIUS_SMALL = 6
    CORNER_RADIUS_LARGE = 12

    # 边框
    BORDER = '#374151'


# ==================== 主应用窗口 ====================
class App:
    """金水谣万物引擎主应用窗口

    使用 customtkinter + ttkbootstrap 构建现代化暗色科技风界面。
    集成预测生成、数据抓取、数据导入、热度统计、走势图、足彩入口等功能。
    """

    # 引擎列表（顺序固定）
    ENGINE_LIST = [
        "trend", "turning", "missing", "cycle", "antikill", "filter", "risk",
        "morph", "killcheck", "correlation", "cold_tunnel", "hurst", "vote", "hot_freq"
    ]

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def __init__(self, root=None):
        """初始化主窗口

        Args:
            root: 可选的根窗口。为None时自动创建。
        """
        # ----- 创建根窗口 -----
        if root is None:
            if CTk_AVAILABLE:
                ctk.set_appearance_mode("dark")
                ctk.set_default_color_theme("blue")
                self.root = ctk.CTk()
            else:
                self.root = tk.Tk()
        else:
            self.root = root

        self.root.title("金水谣万物引擎")
        self.root.geometry("1400x900")
        self.root.minsize(1200, 800)
        self.root.configure(bg=ModernTheme.BG_DEEP)

        # ----- 主题状态 -----
        self.theme_mode = "dark"

        # ----- 初始化业务对象 -----
        self.fetcher = Fetcher()
        self.killer = Killer()
        self.evolve = Evolve()
        self.scheme_mgr = SchemeManager()
        self.schemes = self.scheme_mgr  # PredictionService 需要 schemes 参数

        # ----- 预测数据 -----
        self.preds = []
        self.reference_pool = []

        # ----- 线程安全 -----
        self._lock = threading.Lock()
        self.log_queue = queue.Queue()

        # ----- 引擎开关变量 (tc) -----
        self.tc = {}
        for eng in self.ENGINE_LIST:
            self.tc[eng] = tk.BooleanVar(value=True)

        # ----- 引擎状态字典（给 PredictionService 使用） -----
        self.engine_states = {eng: True for eng in self.ENGINE_LIST}

        # ----- BooleanVar 控制变量 -----
        self.cache_lock_var = tk.BooleanVar(value=False)
        self.budget_var = tk.BooleanVar(value=True)
        self.vote_var = tk.BooleanVar(value=False)
        self.debug_mode = tk.BooleanVar(value=False)

        # ----- 预算 -----
        self.max_budget = DEFAULT_MAX_BUDGET  # 默认149

        # ----- 热号窗口 -----
        self.hot_window = DEFAULT_HOT_WINDOW

        # ----- 玩法计划（3单+1复+1胆拖） -----
        self.play_plan = self._make_play_plan()

        # ----- 界面变量 -----
        self.lot_var = tk.StringVar(value=LOT_ALL[0] if LOT_ALL else "双色球")
        self.per_var = tk.StringVar()
        self.scheme_var = tk.StringVar(value="默认方案")
        self.budget_entry_var = tk.StringVar(value=str(self.max_budget))

        # ----- 加载数据 -----
        self.load_settings()
        self.load_preds()
        self.load_reference_pool()

        # ----- 构建 UI -----
        self.build_ui()

        # ----- 启动定时器 -----
        self.poll_log()
        self._update_time()

        # ----- 欢迎日志 -----
        self.log("金水谣万物引擎已启动")
        self.log(f"版本: {VERSION}")

    # ------------------------------------------------------------------
    # 日志系统
    # ------------------------------------------------------------------
    def log(self, msg, level='INFO'):
        """日志输出

        格式: [时间] 级别: 消息
        ERROR级别写入 error_YYYY-MM-DD.log
        消息放入 log_queue 供 poll_log 消费

        Args:
            msg: 日志消息
            level: 日志级别 (INFO/WARNING/ERROR/DEBUG)
        """
        now = datetime.datetime.now()
        timestamp = now.strftime('%H:%M:%S')
        line = f"[{timestamp}] {level}: {msg}"
        self.log_queue.put(line)

        # ERROR 级别写入错误日志文件
        if level == 'ERROR':
            try:
                os.makedirs(ERR_LOG_DIR, exist_ok=True)
                err_file = os.path.join(ERR_LOG_DIR, f"error_{now.strftime('%Y-%m-%d')}.log")
                with open(err_file, 'a', encoding='utf-8') as f:
                    f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {level}: {msg}\n")
            except Exception:
                pass

    def poll_log(self):
        """每200ms从log_queue取消息更新lb(Listbox)"""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if hasattr(self, 'lb') and self.lb:
                    self.lb.insert(tk.END, msg)
                    self.lb.see(tk.END)
                    # 限制日志条数，防止内存溢出
                    if self.lb.size() > 1000:
                        self.lb.delete(0, self.lb.size() - 500)
        except queue.Empty:
            pass
        self.root.after(200, self.poll_log)

    # ------------------------------------------------------------------
    # 验证方法
    # ------------------------------------------------------------------
    def _is_valid_period(self, lot, period):
        """检查期号是否有效

        Args:
            lot: 彩种名称
            period: 期号

        Returns:
            bool: 期号是否有效
        """
        try:
            p = int(period)
        except (ValueError, TypeError):
            return False
        from utils.number_utils import is_valid_period
        return is_valid_period(lot, p)

    def _validate_ticket(self, lot, nums_str):
        """验证号码格式

        支持: 双色球(红1-33蓝1-16), 大乐透(红1-35蓝1-12), 3D/排列3(0-9), 快乐8(1-80)

        Args:
            lot: 彩种名称
            nums_str: 号码字符串

        Returns:
            tuple: (is_valid: bool, error_msg: str)
        """
        if not nums_str:
            return False, "空号码"
        from utils.ticket_validator import validate_ticket
        return validate_ticket(lot, nums_str)

    # ------------------------------------------------------------------
    # 按钮状态控制
    # ------------------------------------------------------------------
    def set_btns_state(self, state):
        """批量设置操作按钮状态

        Args:
            state: tk.NORMAL 或 tk.DISABLED
        """
        btns = getattr(self, '_action_btns', [])
        for btn in btns:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 剪贴板操作
    # ------------------------------------------------------------------
    def _safe_copy(self, text):
        """安全复制到剪贴板

        优先使用 pyperclip，不可用时回退到 tkinter 剪贴板。

        Args:
            text: 要复制的文本
        """
        if not text:
            return
        try:
            if pyperclip:
                pyperclip.copy(text)
            else:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
        except Exception:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 表格行操作
    # ------------------------------------------------------------------
    def _select_all_rows(self):
        """全选表格行"""
        if not hasattr(self, 'tree'):
            return
        children = self.tree.get_children()
        for item in children:
            self.tree.selection_add(item)

    def _copy_selected_rows(self):
        """复制选中行（号码列）"""
        if not hasattr(self, 'tree'):
            return
        selected = self.tree.selection()
        if not selected:
            return
        lines = []
        for item in selected:
            vals = self.tree.item(item, 'values')
            if len(vals) >= 4:
                lines.append(str(vals[3]))  # 号码列
        self._safe_copy('\n'.join(lines))
        self.log(f"已复制 {len(lines)} 行号码")

    def _copy_selected_rows_full(self):
        """复制选中行（全部列）"""
        if not hasattr(self, 'tree'):
            return
        selected = self.tree.selection()
        if not selected:
            return
        lines = []
        for item in selected:
            vals = self.tree.item(item, 'values')
            lines.append('\t'.join(str(v) for v in vals))
        self._safe_copy('\n'.join(lines))
        self.log(f"已复制 {len(lines)} 行完整数据")

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------
    def _show_tree_context_menu(self, event):
        """显示表格右键菜单"""
        if not hasattr(self, 'tree'):
            return
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
        if not hasattr(self, '_tree_menu'):
            self._tree_menu = tk.Menu(self.root, tearoff=0)
            self._tree_menu.add_command(label="复制号码", command=self._copy_selected_rows)
            self._tree_menu.add_command(label="复制整行", command=self._copy_selected_rows_full)
            self._tree_menu.add_command(label="全选", command=self._select_all_rows)
        try:
            self._tree_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._tree_menu.grab_release()

    def _show_log_context_menu(self, event):
        """显示日志右键菜单"""
        if not hasattr(self, 'lb'):
            return
        if not hasattr(self, '_log_menu'):
            self._log_menu = tk.Menu(self.root, tearoff=0)
            self._log_menu.add_command(label="清空日志", command=self.clr_log)
            self._log_menu.add_command(label="复制选中", command=self._copy_log_selected)
        try:
            self._log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._log_menu.grab_release()

    def _copy_log_selected(self):
        """复制选中的日志内容"""
        if not hasattr(self, 'lb'):
            return
        try:
            selected = self.lb.curselection()
            if selected:
                lines = [self.lb.get(i) for i in selected]
                self._safe_copy('\n'.join(lines))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 主题切换
    # ------------------------------------------------------------------
    def toggle_theme(self):
        """切换 dark/light 主题"""
        if self.theme_mode == "dark":
            self.theme_mode = "light"
            if CTk_AVAILABLE:
                ctk.set_appearance_mode("light")
            self.root.configure(bg='#e5e7eb')
            self.log("已切换到浅色主题")
        else:
            self.theme_mode = "dark"
            if CTk_AVAILABLE:
                ctk.set_appearance_mode("dark")
            self.root.configure(bg=ModernTheme.BG_DEEP)
            self.log("已切换到深色主题")

    # ------------------------------------------------------------------
    # 清空日志
    # ------------------------------------------------------------------
    def clr_log(self):
        """清空日志"""
        if hasattr(self, 'lb') and self.lb:
            self.lb.delete(0, tk.END)
        self.log("日志已清空")

    # ------------------------------------------------------------------
    # 显示头奖概率
    # ------------------------------------------------------------------
    def show_prob(self, lot=None):
        """显示各彩种头奖概率

        Args:
            lot: 指定彩种。为None时显示全部。
        """
        probs = {
            "双色球": "1/17,721,088",
            "大乐透": "1/21,425,712",
            "福彩3D": "1/1,000",
            "排列三": "1/20,358,520",
            "七乐彩": "1/10,000,000",
            "快乐8": "选10中10: 1/8,911,711",
        }
        if lot and lot in probs:
            messagebox.showinfo("头奖概率", f"{lot}: {probs[lot]}")
        else:
            msg = "\n".join(f"{k}: {v}" for k, v in probs.items())
            messagebox.showinfo("各彩种头奖概率", msg)

    # ------------------------------------------------------------------
    # 预测面板刷新
    # ------------------------------------------------------------------
    def refresh_pred_panel(self):
        """刷新预测面板，从self.preds填充tree(Treeview)"""
        if not hasattr(self, 'tree'):
            return
        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)
        # 填充数据
        for p in self.preds:
            scheme = str(p.get("scheme", ""))
            lot = str(p.get("lot", ""))
            period = str(p.get("period", ""))
            nums = str(p.get("nums", ""))
            ptype = str(p.get("type", ""))
            date = str(p.get("date", ""))
            self.tree.insert("", tk.END, values=(scheme, lot, period, nums, ptype, date))

    # ------------------------------------------------------------------
    # 参考池管理
    # ------------------------------------------------------------------
    def load_reference_pool(self):
        """加载参考池"""
        try:
            data = safe_load_json(REFERENCE_CACHE, default=[])
            self.reference_pool = data if isinstance(data, list) else []
        except Exception:
            self.reference_pool = []

    def save_reference_pool(self):
        """保存参考池"""
        try:
            safe_write_json(REFERENCE_CACHE, self.reference_pool)
        except Exception as e:
            self.log(f"保存参考池失败: {e}", "ERROR")

    def add_to_pool(self, lot, period, nums):
        """添加到参考池

        Args:
            lot: 彩种名称
            period: 期号
            nums: 号码字符串
        """
        entry = {
            "lot": lot,
            "period": period,
            "nums": nums,
            "date": datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        self.reference_pool.append(entry)
        self.save_reference_pool()
        self.log(f"已添加到参考池: {lot} {nums}")

    # ------------------------------------------------------------------
    # 引擎设置管理
    # ------------------------------------------------------------------
    def load_settings(self):
        """加载引擎设置（从ENGINE_SET文件）"""
        try:
            settings = safe_load_json(ENGINE_SET, default={})
            if isinstance(settings, dict):
                for eng in self.ENGINE_LIST:
                    if eng in settings:
                        val = bool(settings[eng])
                        self.tc[eng].set(val)
                        self.engine_states[eng] = val
                if "max_budget" in settings:
                    self.max_budget = int(settings["max_budget"])
                    self.budget_entry_var.set(str(self.max_budget))
                if "hot_window" in settings:
                    self.hot_window = int(settings["hot_window"])
                if "vote" in settings:
                    self.vote_var.set(bool(settings["vote"]))
                if "debug_mode" in settings:
                    self.debug_mode.set(bool(settings["debug_mode"]))
        except Exception as e:
            self.log(f"加载设置失败: {e}", "WARNING")

    def save_settings(self):
        """保存引擎设置（到ENGINE_SET文件）"""
        try:
            settings = {}
            for eng in self.ENGINE_LIST:
                val = self.tc[eng].get()
                settings[eng] = val
                self.engine_states[eng] = val
            settings["max_budget"] = self.max_budget
            settings["hot_window"] = self.hot_window
            settings["vote"] = self.vote_var.get()
            settings["debug_mode"] = self.debug_mode.get()
            safe_write_json(ENGINE_SET, settings)
            self.log("引擎设置已保存")
        except Exception as e:
            self.log(f"保存设置失败: {e}", "ERROR")

    # ------------------------------------------------------------------
    # 预测数据加载/保存
    # ------------------------------------------------------------------
    def load_preds(self):
        """从PRED_CACHE加载预测"""
        try:
            data = safe_load_json(PRED_CACHE, default=[])
            self.preds = data if isinstance(data, list) else []
        except Exception:
            self.preds = []

    def save_preds(self):
        """保存预测到PRED_CACHE"""
        try:
            with preds_lock:
                safe_write_json(PRED_CACHE, self.preds)
        except Exception as e:
            self.log(f"保存预测失败: {e}", "ERROR")

    # ------------------------------------------------------------------
    # UI构建
    # ------------------------------------------------------------------
    def build_ui(self):
        """构建完整UI界面

        布局结构：
          顶部: logo + 标题 + 状态 + 时间
          控制栏: 彩种选择 + 期号 + 方案 + 引擎开关 + 预算 + 主题按钮
          操作按钮区: 生成预测、抓取数据、导入数据、热度统计、走势图、足彩、保存、清空日志
          预测表格Treeview
          底部日志区 + 公告栏
        """
        T = ModernTheme
        self._action_btns = []

        # ----- ttk 样式配置（暗色科技风） -----
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure("Treeview",
                        background=T.BG_CARD,
                        foreground=T.TEXT_PRIMARY,
                        fieldbackground=T.BG_CARD,
                        borderwidth=0,
                        font=(T.FONT_FAMILY, 10))
        style.configure("Treeview.Heading",
                        background=T.BG_ACTIVE,
                        foreground=T.TEXT_PRIMARY,
                        font=(T.FONT_FAMILY, 10, 'bold'))
        style.map("Treeview",
                  background=[('selected', T.COLOR_PRIMARY_DARK)],
                  foreground=[('selected', T.TEXT_PRIMARY)])
        style.configure("TCombobox",
                        fieldbackground=T.BG_INPUT,
                        background=T.BG_INPUT,
                        foreground=T.TEXT_PRIMARY)

        # ===== 1. 顶部标题栏 =====
        header = tk.Frame(self.root, bg=T.BG_CARD, height=60)
        header.pack(fill=tk.X, padx=8, pady=(8, 4))
        header.pack_propagate(False)

        # Logo图标
        logo_label = tk.Label(header, text="TS", font=(T.FONT_FAMILY, 20, 'bold'),
                              fg=T.COLOR_PRIMARY, bg=T.BG_CARD, width=3)
        logo_label.pack(side=tk.LEFT, padx=(16, 8))

        # 分隔线
        sep = tk.Frame(header, bg=T.COLOR_PRIMARY, width=2, height=36)
        sep.pack(side=tk.LEFT, padx=4, pady=12)

        # 标题 + 版本号
        title_frame = tk.Frame(header, bg=T.BG_CARD)
        title_frame.pack(side=tk.LEFT, padx=8)
        tk.Label(title_frame, text="金水谣万物引擎", font=(T.FONT_FAMILY, 16, 'bold'),
                 fg=T.TEXT_PRIMARY, bg=T.BG_CARD).pack(anchor='w')
        tk.Label(title_frame, text=VERSION[:40] + "..." if len(VERSION) > 40 else VERSION,
                 font=(T.FONT_FAMILY, 8), fg=T.TEXT_MUTED, bg=T.BG_CARD).pack(anchor='w')

        # 右侧：状态指示 + 时间
        right_frame = tk.Frame(header, bg=T.BG_CARD)
        right_frame.pack(side=tk.RIGHT, padx=16)

        self.status_label = tk.Label(right_frame, text="● 运行中", font=(T.FONT_FAMILY, 10),
                                     fg=T.SUCCESS, bg=T.BG_CARD)
        self.status_label.pack(side=tk.LEFT, padx=8)

        self.time_label = tk.Label(right_frame, text="", font=(T.FONT_FAMILY, 11),
                                   fg=T.COLOR_SECONDARY, bg=T.BG_CARD)
        self.time_label.pack(side=tk.RIGHT, padx=8)

        # 主题切换按钮
        theme_btn = tk.Button(right_frame, text="主题", font=(T.FONT_FAMILY, 9),
                              fg=T.TEXT_PRIMARY, bg=T.BG_HOVER, activebackground=T.BG_ACTIVE,
                              bd=0, padx=12, pady=4, cursor='hand2',
                              command=self.toggle_theme)
        theme_btn.pack(side=tk.RIGHT, padx=4)
        self._action_btns.append(theme_btn)

        # ===== 2. 控制栏 =====
        ctrl_frame = tk.Frame(self.root, bg=T.BG_DEEP)
        ctrl_frame.pack(fill=tk.X, padx=8, pady=4)

        # 第一行：彩种 + 期号 + 方案 + 预算 + 概率
        row1 = tk.Frame(ctrl_frame, bg=T.BG_DEEP)
        row1.pack(fill=tk.X, pady=2)

        tk.Label(row1, text="彩种:", font=(T.FONT_FAMILY, 10),
                 fg=T.TEXT_SECONDARY, bg=T.BG_DEEP).pack(side=tk.LEFT, padx=(4, 2))
        lot_combo = ttk.Combobox(row1, textvariable=self.lot_var, values=LOT_ALL,
                                 width=10, state='readonly', font=(T.FONT_FAMILY, 10))
        lot_combo.pack(side=tk.LEFT, padx=2)
        self._action_btns.append(lot_combo)

        tk.Label(row1, text="期号:", font=(T.FONT_FAMILY, 10),
                 fg=T.TEXT_SECONDARY, bg=T.BG_DEEP).pack(side=tk.LEFT, padx=(12, 2))
        per_entry = tk.Entry(row1, textvariable=self.per_var, width=12,
                             font=(T.FONT_FAMILY, 10), bg=T.BG_INPUT, fg=T.TEXT_PRIMARY,
                             insertbackground=T.TEXT_PRIMARY, bd=0, relief='flat')
        per_entry.pack(side=tk.LEFT, padx=2)
        self._action_btns.append(per_entry)

        tk.Label(row1, text="方案:", font=(T.FONT_FAMILY, 10),
                 fg=T.TEXT_SECONDARY, bg=T.BG_DEEP).pack(side=tk.LEFT, padx=(12, 2))
        scheme_entry = tk.Entry(row1, textvariable=self.scheme_var, width=12,
                                font=(T.FONT_FAMILY, 10), bg=T.BG_INPUT, fg=T.TEXT_PRIMARY,
                                insertbackground=T.TEXT_PRIMARY, bd=0, relief='flat')
        scheme_entry.pack(side=tk.LEFT, padx=2)
        self._action_btns.append(scheme_entry)

        tk.Label(row1, text="预算:", font=(T.FONT_FAMILY, 10),
                 fg=T.TEXT_SECONDARY, bg=T.BG_DEEP).pack(side=tk.LEFT, padx=(12, 2))
        budget_entry = tk.Entry(row1, textvariable=self.budget_entry_var, width=6,
                                font=(T.FONT_FAMILY, 10), bg=T.BG_INPUT, fg=T.TEXT_PRIMARY,
                                insertbackground=T.TEXT_PRIMARY, bd=0, relief='flat',
                                justify='center')
        budget_entry.pack(side=tk.LEFT, padx=2)
        budget_entry.bind('<Return>', lambda e: self._update_budget(self.budget_entry_var.get()))
        budget_entry.bind('<FocusOut>', lambda e: self._update_budget(self.budget_entry_var.get()))
        self._action_btns.append(budget_entry)

        tk.Label(row1, text=f"元 (上限{MAX_BUDGET_LIMIT})", font=(T.FONT_FAMILY, 8),
                 fg=T.TEXT_MUTED, bg=T.BG_DEEP).pack(side=tk.LEFT, padx=(2, 8))

        prob_btn = tk.Button(row1, text="概率", font=(T.FONT_FAMILY, 9),
                             fg=T.TEXT_PRIMARY, bg=T.BG_HOVER, activebackground=T.BG_ACTIVE,
                             bd=0, padx=10, pady=3, cursor='hand2',
                             command=self.show_prob)
        prob_btn.pack(side=tk.LEFT, padx=4)
        self._action_btns.append(prob_btn)

        # 投票模式复选框
        vote_cb = tk.Checkbutton(row1, text="多引擎投票", font=(T.FONT_FAMILY, 9),
                                 variable=self.vote_var, bg=T.BG_DEEP,
                                 fg=T.TEXT_SECONDARY, selectcolor=T.BG_INPUT,
                                 activebackground=T.BG_DEEP, activeforeground=T.TEXT_PRIMARY,
                                 bd=0)
        vote_cb.pack(side=tk.LEFT, padx=8)
        self._action_btns.append(vote_cb)

        # 调试模式复选框
        debug_cb = tk.Checkbutton(row1, text="调试", font=(T.FONT_FAMILY, 9),
                                  variable=self.debug_mode, bg=T.BG_DEEP,
                                  fg=T.TEXT_SECONDARY, selectcolor=T.BG_INPUT,
                                  activebackground=T.BG_DEEP, activeforeground=T.TEXT_PRIMARY,
                                  bd=0)
        debug_cb.pack(side=tk.LEFT, padx=4)
        self._action_btns.append(debug_cb)

        # ===== 3. 引擎开关区 =====
        eng_frame = tk.Frame(self.root, bg=T.BG_CARD)
        eng_frame.pack(fill=tk.X, padx=8, pady=4)

        tk.Label(eng_frame, text="引擎开关:", font=(T.FONT_FAMILY, 9, 'bold'),
                 fg=T.COLOR_PRIMARY, bg=T.BG_CARD).pack(side=tk.LEFT, padx=(8, 8), pady=6)

        eng_inner = tk.Frame(eng_frame, bg=T.BG_CARD)
        eng_inner.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=4)

        # 14个引擎复选框，分2行排列
        for i, eng in enumerate(self.ENGINE_LIST):
            row = i // 7
            col = i % 7
            eng_name = ENGINE_NAMES.get(eng, eng)
            cb = tk.Checkbutton(eng_inner, text=eng_name, font=(T.FONT_FAMILY, 9),
                                variable=self.tc[eng], bg=T.BG_CARD,
                                fg=T.TEXT_SECONDARY, selectcolor=T.BG_INPUT,
                                activebackground=T.BG_CARD, activeforeground=T.TEXT_PRIMARY,
                                bd=0)
            cb.grid(row=row, column=col, sticky='w', padx=6, pady=2)
            self._action_btns.append(cb)

        # ===== 4. 操作按钮区 =====
        btn_frame = tk.Frame(self.root, bg=T.BG_DEEP)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)

        btn_defs = [
            ("生成预测", T.COLOR_PRIMARY, self.gen_one),
            ("抓取数据", T.COLOR_ACCENT, self.fetch_all),
            ("导入数据", T.COLOR_SECONDARY, self.import_lottery_data),
            ("热度统计", T.COLOR_PURPLE, self.show_hot_stats),
            ("走势图", T.COLOR_PRIMARY_DARK, self.show_trend_chart),
            ("足彩", T.COLOR_RED, self._launch_football),
            ("保存", T.BG_ACTIVE, lambda: (self.save_settings(), self.save_preds())),
            ("清空日志", T.BG_HOVER, self.clr_log),
        ]
        for text, color, cmd in btn_defs:
            btn = tk.Button(btn_frame, text=text, font=(T.FONT_FAMILY, 10, 'bold'),
                            fg=T.TEXT_PRIMARY, bg=color, activebackground=T.BG_ACTIVE,
                            bd=0, padx=16, pady=6, cursor='hand2', command=cmd)
            btn.pack(side=tk.LEFT, padx=3)
            self._action_btns.append(btn)

        # 表格操作按钮（右侧）
        copy_btn = tk.Button(btn_frame, text="复制号码", font=(T.FONT_FAMILY, 9),
                             fg=T.TEXT_SECONDARY, bg=T.BG_HOVER, activebackground=T.BG_ACTIVE,
                             bd=0, padx=10, pady=6, cursor='hand2',
                             command=self._copy_selected_rows)
        copy_btn.pack(side=tk.RIGHT, padx=3)
        self._action_btns.append(copy_btn)

        select_all_btn = tk.Button(btn_frame, text="全选", font=(T.FONT_FAMILY, 9),
                                   fg=T.TEXT_SECONDARY, bg=T.BG_HOVER, activebackground=T.BG_ACTIVE,
                                   bd=0, padx=10, pady=6, cursor='hand2',
                                   command=self._select_all_rows)
        select_all_btn.pack(side=tk.RIGHT, padx=3)
        self._action_btns.append(select_all_btn)

        # ===== 5. 预测结果表格 =====
        table_frame = tk.Frame(self.root, bg=T.BG_DEEP)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        columns = ("scheme", "lot", "period", "nums", "type", "date")
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=12)

        # 列标题与宽度
        col_cfg = [
            ("scheme", "方案", 100),
            ("lot", "彩种", 80),
            ("period", "期号", 110),
            ("nums", "号码", 380),
            ("type", "类型", 70),
            ("date", "日期", 140),
        ]
        for col_id, col_title, col_width in col_cfg:
            self.tree.heading(col_id, text=col_title)
            self.tree.column(col_id, width=col_width, anchor=tk.CENTER)

        # 表格滚动条
        tree_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL,
                                    command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 双击查看详情
        self.tree.bind('<Double-1>', self._on_tree_double_click)
        # 右键菜单
        self.tree.bind('<Button-3>', self._show_tree_context_menu)

        # 填充已有数据
        self.refresh_pred_panel()

        # ===== 6. 底部日志区 + 公告栏 =====
        self._bottom_frame = tk.Frame(self.root, bg=T.BG_DEEP)
        self._bottom_frame.pack(fill=tk.BOTH, padx=8, pady=(4, 8))

        # 公告栏
        self.notice_visible = True
        self.notice_frame = tk.Frame(self._bottom_frame, bg=T.BG_CARD, height=60)
        self.notice_frame.pack(fill=tk.X, pady=(0, 4))
        self.notice_frame.pack_propagate(False)

        notice_header = tk.Frame(self.notice_frame, bg=T.BG_CARD)
        notice_header.pack(fill=tk.X, padx=8, pady=(4, 0))
        tk.Label(notice_header, text="📢 公告栏", font=(T.FONT_FAMILY, 9, 'bold'),
                 fg=T.COLOR_SECONDARY, bg=T.BG_CARD).pack(side=tk.LEFT)
        notice_btn_frame = tk.Frame(notice_header, bg=T.BG_CARD)
        notice_btn_frame.pack(side=tk.RIGHT)
        tk.Button(notice_btn_frame, text="清空", font=(T.FONT_FAMILY, 8),
                  fg=T.TEXT_MUTED, bg=T.BG_HOVER, bd=0, padx=6, cursor='hand2',
                  command=self.clear_notice_text).pack(side=tk.LEFT, padx=2)
        tk.Button(notice_btn_frame, text="隐藏", font=(T.FONT_FAMILY, 8),
                  fg=T.TEXT_MUTED, bg=T.BG_HOVER, bd=0, padx=6, cursor='hand2',
                  command=self.toggle_notice).pack(side=tk.LEFT, padx=2)

        self.notice_text = tk.Label(self.notice_frame, text="欢迎使用金水谣万物引擎",
                                    font=(T.FONT_FAMILY, 9), fg=T.TEXT_SECONDARY,
                                    bg=T.BG_CARD, anchor='w', justify=tk.LEFT)
        self.notice_text.pack(fill=tk.X, padx=8, pady=4)

        # 日志区
        self._log_frame = tk.Frame(self._bottom_frame, bg=T.BG_CARD)
        self._log_frame.pack(fill=tk.BOTH, expand=True)

        log_header = tk.Frame(self._log_frame, bg=T.BG_CARD)
        log_header.pack(fill=tk.X, padx=8, pady=(4, 0))
        tk.Label(log_header, text="系统日志", font=(T.FONT_FAMILY, 9, 'bold'),
                 fg=T.COLOR_PRIMARY, bg=T.BG_CARD).pack(side=tk.LEFT)

        # 日志列表
        log_inner = tk.Frame(self._log_frame, bg=T.BG_CARD)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.lb = tk.Listbox(log_inner, font=(T.FONT_FAMILY, 9),
                             bg=T.BG_INPUT, fg=T.TEXT_PRIMARY,
                             selectbackground=T.COLOR_PRIMARY_DARK,
                             selectforeground=T.TEXT_PRIMARY,
                             bd=0, height=8, activestyle='none')
        log_scroll = ttk.Scrollbar(log_inner, orient=tk.VERTICAL,
                                   command=self.lb.yview)
        self.lb.configure(yscrollcommand=log_scroll.set)
        self.lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb.bind('<Button-3>', self._show_log_context_menu)

    # ------------------------------------------------------------------
    # 双击查看详情
    # ------------------------------------------------------------------
    def _on_tree_double_click(self, event):
        """双击查看详情"""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        vals = self.tree.item(item, 'values')
        if not vals:
            return

        top = tk.Toplevel(self.root)
        top.title("预测详情")
        top.geometry("500x350")
        top.configure(bg=ModernTheme.BG_DEEP)
        top.transient(self.root)
        top.grab_set()

        T = ModernTheme
        labels = ["方案", "彩种", "期号", "号码", "类型", "日期"]
        for i, (label, val) in enumerate(zip(labels, vals)):
            tk.Label(top, text=f"{label}:", font=(T.FONT_FAMILY, 11, 'bold'),
                     fg=T.COLOR_PRIMARY, bg=T.BG_DEEP).grid(
                row=i, column=0, sticky='w', padx=20, pady=8)
            tk.Label(top, text=str(val), font=(T.FONT_FAMILY, 11),
                     fg=T.TEXT_PRIMARY, bg=T.BG_DEEP, wraplength=300, justify=tk.LEFT).grid(
                row=i, column=1, sticky='w', padx=10, pady=8)

        # 复制按钮
        tk.Button(top, text="复制号码", font=(T.FONT_FAMILY, 10),
                  fg=T.TEXT_PRIMARY, bg=T.COLOR_PRIMARY, bd=0, padx=20, pady=6,
                  cursor='hand2',
                  command=lambda: self._safe_copy(str(vals[3]))).grid(
            row=len(labels), column=0, columnspan=2, pady=16)

    # ------------------------------------------------------------------
    # 公告栏管理
    # ------------------------------------------------------------------
    def toggle_notice(self):
        """切换公告栏显示/隐藏"""
        if self.notice_visible:
            self.notice_frame.pack_forget()
            self.notice_visible = False
        else:
            self.notice_frame.pack(fill=tk.X, pady=(0, 4), before=self._log_frame)
            self.notice_visible = True

    def _find_log_frame(self):
        """查找日志区域frame用于公告栏位置定位（兼容方法）"""
        return getattr(self, '_log_frame', None)

    def clear_notice_text(self):
        """清空公告栏文字"""
        self.notice_text.config(text="")

    def update_notice(self, text):
        """更新公告栏内容

        Args:
            text: 公告内容
        """
        self.notice_text.config(text=str(text))

    # ------------------------------------------------------------------
    # 导入彩票数据
    # ------------------------------------------------------------------
    def import_lottery_data(self):
        """弹出导入窗口，用LotteryDataImporter.parse_and_save"""
        top = tk.Toplevel(self.root)
        top.title("导入开奖数据")
        top.geometry("600x450")
        top.configure(bg=ModernTheme.BG_DEEP)
        top.transient(self.root)
        top.grab_set()

        T = ModernTheme
        tk.Label(top, text="粘贴开奖数据文本（支持多种格式）", font=(T.FONT_FAMILY, 11, 'bold'),
                 fg=T.COLOR_PRIMARY, bg=T.BG_DEEP).pack(pady=8)

        text_area = scrolledtext.ScrolledText(top, font=(T.FONT_FAMILY, 10),
                                              bg=T.BG_INPUT, fg=T.TEXT_PRIMARY,
                                              insertbackground=T.TEXT_PRIMARY,
                                              bd=0, wrap=tk.WORD)
        text_area.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        result_label = tk.Label(top, text="", font=(T.FONT_FAMILY, 9),
                                fg=T.TEXT_SECONDARY, bg=T.BG_DEEP)
        result_label.pack(pady=4)

        def do_import():
            text = text_area.get("1.0", tk.END).strip()
            if not text:
                result_label.config(text="请先粘贴数据", fg=T.COLOR_RED)
                return
            try:
                imported, errors = LotteryDataImporter.parse_and_save(text)
                if imported > 0:
                    result_label.config(
                        text=f"成功导入 {imported} 条记录" +
                             (f"，{len(errors)} 条失败" if errors else ""),
                        fg=T.SUCCESS)
                    self.log(f"数据导入完成: 成功{imported}条, 失败{len(errors)}条")
                    Data.invalidate_cache()
                else:
                    result_label.config(text="未识别到有效数据", fg=T.COLOR_RED)
                    self.log("数据导入失败: 未识别到有效数据", "WARNING")
            except Exception as e:
                result_label.config(text=f"导入异常: {e}", fg=T.COLOR_RED)
                self.log(f"数据导入异常: {e}", "ERROR")

        tk.Button(top, text="解析并保存", font=(T.FONT_FAMILY, 10, 'bold'),
                  fg=T.TEXT_PRIMARY, bg=T.COLOR_PRIMARY, bd=0, padx=24, pady=8,
                  cursor='hand2', command=do_import).pack(pady=8)

    # ------------------------------------------------------------------
    # 热度统计
    # ------------------------------------------------------------------
    def show_hot_stats(self, lot=None):
        """显示近30期热度统计

        Args:
            lot: 指定彩种。为None时使用当前选择。
        """
        if lot is None:
            lot = self.lot_var.get()
        if not lot:
            messagebox.showwarning("提示", "请选择彩种")
            return

        arr = Data.load(lot)
        if not arr or len(arr) < 5:
            messagebox.showwarning("提示", f"{lot} 数据不足，无法统计")
            return

        # 取近30期
        recent = arr[-30:]
        from collections import Counter

        # 统计号码频率
        freq = Counter()
        rule = LOTTERY_RULES.get(lot, {})
        red_rule = rule.get("red", (0, 99))
        if isinstance(red_rule[0], tuple):
            rmin, rmax = 0, max(r[1] for r in red_rule)
        else:
            rmin, rmax = red_rule[0], red_rule[1]

        for d in recent:
            nums_str = str(d.get("nums", ""))
            reds_str = nums_str.split("+")[0] if "+" in nums_str else nums_str
            nums = [n for n in parse_reds(reds_str) if rmin <= n <= rmax]
            freq.update(nums)

        # 蓝球统计（如有）
        blue_freq = Counter()
        blue_rule = rule.get("blue")
        if blue_rule:
            bmin, bmax, _ = blue_rule
            for d in recent:
                nums_str = str(d.get("nums", ""))
                if "+" in nums_str:
                    blues = [n for n in parse_reds(nums_str.split("+")[1]) if bmin <= n <= bmax]
                    blue_freq.update(blues)

        # 创建统计窗口
        top = tk.Toplevel(self.root)
        top.title(f"{lot} 热度统计 (近{len(recent)}期)")
        top.geometry("550x500")
        top.configure(bg=ModernTheme.BG_DEEP)
        top.transient(self.root)

        T = ModernTheme
        tk.Label(top, text=f"{lot} 近{len(recent)}期热度统计", font=(T.FONT_FAMILY, 13, 'bold'),
                 fg=T.COLOR_PRIMARY, bg=T.BG_DEEP).pack(pady=8)

        # 热号 Top 10
        hot_nums = freq.most_common(10)
        hot_str = "  ".join(f"{n:02d}({c}次)" for n, c in hot_nums) if hot_nums else "无"
        tk.Label(top, text=f"热号 Top10:\n{hot_str}", font=(T.FONT_FAMILY, 10),
                 fg=T.COLOR_RED, bg=T.BG_DEEP, justify=tk.LEFT, anchor='w').pack(
            fill=tk.X, padx=20, pady=4)

        # 冷号 Bottom 10
        all_possible = list(range(rmin, rmax + 1))
        cold_nums = sorted(all_possible, key=lambda x: freq.get(x, 0))[:10]
        cold_str = "  ".join(f"{n:02d}({freq.get(n, 0)}次)" for n in cold_nums)
        tk.Label(top, text=f"冷号 Top10:\n{cold_str}", font=(T.FONT_FAMILY, 10),
                 fg=T.COLOR_PRIMARY, bg=T.BG_DEEP, justify=tk.LEFT, anchor='w').pack(
            fill=tk.X, padx=20, pady=4)

        # 蓝球统计
        if blue_freq:
            blue_hot = blue_freq.most_common(5)
            blue_str = "  ".join(f"{n:02d}({c}次)" for n, c in blue_hot)
            tk.Label(top, text=f"蓝球热号 Top5:\n{blue_str}", font=(T.FONT_FAMILY, 10),
                     fg=T.COLOR_SECONDARY, bg=T.BG_DEEP, justify=tk.LEFT, anchor='w').pack(
                fill=tk.X, padx=20, pady=4)

        # 近5期开奖
        tk.Label(top, text="近5期开奖:", font=(T.FONT_FAMILY, 10, 'bold'),
                 fg=T.TEXT_SECONDARY, bg=T.BG_DEEP, anchor='w').pack(
            fill=tk.X, padx=20, pady=(8, 2))
        for d in recent[-5:]:
            per = fmt_period(lot, d["period"])
            nums = format_display(lot, d.get("nums", ""))
            tk.Label(top, text=f"  第{per}期: {nums}", font=(T.FONT_FAMILY, 9),
                     fg=T.TEXT_PRIMARY, bg=T.BG_DEEP, anchor='w').pack(
                fill=tk.X, padx=20)

        self.log(f"已显示 {lot} 近{len(recent)}期热度统计")

    # ------------------------------------------------------------------
    # 预算更新
    # ------------------------------------------------------------------
    def _update_budget(self, value):
        """更新预算

        Args:
            value: 预算值字符串
        """
        try:
            budget = int(value)
            if budget < 2:
                budget = 2
                messagebox.showwarning("提示", "预算不能低于2元")
            if budget > MAX_BUDGET_LIMIT:
                budget = MAX_BUDGET_LIMIT
                messagebox.showwarning("提示", f"预算不能超过{MAX_BUDGET_LIMIT}元")
            self.max_budget = budget
            self.budget_entry_var.set(str(budget))
            self.log(f"预算已更新: {budget}元")
        except (ValueError, TypeError):
            self.budget_entry_var.set(str(self.max_budget))
            self.log("预算输入无效，已恢复默认值", "WARNING")

    # ------------------------------------------------------------------
    # 走势图
    # ------------------------------------------------------------------
    def show_trend_chart(self, lot=None):
        """显示走势图（matplotlib）

        Args:
            lot: 指定彩种。为None时使用当前选择。
        """
        if lot is None:
            lot = self.lot_var.get()
        if not lot:
            messagebox.showwarning("提示", "请选择彩种")
            return

        if not MATPLOTLIB_AVAILABLE:
            messagebox.showwarning("提示", "matplotlib 未安装，无法绘制走势图")
            self.log("matplotlib 不可用，走势图功能不可用", "WARNING")
            return

        arr = Data.load(lot)
        if not arr or len(arr) < 5:
            messagebox.showwarning("提示", f"{lot} 数据不足，无法绘制走势图")
            return

        # 取近50期
        recent = arr[-50:]
        rule = LOTTERY_RULES.get(lot, {})
        red_rule = rule.get("red", (0, 99))
        if isinstance(red_rule[0], tuple):
            rmin, rmax = 0, max(r[1] for r in red_rule)
        else:
            rmin, rmax = red_rule[0], red_rule[1]

        # 计算每期和值
        sums = []
        periods = []
        freq = {}
        for d in recent:
            nums_str = str(d.get("nums", ""))
            reds_str = nums_str.split("+")[0] if "+" in nums_str else nums_str
            nums = [n for n in parse_reds(reds_str) if rmin <= n <= rmax]
            sums.append(sum(nums))
            periods.append(d["period"])
            for n in nums:
                freq[n] = freq.get(n, 0) + 1

        # 创建图表
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7))
        fig.suptitle(f"{lot} 走势分析 (近{len(recent)}期)", fontsize=14, fontweight='bold')

        # 子图1: 和值走势
        ax1.plot(range(len(sums)), sums, color=ModernTheme.COLOR_PRIMARY,
                 linewidth=1.5, marker='o', markersize=3, label='和值')
        # 均线
        if len(sums) >= 5:
            ma5 = []
            for i in range(len(sums)):
                start = max(0, i - 4)
                ma5.append(sum(sums[start:i + 1]) / (i - start + 1))
            ax1.plot(range(len(sums)), ma5, color=ModernTheme.COLOR_SECONDARY,
                     linewidth=1.5, linestyle='--', label='MA5')
        ax1.set_title("和值走势", fontsize=11)
        ax1.set_xlabel("期数")
        ax1.set_ylabel("和值")
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)

        # 子图2: 号码频率
        sorted_freq = sorted(freq.items())
        nums_list = [f"{n:02d}" for n, _ in sorted_freq]
        counts_list = [c for _, c in sorted_freq]
        colors = [ModernTheme.COLOR_RED if c >= max(counts_list) * 0.7
                  else ModernTheme.COLOR_PRIMARY if c >= max(counts_list) * 0.4
                  else ModernTheme.TEXT_MUTED for c in counts_list]
        ax2.bar(nums_list, counts_list, color=colors, edgecolor='none')
        ax2.set_title("号码出现频率", fontsize=11)
        ax2.set_xlabel("号码")
        ax2.set_ylabel("出现次数")
        ax2.tick_params(axis='x', rotation=45, labelsize=7)
        ax2.grid(True, alpha=0.3, axis='y')

        plt.tight_layout()

        # 显示图表
        top = tk.Toplevel(self.root)
        top.title(f"{lot} 走势图")
        top.geometry("800x600")
        top.transient(self.root)

        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        canvas = FigureCanvasTkAgg(fig, master=top)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.log(f"已显示 {lot} 走势图")

    # ------------------------------------------------------------------
    # 启动足彩独立窗口
    # ------------------------------------------------------------------
    def _launch_football(self):
        """启动足彩独立窗口"""
        try:
            top = tk.Toplevel(self.root)
            top.title("金水谣足彩预测系统")
            top.geometry("1280x800")
            top.configure(bg=ModernTheme.BG_DEEP)

            from jinshuiyao.football_gui import FootballApp
            FootballApp(top)
            self.log("足彩窗口已启动")
        except ImportError:
            messagebox.showerror("错误", "足彩模块未安装")
            self.log("足彩模块导入失败", "ERROR")
        except Exception as e:
            messagebox.showerror("错误", f"启动足彩失败: {e}")
            self.log(f"启动足彩失败: {e}", "ERROR")

    # ------------------------------------------------------------------
    # 异步抓取数据
    # ------------------------------------------------------------------
    def fetch_all(self):
        """异步抓取所有彩种数据"""
        self.log("开始抓取数据...")
        self.set_btns_state('disabled')
        threading.Thread(target=self._fetch_job, daemon=True).start()

    def _fetch_job(self):
        """抓取数据工作线程"""
        lots = LOT_ALL if LOT_ALL else ["双色球", "大乐透", "福彩3D", "排列三", "七乐彩", "快乐8"]
        success_count = 0
        fail_count = 0
        for lot in lots:
            try:
                self.log(f"正在抓取 {lot}...")
                ok, data = self.fetcher.fetch(lot)
                if ok:
                    count = len(data) if data else 0
                    self.log(f"✅ {lot} 抓取成功，共 {count} 条记录")
                    success_count += 1
                    if self.fetcher.last_error:
                        self.log(f"   {self.fetcher.last_error}", "WARNING")
                else:
                    self.log(f"❌ {lot} 抓取失败", "WARNING")
                    fail_count += 1
            except Exception as e:
                self.log(f"❌ {lot} 抓取异常: {e}", "ERROR")
                fail_count += 1

        # 刷新缓存
        Data.invalidate_cache()
        self.log(f"数据抓取完成: 成功 {success_count} 个彩种, 失败 {fail_count} 个")
        self.set_btns_state('normal')

    # ------------------------------------------------------------------
    # 生成预测
    # ------------------------------------------------------------------
    def gen_one(self):
        """生成预测

        使用 PredictionService 生成预测，结果添加到 preds 和 tree。
        """
        lot = self.lot_var.get()
        if not lot:
            messagebox.showwarning("提示", "请选择彩种")
            return

        # 更新引擎状态
        for eng in self.ENGINE_LIST:
            self.engine_states[eng] = self.tc[eng].get()

        # 更新预算
        try:
            self.max_budget = int(self.budget_entry_var.get())
        except (ValueError, TypeError):
            self.max_budget = DEFAULT_MAX_BUDGET

        # 方案名
        scheme = self.scheme_var.get().strip() or "默认方案"

        # 期号
        per_value = self.per_var.get().strip() or None

        self.log(f"开始生成 {lot} 预测 (方案: {scheme})...")
        self.set_btns_state('disabled')

        def _do_gen():
            try:
                svc = PredictionService(
                    killer=self.killer,
                    evolve=self.evolve,
                    engine_states=self.engine_states,
                    hot_window=self.hot_window,
                    schemes=self.schemes,
                    on_log=self.log
                )
                result = svc.generate(
                    lot,
                    play_plan=self.play_plan,
                    scheme=scheme,
                    hot_window=self.hot_window,
                    per_value=per_value,
                    vote_value=self.vote_var.get()
                )

                if result["success"]:
                    # 添加到 preds 和 tree
                    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
                    per = result.get("period", "")
                    all_nums = result.get("all_nums", [])
                    for nums in all_nums:
                        entry = {
                            "scheme": scheme,
                            "lot": lot,
                            "period": per,
                            "nums": nums,
                            "type": "预测",
                            "date": now_str,
                            "reviewed": False,
                            "hits": 0
                        }
                        with self._lock:
                            self.preds.append(entry)

                    self.save_preds()
                    self.refresh_pred_panel()
                    self.log(f"✅ {lot} 预测生成完成，共 {len(all_nums)} 注")

                    # 自动添加到参考池
                    if all_nums:
                        self.add_to_pool(lot, per, all_nums[0])
                else:
                    err = result.get("error", "未知错误")
                    self.log(f"⚠️ {lot} 预测生成失败: {err}", "WARNING")
                    if err in ("无数据",):
                        self.log("请先抓取数据或导入数据", "INFO")

            except Exception as e:
                self.log(f"生成预测异常: {e}", "ERROR")
                import traceback
                self.log(traceback.format_exc(), "ERROR")
            finally:
                self.set_btns_state('normal')

        # 在线程中执行，避免阻塞UI
        threading.Thread(target=_do_gen, daemon=True).start()

    # ------------------------------------------------------------------
    # 玩法计划生成
    # ------------------------------------------------------------------
    def _make_play_plan(self, lot=None):
        """生成玩法计划（3单+1复+1胆拖）

        Args:
            lot: 彩种名称（可选，不同彩种可配置不同参数）

        Returns:
            list: 玩法计划列表
        """
        return [
            {"type": "单注", "count": 3, "config": {}},
            {"type": "复式", "count": 1, "config": {}},
            {"type": "胆拖", "count": 1, "config": {}},
        ]

    # ------------------------------------------------------------------
    # 时间更新
    # ------------------------------------------------------------------
    def _update_time(self):
        """每秒更新顶部时间显示"""
        if hasattr(self, 'time_label') and self.time_label:
            now = datetime.datetime.now()
            self.time_label.config(text=now.strftime('%Y-%m-%d %H:%M:%S'))
        self.root.after(1000, self._update_time)

    # ------------------------------------------------------------------
    # mainloop 代理
    # ------------------------------------------------------------------
    def mainloop(self):
        """启动主事件循环"""
        self.root.mainloop()


# ==================== 入口 ====================
if __name__ == '__main__':
    app = App()
    app.mainloop()
