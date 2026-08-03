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
import time
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

# ==================== 预测表格列配置（单一事实来源，防止 columns 与 col_cfg 失配） ====================
# 每个元组: (列ID, 列标题, 列宽)。Treeview 的 columns 元组与表头循环均由此派生。
PRED_TABLE_COLUMNS = (
    ("period", "期号", 100),
    ("lot", "彩种", 70),
    ("nums", "号码", 300),
    ("type", "类型", 60),
    ("scheme", "方案", 90),
    ("confidence", "SQI", 50),
    ("hits", "命中", 50),
    ("coverage", "覆盖度", 60),
    ("status", "状态", 70),
    ("date", "日期", 130),
)

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
from utils.number_utils import clean_nums, parse_reds, fmt_period, format_display, get_today_lots
from importers.lottery_data_importer import LotteryDataImporter

# Phase1 拆出模块导入
from gui.ticket_utils import detect_3d_type as _detect_3d_type, is_valid_period as _is_valid_period_ext, validate_ticket as _validate_ticket_ext
from gui.play_plans import PLAY_PLANS as _PLAY_PLANS, DEFAULT_PLAY_PLAN as _DEFAULT_PLAY_PLAN, make_play_plan as _make_play_plan_ext, LOTTERY_PROBS as _LOTTERY_PROBS
from gui.data_store import (load_preds_data as _load_preds_data, save_preds_data as _save_preds_data,
                             load_reference_pool_data as _load_ref_pool_data, save_reference_pool_data as _save_ref_pool_data,
                             add_to_pool_data as _add_to_pool_data,
                             load_settings_data as _load_settings_data, save_settings_data as _save_settings_data)


# ==================== 金水谣 · 七色暗色体系主题配置 ====================
class ModernTheme:
    """金水谣七色暗色体系 — 与 workbench.html / theme.css / Ardot 画布完全对齐

    核心四色（占 ~96%）：
      深海墨蓝 #0B1A2F  ·  深蓝灰 #162840  ·  暖银白 #E8ECF1  ·  香槟金 #C9A96E
    功能三辅色（占 ~4%）：
      冰水蓝 #5BC0DE   ·  墨绿金 #2D8B7E   ·  赤铜 #C8755A
    绝对禁用：红 / 橙 / 黄 / 棕 / 绿(非墨绿金) / 紫 / 粉 / 灰紫
    """

    # ── 核心四色 ──
    DEEP = '#0B1A2F'            # 深海墨蓝 · 主背景（画布）
    CARD_BG = '#162840'         # 深蓝灰 · 卡片/区块/侧栏
    INK = '#E8ECF1'             # 暖银白 · 主文字
    GOLD = '#C9A96E'            # 香槟金 · 强调/按钮/边框

    # ── 功能三辅色 ──
    ICE = '#5BC0DE'             # 冰水蓝 · 数据/链接/交互
    JADE = '#2D8B7E'            # 墨绿金 · 成功/盈利/正向
    COPPER = '#C8755A'          # 赤铜 · 警示/亏损/开发中

    # ── 层次衍生（半透明变体 → tkinter实色近似，底色#0B1A2F）──
    INK_DIM = '#858e9a'         # 银白暗（次要文字）
    INK_MID = '#a6adb7'         # 银白中
    INK_FAINT = '#5f6a79'       # 银白极淡
    GOLD_SOFT = '#222b37'       # 金色淡底
    GOLD_BORDER = '#2d343a'     # 金色淡边框
    GOLD_GLOW = '#33393f'       # 金色光晕
    ICE_SOFT = '#152e44'        # 冰蓝淡底
    JADE_SOFT = '#0f2838'       # 墨绿金淡底
    COPPER_SOFT = '#222534'     # 赤铜淡底

    # ── 背景色（兼容旧引用名）──
    BG_DEEP = DEEP              # 主背景
    BG_CARD = CARD_BG           # 卡片/区块
    BG_HOVER = '#1e3048'        # 悬停态（比 CARD_BG 稍亮）
    BG_INPUT = '#0f2035'        # 输入框（实色近似）
    BG_ACTIVE = '#1a3350'       # 激活态（带金调）

    # ── 文字色（兼容旧引用名）──
    TEXT_PRIMARY = INK          # 主文字
    TEXT_SECONDARY = INK_DIM    # 次要文字
    TEXT_MUTED = INK_FAINT      # 弱化文字

    # ── 功能色（七色映射，兼容旧引用名）──
    COLOR_PRIMARY = ICE         # 主操作色 → 冰蓝（数据/交互语义）
    COLOR_PRIMARY_DARK = '#4ABBD8'  # 主操作深色 → 冰蓝亮
    COLOR_SECONDARY = GOLD      # 次要强调 → 香槟金
    COLOR_ACCENT = JADE         # 强调色 → 墨绿金（成功正向）
    COLOR_PURPLE = ICE          # 紫色禁用 → 映射冰蓝
    COLOR_RED = COPPER          # 红色禁用 → 映射赤铜（警示）
    COLOR_PINK = COPPER_SOFT    # 粉色禁用 → 映射赤铜淡
    COLOR_AMBER = GOLD          # 琥珀/橙 → 映射香槟金
    SUCCESS = JADE              # 成功 → 墨绿金
    WARN = '#907e5b'            # 警告 → 金色调
    ERR = COPPER                # 错误 → 赤铜

    # ── 边框 ──
    BORDER = GOLD_BORDER        # 统一边框 → 金色淡边框

    # ── 字体与圆角 ──
    FONT_FAMILY = 'Microsoft YaHei'
    CORNER_RADIUS = 8
    CORNER_RADIUS_SMALL = 6
    CORNER_RADIUS_LARGE = 12


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

        # 智能大脑 & 进化引擎（复盘学习用）
        try:
            from engines.smart_brain import SmartBrain
            self.brain = SmartBrain()
        except Exception:
            self.brain = None
        try:
            from engines.evolution import EvolutionManager
            self.evolution_mgr = EvolutionManager()
        except Exception:
            self.evolution_mgr = None

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
        """检查期号是否有效（薄委托）"""
        return _is_valid_period_ext(lot, period)

    def _validate_ticket(self, lot, nums_str):
        """验证号码格式（薄委托）"""
        return _validate_ticket_ext(lot, nums_str)

    # ------------------------------------------------------------------
    # 按钮状态控制
    # ------------------------------------------------------------------
    def set_btns_state(self, state):
        """批量设置操作按钮状态（线程安全，可从工作线程调用）

        Args:
            state: 'normal' 或 'disabled'
        """
        def _apply():
            btns = getattr(self, '_action_btns', [])
            for btn in btns:
                try:
                    btn.configure(state=state)
                except Exception:
                    pass
        try:
            self.root.after(0, _apply)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 剪贴板操作
    # ------------------------------------------------------------------
    def _safe_copy(self, text):
        """安全复制到剪贴板（大文本防卡 JS-20260804-04）

        优先使用 pyperclip，不可用时回退到 tkinter 剪贴板。
        一次性复制超过 _COPY_CAP 字符时自动截断并提示（避免粘贴端卡死，
        例如把整库 1700+ 行一次 Ctrl+A+C 粘进聊天框导致卡掉）。

        Args:
            text: 要复制的文本
        """
        if not text:
            return
        cap = getattr(self, '_COPY_CAP', 200_000)
        original_len = len(text)
        if original_len > cap:
            text = text[:cap]
            self.log(f"⚠️ 复制内容过大({original_len:,}字符)，已截取前{cap:,}字符防止卡顿")
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
            if len(vals) >= 3:
                lines.append(str(vals[2]))  # 号码列（新列序：期号/彩种/号码/...）
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

    def _tree_select_all(self, event=None):
        """Ctrl+A：全选预测表格行"""
        self._select_all_rows()
        return "break"

    # ── 鼠标拖拽连选（Treeview 原生不支持，手动实现 JS-20260804-04）
    # 关键点：按住左键后 tk 会把 Motion/Release 持续派发给按下时的控件，
    # 所以指针拖出控件边缘也不会"断链"；拖出上/下边界时自动滚动列表
    # 并继续延伸选择范围（原生 autoscroll 被 return "break" 拦掉后需自己实现）。
    def _tree_drag_start(self, event):
        """按下左键：记录起始行并单选该行"""
        if not hasattr(self, 'tree'):
            return
        self.tree.focus_set()  # 拖拽 handler 返回 break 会跳过类级焦点绑定，需显式聚焦（JS-20260804-06）
        if getattr(self, '_tree_drag_scroll_job', None) is not None:
            self.root.after_cancel(self._tree_drag_scroll_job)
        self._tree_drag_scroll_job = None
        item = self.tree.identify_row(event.y)
        self._tree_drag_anchor = item or ""
        self._tree_drag_active = bool(item)
        self._tree_drag_last_item = None
        if item:
            if event.state & 0x0004:  # Ctrl：追加
                self.tree.selection_add(item)
            else:
                self.tree.selection_set(item)
        return "break"

    def _tree_drag_step(self, y, state):
        """按指针在控件内的 y 更新选择范围（Motion 与自动滚动共用）"""
        if not getattr(self, '_tree_drag_active', False):
            return
        anchor = self._tree_drag_anchor
        if not anchor:
            return
        children = list(self.tree.get_children())
        if not children or anchor not in children:
            return
        h = self.tree.winfo_height()
        if y < 0:
            item = self.tree.identify_row(0)      # 越顶：第一可视行
        elif y >= h:
            item = self.tree.identify_row(h - 1)  # 越底：最后可视行
        else:
            item = self.tree.identify_row(y)
        if not item or item not in children:
            return
        a, b = children.index(anchor), children.index(item)
        block = children[min(a, b):max(a, b) + 1]
        if state & 0x0004:  # Ctrl：追加到现有选择
            keep = {iid for iid in self.tree.selection()}
            keep.update(block)
            self.tree.selection_set(list(keep))
        else:
            self.tree.selection_set(block)
        self._tree_drag_last_item = item

    def _tree_drag_extend(self, event):
        """拖动：跟随指针连选"""
        if not getattr(self, '_tree_drag_active', False):
            return
        self._tree_drag_step(event.y, event.state)
        return "break"

    def _tree_drag_motion(self, event):
        """拖动：跟随指针 + 拖出边界自动滚动"""
        if not getattr(self, '_tree_drag_active', False):
            return
        self._tree_drag_step(event.y, event.state)
        self._tree_drag_maybe_scroll(event.y, event.state)
        return "break"

    def _tree_drag_maybe_scroll(self, y, state):
        """指针越界时启动自动滚动（40ms 一格，滚动中继续延伸选择）"""
        if not getattr(self, '_tree_drag_active', False):
            return
        h = self.tree.winfo_height()
        if y < 0 or y >= h:
            if self._tree_drag_scroll_job is None:
                self._tree_drag_scroll_dir = -1 if y < 0 else 1
                self._tree_drag_scroll_state = state
                self._tree_drag_scroll_tick()
        elif self._tree_drag_scroll_job is not None:
            self.root.after_cancel(self._tree_drag_scroll_job)
            self._tree_drag_scroll_job = None

    def _tree_drag_scroll_tick(self):
        """自动滚动一格，滚动后按指针位置继续延伸选择"""
        if not getattr(self, '_tree_drag_active', False):
            self._tree_drag_scroll_job = None
            return
        before = self.tree.yview()
        self.tree.yview_scroll(self._tree_drag_scroll_dir * 3, "units")
        if self.tree.yview() == before:  # 已滚到边界
            self._tree_drag_scroll_job = None
            return
        x, y = self.tree.winfo_pointerxy()
        ry = y - self.tree.winfo_rooty()
        h = self.tree.winfo_height()
        if (self._tree_drag_scroll_dir < 0 and ry >= 0) or (self._tree_drag_scroll_dir > 0 and ry < h):
            self._tree_drag_scroll_job = None
            return
        self._tree_drag_step(ry, self._tree_drag_scroll_state)
        self._tree_drag_scroll_job = self.root.after(40, self._tree_drag_scroll_tick)

    def _tree_drag_end(self, event):
        """松开左键：清理拖拽状态"""
        if getattr(self, '_tree_drag_scroll_job', None) is not None:
            self.root.after_cancel(self._tree_drag_scroll_job)
        self._tree_drag_scroll_job = None
        self._tree_drag_active = False
        self._tree_drag_anchor = ""
        return None

    def _tree_copy_full(self, event=None):
        """Ctrl+C：复制选中行完整数据"""
        self._copy_selected_rows_full()
        return "break"

    def _log_select_all(self, event=None):
        """Ctrl+A：全选日志内容"""
        if not hasattr(self, 'lb'):
            return "break"
        size = self.lb.size()
        if size:
            self.lb.selection_set(0, size - 1)
        return "break"

    def _root_ctrl_a(self, event=None):
        """根级 Ctrl+A 兜底：焦点在表格/日志时全选，否则放行（JS-20260804-06）"""
        w = self.root.focus_get()
        if w is self.tree:
            return self._tree_select_all()
        if w is self.lb:
            return self._log_select_all()
        return None

    def _root_ctrl_c(self, event=None):
        """根级 Ctrl+C 兜底：焦点在表格/日志时复制，否则放行（JS-20260804-06）"""
        w = self.root.focus_get()
        if w is self.tree:
            return self._tree_copy_full()
        if w is self.lb:
            return self._log_copy_selected()
        return None

    # ── 鼠标拖拽连选（Listbox 原生不支持，手动实现 JS-20260804-04） ──
    def _log_drag_start(self, event):
        """按下左键：记录起始索引"""
        if not hasattr(self, 'lb'):
            return
        self.lb.focus_set()  # 拖拽 handler 返回 break 会跳过类级焦点绑定，需显式聚焦（JS-20260804-06）
        if getattr(self, '_log_drag_scroll_job', None) is not None:
            self.root.after_cancel(self._log_drag_scroll_job)
        self._log_drag_scroll_job = None
        size = self.lb.size()
        if size == 0:
            return
        idx = max(0, min(self.lb.nearest(event.y), size - 1))
        self._log_drag_anchor = idx
        self._log_drag_active = True
        self._log_drag_prev = [idx]
        if event.state & 0x0004:
            self.lb.selection_set(idx)
        else:
            self.lb.selection_clear(0, size - 1)
            self.lb.selection_set(idx)
        return "break"

    def _log_drag_step(self, y, state):
        """按指针在控件内的 y 更新选择范围（Motion 与自动滚动共用）"""
        if not getattr(self, '_log_drag_active', False) or self._log_drag_anchor is None:
            return
        size = self.lb.size()
        if size == 0:
            return
        h = self.lb.winfo_height()
        if y < 0:
            idx = 0            # 越顶：第一项
        elif y >= h:
            idx = size - 1     # 越底：最后一项
        else:
            idx = max(0, min(self.lb.nearest(y), size - 1))
        lo, hi = min(self._log_drag_anchor, idx), max(self._log_drag_anchor, idx)
        if state & 0x0004:  # Ctrl：保留既有选择再追加
            keep = set(self._log_drag_prev)
            keep.update(range(lo, hi + 1))
            self.lb.selection_clear(0, size - 1)
            for i in sorted(keep):
                if 0 <= i < size:
                    self.lb.selection_set(i)
            self._log_drag_prev = sorted(keep)
        else:
            self.lb.selection_clear(0, size - 1)
            self.lb.selection_set(lo, hi)
            self._log_drag_prev = list(range(lo, hi + 1))

    def _log_drag_extend(self, event):
        """拖动：从起始索引到当前索引连选"""
        if not getattr(self, '_log_drag_active', False):
            return
        self._log_drag_step(event.y, event.state)
        return "break"

    def _log_drag_motion(self, event):
        """拖动：跟随指针 + 拖出边界自动滚动"""
        if not getattr(self, '_log_drag_active', False):
            return
        self._log_drag_step(event.y, event.state)
        self._log_drag_maybe_scroll(event.y, event.state)
        return "break"

    def _log_drag_maybe_scroll(self, y, state):
        """指针越界时启动自动滚动"""
        if not getattr(self, '_log_drag_active', False):
            return
        h = self.lb.winfo_height()
        if y < 0 or y >= h:
            if self._log_drag_scroll_job is None:
                self._log_drag_scroll_dir = -1 if y < 0 else 1
                self._log_drag_scroll_state = state
                self._log_drag_scroll_tick()
        elif self._log_drag_scroll_job is not None:
            self.root.after_cancel(self._log_drag_scroll_job)
            self._log_drag_scroll_job = None

    def _log_drag_scroll_tick(self):
        """自动滚动一格，滚动后按指针位置继续延伸选择"""
        if not getattr(self, '_log_drag_active', False):
            self._log_drag_scroll_job = None
            return
        before = self.lb.yview()
        self.lb.yview_scroll(self._log_drag_scroll_dir * 3, "units")
        if self.lb.yview() == before:  # 已滚到边界
            self._log_drag_scroll_job = None
            return
        x, y = self.lb.winfo_pointerxy()
        ry = y - self.lb.winfo_rooty()
        h = self.lb.winfo_height()
        if (self._log_drag_scroll_dir < 0 and ry >= 0) or (self._log_drag_scroll_dir > 0 and ry < h):
            self._log_drag_scroll_job = None
            return
        self._log_drag_step(ry, self._log_drag_scroll_state)
        self._log_drag_scroll_job = self.root.after(40, self._log_drag_scroll_tick)

    def _log_drag_end(self, event):
        """松开左键：清理拖拽状态"""
        if getattr(self, '_log_drag_scroll_job', None) is not None:
            self.root.after_cancel(self._log_drag_scroll_job)
        self._log_drag_scroll_job = None
        self._log_drag_active = False
        self._log_drag_anchor = None
        self._log_drag_prev = []
        return None

    def _log_copy_selected(self, event=None):
        """Ctrl+C：复制选中日志"""
        self._copy_log_selected()
        return "break"

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
            self._log_menu.add_command(label="全选", command=self._log_select_all)
            self._log_menu.add_command(label="复制选中", command=self._copy_log_selected)
            self._log_menu.add_command(label="复制全部", command=self._copy_log_all)
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

    def _copy_log_all(self):
        """复制全部日志内容（右键菜单/兜底用，JS-20260804-06）"""
        if not hasattr(self, 'lb'):
            return
        try:
            size = self.lb.size()
            if size:
                lines = [self.lb.get(i) for i in range(size)]
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
            self.root.configure(bg='#e8e4d9')  # 浅色：暖灰调（非冷灰）
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
        """显示各彩种头奖概率（薄委托，messagebox留在GUI层）"""
        probs = _LOTTERY_PROBS
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
        T = ModernTheme
        # 配置行标签样式（七色暗色体系）
        self.tree.tag_configure('odd', background='#0c1a2e')  # 奇数行：深海墨蓝变体
        self.tree.tag_configure('even', background=T.BG_CARD)  # 偶数行：深蓝灰
        self.tree.tag_configure('reviewed', foreground=T.JADE)  # 已复盘：墨绿金
        self.tree.tag_configure('pending', foreground=T.GOLD)   # 待复盘：香槟金
        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)
        # 填充数据（列顺序：期号/彩种/号码/类型/方案/SQI/命中/覆盖度/状态/日期）
        for idx, p in enumerate(self.preds):
            period = str(p.get("period", ""))
            lot = str(p.get("lot", ""))
            nums = str(p.get("nums", ""))
            ptype = str(p.get("type", ""))
            scheme = str(p.get("scheme", ""))
            sqi = str(p.get("confidence", "-"))
            hits = p.get("hits", "")
            hits_str = str(hits) if hits != "" else "-"
            coverage = p.get("coverage")
            cov_str = f"{coverage*100:.0f}%" if coverage is not None else "-"
            reviewed = p.get("reviewed", False)
            status = "已复盘" if reviewed else "待复盘"
            date = str(p.get("date", ""))
            row_tag = 'odd' if idx % 2 == 0 else 'even'
            status_tag = 'reviewed' if reviewed else 'pending'
            self.tree.insert("", tk.END, values=(period, lot, nums, ptype, scheme, sqi, hits_str, cov_str, status, date),
                             tags=(row_tag, status_tag))
        # 更新命中率统计
        self._update_hit_stats()

    def _update_hit_stats(self):
        """计算并显示命中率统计"""
        if not hasattr(self, '_stats_label'):
            return
        reviewed = [p for p in self.preds if p.get("reviewed")]
        if not reviewed:
            self._stats_label.config(text="命中率统计：暂无复盘数据（预测后点\"复盘\"按钮）")
            return
        # 总体统计
        total = len(reviewed)
        # 组选命中率（任意1+码中 / 任意奖级命中）—— 与看板"组选"口径一致
        group_hit = sum(1 for p in reviewed if p.get("hits", 0) > 0)
        group_rate = group_hit / total * 100 if total else 0
        # 直选命中率（位置精确）—— 仅对 3D/排列三等有直选概念的彩种；历史无 hit_type 则降级不计入
        direct_total = 0
        direct_hit = 0
        for p in reviewed:
            lot = p.get("lot", "")
            if lot not in ("福彩3D", "排列三"):
                continue
            ht = p.get("hit_type")
            if ht is None:
                continue  # 历史数据无明细，不计入直选分母避免虚高/虚低
            direct_total += 1
            if ht == "直选":
                direct_hit += 1
        direct_rate = direct_hit / direct_total * 100 if direct_total else None
        # 按彩种分组（组选级）
        lot_stats = {}
        for p in reviewed:
            lot = p.get("lot", "?")
            if lot not in lot_stats:
                lot_stats[lot] = {"total": 0, "hit": 0}
            lot_stats[lot]["total"] += 1
            if p.get("hits", 0) > 0:
                lot_stats[lot]["hit"] += 1
        # 平均复式覆盖度（命中号码数 / 开奖号码总数）—— JS-20260724-03
        cov_vals = [p.get("coverage") for p in reviewed if p.get("coverage") is not None]
        avg_cov = sum(cov_vals) / len(cov_vals) if cov_vals else None
        # 组装文本（三口径：组选 + 直选 + 覆盖度，与彩票看板统一）
        parts = [f"组选命中率 {group_rate:.1f}%"]
        if direct_rate is not None:
            parts.append(f"直选命中率 {direct_rate:.1f}%")
        else:
            parts.append("直选命中率 历史无明细")
        if avg_cov is not None:
            parts.append(f"平均覆盖度 {avg_cov*100:.1f}%")
        for lot, s in sorted(lot_stats.items(), key=lambda x: -x[1]["total"])[:4]:
            lot_rate = s["hit"] / s["total"] * 100 if s["total"] else 0
            parts.append(f"{lot} {lot_rate:.0f}%")
        self._stats_label.config(text="  |  ".join(parts))

    # ------------------------------------------------------------------
    # 参考池管理
    # ------------------------------------------------------------------
    def load_reference_pool(self):
        """加载参考池（薄委托）"""
        self.reference_pool = _load_ref_pool_data()

    def save_reference_pool(self):
        """保存参考池（薄委托）"""
        _save_ref_pool_data(self.reference_pool)

    def add_to_pool(self, lot, period, nums):
        """添加到参考池（薄委托）
        """
        self.reference_pool = _add_to_pool_data(self.reference_pool, lot, period, nums)
        self.save_reference_pool()
        self.log(f"已添加到参考池: {lot} {nums}")

    # ------------------------------------------------------------------
    # 引擎设置管理
    # ------------------------------------------------------------------
    def load_settings(self):
        """加载引擎设置（从ENGINE_SET文件，数据读取用薄委托，tk变量同步留在GUI层）"""
        try:
            settings = _load_settings_data(self.ENGINE_LIST)
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
        """保存引擎设置（到ENGINE_SET文件，数据写入用薄委托，tk变量读取留在GUI层）"""
        try:
            engine_states = {}
            for eng in self.ENGINE_LIST:
                val = self.tc[eng].get()
                engine_states[eng] = val
                self.engine_states[eng] = val
            _save_settings_data(engine_states, self.ENGINE_LIST, self.max_budget,
                                self.hot_window, self.vote_var.get(), self.debug_mode.get())
            self.log("引擎设置已保存")
        except Exception as e:
            self.log(f"保存设置失败: {e}", "ERROR")

    # ------------------------------------------------------------------
    # 预测数据加载/保存
    # ------------------------------------------------------------------
    def load_preds(self):
        """从PRED_CACHE加载预测（薄委托）"""
        self.preds = _load_preds_data()

    def save_preds(self):
        """保存预测到PRED_CACHE（薄委托）"""
        _save_preds_data(self.preds)

    # ------------------------------------------------------------------
    # UI构建
    # ------------------------------------------------------------------
    def build_ui(self):
        """构建完整UI界面（子方法调度）

        布局结构：
          顶部: logo + 标题 + 状态 + 时间
          控制栏: 彩种选择 + 期号 + 方案 + 引擎开关 + 预算 + 主题按钮
          操作按钮区: 生成预测、抓取数据、导入数据、热度统计、走势图、足彩、保存、清空日志
          预测表格Treeview
          底部日志区 + 公告栏
        """
        self._action_btns = []
        self._build_styles()
        self._build_header()
        self._build_control_bar()
        self._build_engine_switches()
        self._build_action_buttons()
        self._build_table()
        self._build_log_area()

    # ------------------------------------------------------------------
    # UI子方法（全部留在类内，零风险结构优化）
    # ------------------------------------------------------------------
    def _build_styles(self):
        """ttk 样式配置（暗色科技风）"""
        T = ModernTheme
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
                        rowheight=26,
                        font=(T.FONT_FAMILY, 10))
        style.configure("Treeview.Heading",
                        background=T.BG_ACTIVE,
                        foreground=T.TEXT_PRIMARY,
                        font=(T.FONT_FAMILY, 10, 'bold'))
        style.map("Treeview",
                  background=[('selected', '#1a3a4a')],
                  foreground=[('selected', T.TEXT_PRIMARY)])
        style.configure("TCombobox",
                        fieldbackground=T.BG_INPUT,
                        background=T.BG_INPUT,
                        foreground=T.TEXT_PRIMARY)

    def _build_header(self):
        """顶部标题栏"""
        T = ModernTheme
        header = tk.Frame(self.root, bg=T.BG_CARD, height=60)
        header.pack(fill=tk.X, padx=8, pady=(8, 4))
        header.pack_propagate(False)

        logo_label = tk.Label(header, text="TS", font=(T.FONT_FAMILY, 20, 'bold'),
                              fg=T.GOLD, bg=T.BG_CARD, width=3)
        logo_label.pack(side=tk.LEFT, padx=(16, 8))

        sep = tk.Frame(header, bg='#3d5a4a', width=2, height=36)
        sep.pack(side=tk.LEFT, padx=4, pady=12)

        title_frame = tk.Frame(header, bg=T.BG_CARD)
        title_frame.pack(side=tk.LEFT, padx=8)
        tk.Label(title_frame, text="金水谣万物引擎", font=(T.FONT_FAMILY, 16, 'bold'),
                 fg=T.TEXT_PRIMARY, bg=T.BG_CARD).pack(anchor='w')
        tk.Label(title_frame, text=VERSION[:40] + "..." if len(VERSION) > 40 else VERSION,
                 font=(T.FONT_FAMILY, 8), fg=T.TEXT_MUTED, bg=T.BG_CARD).pack(anchor='w')

        right_frame = tk.Frame(header, bg=T.BG_CARD)
        right_frame.pack(side=tk.RIGHT, padx=16)

        self.status_label = tk.Label(right_frame, text="● 运行中", font=(T.FONT_FAMILY, 10),
                                     fg=T.JADE, bg=T.BG_CARD)
        self.status_label.pack(side=tk.LEFT, padx=8)

        self.time_label = tk.Label(right_frame, text="", font=(T.FONT_FAMILY, 11),
                                   fg=T.GOLD, bg=T.BG_CARD)
        self.time_label.pack(side=tk.RIGHT, padx=8)

        theme_btn = tk.Button(right_frame, text="主题", font=(T.FONT_FAMILY, 9),
                              fg=T.TEXT_PRIMARY, bg=T.BG_HOVER, activebackground=T.BG_ACTIVE,
                              bd=0, padx=12, pady=4, cursor='hand2',
                              command=self.toggle_theme)
        theme_btn.pack(side=tk.RIGHT, padx=4)
        self._action_btns.append(theme_btn)

    def _build_control_bar(self):
        """控制栏：彩种+期号+方案+预算+概率+投票+调试"""
        T = ModernTheme
        ctrl_frame = tk.Frame(self.root, bg=T.BG_DEEP)
        ctrl_frame.pack(fill=tk.X, padx=8, pady=4)

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

        vote_cb = tk.Checkbutton(row1, text="多引擎投票", font=(T.FONT_FAMILY, 9),
                                 variable=self.vote_var, bg=T.BG_DEEP,
                                 fg=T.TEXT_SECONDARY, selectcolor=T.BG_INPUT,
                                 activebackground=T.BG_DEEP, activeforeground=T.TEXT_PRIMARY,
                                 bd=0)
        vote_cb.pack(side=tk.LEFT, padx=8)
        self._action_btns.append(vote_cb)

        debug_cb = tk.Checkbutton(row1, text="调试", font=(T.FONT_FAMILY, 9),
                                  variable=self.debug_mode, bg=T.BG_DEEP,
                                  fg=T.TEXT_SECONDARY, selectcolor=T.BG_INPUT,
                                  activebackground=T.BG_DEEP, activeforeground=T.TEXT_PRIMARY,
                                  bd=0)
        debug_cb.pack(side=tk.LEFT, padx=4)
        self._action_btns.append(debug_cb)

    def _build_engine_switches(self):
        """引擎开关区"""
        T = ModernTheme
        eng_frame = tk.Frame(self.root, bg=T.BG_CARD)
        eng_frame.pack(fill=tk.X, padx=8, pady=4)

        tk.Label(eng_frame, text="引擎开关:", font=(T.FONT_FAMILY, 9, 'bold'),
                 fg=T.COLOR_PRIMARY, bg=T.BG_CARD).pack(side=tk.LEFT, padx=(8, 8), pady=6)

        eng_inner = tk.Frame(eng_frame, bg=T.BG_CARD)
        eng_inner.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=4)

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

    def _build_action_buttons(self):
        """操作按钮区"""
        T = ModernTheme
        btn_frame = tk.Frame(self.root, bg=T.BG_DEEP)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)

        btn_defs = [
            ("生成预测", T.GOLD, self.gen_one),
            ("今日预测", T.ICE, self.today),
            ("复盘",     T.JADE, self.review),
            ("抓取数据", T.COLOR_PRIMARY_DARK, self.fetch_all),
            ("导入数据", '#b8944f', self.import_lottery_data),
            ("热度统计", '#3a9fc4', self.show_hot_stats),
            ("走势图", T.GOLD, self.show_trend_chart),
            ("足彩", T.COPPER, self._launch_football),
            ("保存", T.BG_ACTIVE, lambda: (self.save_settings(), self.save_preds())),
            ("清空日志", T.BG_HOVER, self.clr_log),
        ]
        for text, color, cmd in btn_defs:
            fg_color = T.DEEP if color in (T.GOLD, '#b8944f') else T.TEXT_PRIMARY
            btn = tk.Button(btn_frame, text=text, font=(T.FONT_FAMILY, 10, 'bold'),
                            fg=fg_color, bg=color, activebackground=T.BG_ACTIVE,
                            bd=0, padx=16, pady=6, cursor='hand2', command=cmd)
            btn.pack(side=tk.LEFT, padx=3)
            self._action_btns.append(btn)

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

    def _build_table(self):
        """预测结果表格Treeview"""
        T = ModernTheme
        table_frame = tk.Frame(self.root, bg=T.BG_DEEP)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._stats_label = tk.Label(
            table_frame, text="命中率统计：暂无复盘数据",
            bg=T.BG_DEEP, fg=T.TEXT_MUTED, font=("Microsoft YaHei UI", 9),
            anchor="w", padx=4
        )
        self._stats_label.pack(fill=tk.X, pady=(0, 2))

        columns = tuple(cid for cid, _, _ in PRED_TABLE_COLUMNS)
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=12)

        for col_id, col_title, col_width in PRED_TABLE_COLUMNS:
            self.tree.heading(col_id, text=col_title)
            self.tree.column(col_id, width=col_width, anchor=tk.CENTER)

        tree_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL,
                                    command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind('<Double-1>', self._on_tree_double_click)
        self.tree.bind('<Button-3>', self._show_tree_context_menu)

        # Treeview 不支持原生 Ctrl+A/Ctrl+C，手动绑定（JS-20260803-18）
        self.tree.bind('<Control-a>', self._tree_select_all)
        self.tree.bind('<Control-A>', self._tree_select_all)
        self.tree.bind('<Control-c>', self._tree_copy_full)
        self.tree.bind('<Control-C>', self._tree_copy_full)
        # 鼠标拖拽连选（JS-20260804-04）：按下/拖动/松开
        self.tree.bind('<ButtonPress-1>', self._tree_drag_start)
        self.tree.bind('<B1-Motion>', self._tree_drag_motion)
        self.tree.bind('<ButtonRelease-1>', self._tree_drag_end)

        self.refresh_pred_panel()

    def _build_log_area(self):
        """底部日志区 + 公告栏"""
        T = ModernTheme
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
                 fg=T.GOLD, bg=T.BG_CARD).pack(side=tk.LEFT)
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
                 fg=T.GOLD, bg=T.BG_CARD).pack(side=tk.LEFT)

        log_inner = tk.Frame(self._log_frame, bg=T.BG_CARD)
        log_inner.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.lb = tk.Listbox(log_inner, font=(T.FONT_FAMILY, 9),
                             bg=T.BG_INPUT, fg=T.TEXT_PRIMARY,
                             selectbackground='#1a3a4a',
                             selectforeground=T.TEXT_PRIMARY,
                             bd=0, height=8, activestyle='none')
        log_scroll = ttk.Scrollbar(log_inner, orient=tk.VERTICAL,
                                   command=self.lb.yview)
        self.lb.configure(yscrollcommand=log_scroll.set)
        self.lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.lb.bind('<Button-3>', self._show_log_context_menu)
        # Listbox 不支持原生 Ctrl+A/Ctrl+C，手动绑定（JS-20260803-18）
        self.lb.bind('<Control-a>', self._log_select_all)
        self.lb.bind('<Control-A>', self._log_select_all)
        self.lb.bind('<Control-c>', self._log_copy_selected)
        self.lb.bind('<Control-C>', self._log_copy_selected)
        # 根级兜底：焦点在表格/日志即可全选复制（JS-20260804-06）
        self.root.bind('<Control-a>', self._root_ctrl_a, add='+')
        self.root.bind('<Control-A>', self._root_ctrl_a, add='+')
        self.root.bind('<Control-c>', self._root_ctrl_c, add='+')
        self.root.bind('<Control-C>', self._root_ctrl_c, add='+')
        # 鼠标拖拽连选（JS-20260804-04）：按下/拖动/松开
        self._log_drag_anchor = None
        self._log_drag_prev = []
        self._log_drag_active = False
        self._log_drag_scroll_job = None
        self.lb.bind('<ButtonPress-1>', self._log_drag_start)
        self.lb.bind('<B1-Motion>', self._log_drag_motion)
        self.lb.bind('<ButtonRelease-1>', self._log_drag_end)

    # ------------------------------------------------------------------
    # 双击查看详情
    # ------------------------------------------------------------------
    def _on_tree_double_click(self, event):
        """双击查看详情（含号码球可视化）"""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        vals = self.tree.item(item, 'values')
        if not vals:
            return

        top = tk.Toplevel(self.root)
        top.title("预测详情")
        top.geometry("560x420")
        top.configure(bg=ModernTheme.BG_DEEP)
        top.transient(self.root)
        top.grab_set()

        T = ModernTheme
        lot = str(vals[1])
        nums_str = str(vals[2])
        ptype = str(vals[3])

        # ===== 号码球可视化区域 =====
        ball_frame = tk.Frame(top, bg=T.BG_DEEP)
        ball_frame.pack(fill=tk.X, padx=16, pady=(16, 8))

        tk.Label(ball_frame, text=f"{lot} · {ptype}", font=(T.FONT_FAMILY, 12, 'bold'),
                 fg=T.TEXT_PRIMARY, bg=T.BG_DEEP).pack(anchor='w')

        canvas = tk.Canvas(ball_frame, bg=T.BG_CARD, height=70, highlightthickness=0)
        canvas.pack(fill=tk.X, pady=8)

        # 解析号码并确定颜色
        balls = []  # [(number_str, color)]
        parts = nums_str.split("+")
        front_str = parts[0]
        back_str = parts[1] if len(parts) > 1 else ""

        # 提取前区数字
        import re
        front_nums = re.findall(r'\d+', front_str)
        back_nums = re.findall(r'\d+', back_str) if back_str else []

        if lot in ("双色球",):
            for n in front_nums:
                balls.append((n, T.COPPER))   # 前区红球 → 赤铜（暖红替代）
            for n in back_nums:
                balls.append((n, T.ICE))      # 后区蓝球 → 冰水蓝
        elif lot in ("大乐透",):
            for n in front_nums:
                balls.append((n, T.COPPER))   # 前区 → 赤铜
            for n in back_nums:
                balls.append((n, T.ICE))      # 后区 → 冰水蓝
        elif lot in ("福彩3D", "排列三"):
            # 七色映射：组六→墨绿金, 组三→香槟金, 豹子→赤铜, 直选→冰蓝, 组六复式→冰蓝淡
            color_map = {"组六": T.JADE, "组三": T.GOLD, "豹子": T.COPPER,
                         "直选": T.ICE, "组六复式": '#3a9fc4'}
            c = color_map.get(ptype, T.JADE)
            for n in front_nums:
                balls.append((n, c))
        elif lot == "七星彩":
            for n in front_nums:
                balls.append((n, T.ICE))       # 前区 → 冰水蓝
            for n in back_nums:
                balls.append((n, T.GOLD))      # 特别号 → 香槟金
        else:
            # 默认：前区墨绿金，后区冰蓝
            for n in front_nums:
                balls.append((n, T.JADE))
            for n in back_nums:
                balls.append((n, T.ICE))

        # 绘制号码球
        x_start = 15
        ball_r = 16
        gap = 6
        for i, (num, color) in enumerate(balls[:15]):  # 最多画15个球
            cx = x_start + i * (ball_r * 2 + gap) + ball_r
            cy = 35
            canvas.create_oval(cx - ball_r, cy - ball_r, cx + ball_r, cy + ball_r,
                               fill=color, outline='')
            canvas.create_text(cx, cy, text=num, fill='white',
                               font=(T.FONT_FAMILY, 10, 'bold'))

        # ===== 信息区 =====
        info_frame = tk.Frame(top, bg=T.BG_DEEP)
        info_frame.pack(fill=tk.X, padx=16, pady=4)
        labels = ["期号", "彩种", "号码", "类型", "方案", "命中", "状态", "日期"]
        for i, (label, val) in enumerate(zip(labels, vals)):
            tk.Label(info_frame, text=f"{label}:", font=(T.FONT_FAMILY, 10, 'bold'),
                     fg=T.GOLD, bg=T.BG_DEEP).grid(
                row=i, column=0, sticky='w', padx=4, pady=3)
            tk.Label(info_frame, text=str(val), font=(T.FONT_FAMILY, 10),
                     fg=T.TEXT_PRIMARY, bg=T.BG_DEEP, wraplength=350, justify=tk.LEFT).grid(
                row=i, column=1, sticky='w', padx=8, pady=3)

        # 复制按钮（金色系）
        tk.Button(top, text="复制号码", font=(T.FONT_FAMILY, 10),
                  fg=T.DEEP, bg=T.GOLD, bd=0, padx=20, pady=6,
                  cursor='hand2',
                  command=lambda: self._safe_copy(nums_str)).pack(pady=10)

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
        # Text 原生不支持 Ctrl+A，手动补全选绑定（JS-20260804-06）
        text_area.bind('<Control-a>', lambda e: (
            text_area.tag_add('sel', '1.0', 'end-1c'), 'break'))
        text_area.bind('<Control-A>', lambda e: (
            text_area.tag_add('sel', '1.0', 'end-1c'), 'break'))

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

        # 创建图表（七色暗色体系）
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7))
        fig.patch.set_facecolor('#0B1A2F')  # 深海墨蓝底
        fig.suptitle(f"{lot} 走势分析 (近{len(recent)}期)", fontsize=14,
                     fontweight='bold', color='#E8ECF1')

        # 子图1: 和值走势
        ax1.set_facecolor('#0B1A2F')
        ax1.plot(range(len(sums)), sums, color=ModernTheme.ICE,   # 冰水蓝主线
                 linewidth=1.5, marker='o', markersize=3, label='和值')
        # 均线
        if len(sums) >= 5:
            ma5 = []
            for i in range(len(sums)):
                start = max(0, i - 4)
                ma5.append(sum(sums[start:i + 1]) / (i - start + 1))
            ax1.plot(range(len(sums)), ma5, color=ModernTheme.GOLD,  # 香槟金均线
                     linewidth=1.5, linestyle='--', label='MA5')
        ax1.set_title("和值走势", fontsize=11, color='#E8ECF1')
        ax1.set_xlabel("期数", color='#E8ECF1')
        ax1.set_ylabel("和值", color='#E8ECF1')
        ax1.tick_params(colors='#E8ECF1')
        ax1.legend(loc='upper right', facecolor='#162840', edgecolor='#C9A96E',
                   labelcolor='#E8ECF1')
        ax1.grid(True, alpha=0.15, color='#C9A96E')

        # 子图2: 号码频率
        ax2.set_facecolor('#0B1A2F')
        sorted_freq = sorted(freq.items())
        nums_list = [f"{n:02d}" for n, _ in sorted_freq]
        counts_list = [c for _, c in sorted_freq]
        # 七色映射：高频→赤铜, 中频→冰蓝, 低频→银白淡
        colors = [ModernTheme.COPPER if c >= max(counts_list) * 0.7
                  else ModernTheme.ICE if c >= max(counts_list) * 0.4
                  else '#556680' for c in counts_list]
        ax2.bar(nums_list, counts_list, color=colors, edgecolor='none')
        ax2.set_title("号码出现频率", fontsize=11, color='#E8ECF1')
        ax2.set_xlabel("号码", color='#E8ECF1')
        ax2.set_ylabel("出现次数", color='#E8ECF1')
        ax2.tick_params(axis='x', rotation=45, labelsize=7, colors='#E8ECF1')
        ax2.tick_params(axis='y', colors='#E8ECF1')
        ax2.grid(True, alpha=0.15, axis='y', color='#C9A96E')

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

        # 更新公告栏：显示各彩种最新开奖结果
        if success_count > 0:
            try:
                notice_lines = []
                for lot in lots:
                    arr = Data.load(lot)
                    if arr:
                        latest = arr[-1]
                        per = latest.get("period", "")
                        nums = latest.get("nums", "")
                        notice_lines.append(f"{lot} 第{fmt_period(lot, per)}期: {nums}")
                if notice_lines:
                    summary = "最新开奖汇总 | " + " | ".join(notice_lines[:4])
                    self.root.after(0, lambda: self.update_notice(summary))
            except Exception:
                pass

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
                    # 添加到 preds 和 tree（按玩法类型分列）
                    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
                    per = result.get("period", "")
                    tickets = result.get("tickets", {})
                    is_3d = lot in ("福彩3D", "排列三")
                    # SQI 信号质量指数档位（诚实：仅反映信号清晰度，非中奖概率）
                    sqi = result.get("confidence", {})
                    sqi_level = sqi.get("level", "unknown")
                    sqi_score = sqi.get("score")
                    _SQI_LABEL = {"strong": "强", "medium": "中", "weak": "弱", "unknown": "-"}
                    sqi_label = _SQI_LABEL.get(sqi_level, "-")
                    sqi_display = f"{sqi_label}" if sqi_score is None else f"{sqi_label}{sqi_score}"
                    total_count = 0
                    for play_type in ("单注", "复式", "胆拖", "直选推荐"):
                        for nums in tickets.get(play_type, []):
                            if not nums:
                                continue
                            display_type = self._detect_3d_type(nums, play_type) if is_3d else play_type
                            entry = {
                                "scheme": scheme,
                                "lot": lot,
                                "period": per,
                                "nums": str(nums),
                                "type": display_type,
                                "confidence": sqi_display,
                                "date": now_str,
                                "reviewed": False,
                                "hits": 0
                            }
                            with self._lock:
                                self.preds.append(entry)
                            total_count += 1
                    # 兜底
                    if total_count == 0:
                        for nums in result.get("all_nums", []):
                            display_type = self._detect_3d_type(nums, "单注") if is_3d else "单注"
                            entry = {
                                "scheme": scheme,
                                "lot": lot,
                                "period": per,
                                "nums": str(nums),
                                "type": display_type,
                                "confidence": sqi_display,
                                "date": now_str,
                                "reviewed": False,
                                "hits": 0
                            }
                            with self._lock:
                                self.preds.append(entry)
                            total_count += 1

                    self.save_preds()
                    self.refresh_pred_panel()
                    self.log(f"{lot} 预测生成完成，共 {total_count} 注 | SQI={sqi_display}")
                    rf = result.get("ref_features")
                    if rf and rf.get("supported"):
                        sm = rf.get("summary", {})
                        self.log(f"📊 {lot} 多维参考: 和值均{sm.get('和值均值')} 跨度均{sm.get('跨度均值')} 覆盖{rf.get('feature_coverage')}%", "DEBUG")
                    # 诚实声明：SQI 仅反映信号清晰度，非中奖概率
                    self.log("SQI说明：信号质量指数仅反映模型信号清晰度与数据质量，非中奖概率。彩票本质近随机。")

                    # 自动添加到参考池
                    all_nums = result.get("all_nums", [])
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
        """生成玩法计划（3单+1复+1胆拖）（薄委托）"""
        return _make_play_plan_ext(lot)

    # ------------------------------------------------------------------
    # 今日预测
    # ------------------------------------------------------------------
    def today(self):
        """预测今日开奖的所有彩种"""
        if self._lock.locked():
            self.log("已有任务在运行，请稍后再试", "WARNING")
            return
        per_value = self.per_var.get().strip()
        vote_value = self.vote_var.get()
        threading.Thread(target=self._today_job, args=(per_value, None, vote_value), daemon=True).start()

    # 各彩种默认玩法方案（从 gui/play_plans 导入）
    _PLAY_PLANS = _PLAY_PLANS

    def _today_job(self, per_value, play_value, vote_value):
        """今日预测工作线程：预测当天所有开奖彩种（3单注+1复式+1胆拖）"""
        if not self._lock.acquire(blocking=False):
            self.log("已有任务在运行，请稍后再试", "WARNING")
            return
        try:
            self.set_btns_state('disabled')
            today_lots = get_today_lots()
            if not today_lots:
                self.log("今日无开奖彩种", "INFO")
                return
            self.log(f"今日开奖彩种({len(today_lots)}个)：{'、'.join(today_lots)}")
            success_count = 0
            skip_count = 0
            fail_count = 0
            for lot in today_lots:
                plan = self._PLAY_PLANS.get(lot, _DEFAULT_PLAY_PLAN)
                try:
                    result = self._generate_for_lot(lot, plan, per_value=per_value, vote_value=vote_value)
                    if result == "success":
                        success_count += 1
                    elif result == "skip":
                        skip_count += 1
                    else:
                        fail_count += 1
                except Exception as e:
                    fail_count += 1
                    self.log(f"{lot} 预测异常: {e}", "ERROR")
                time.sleep(0.1)
            self.log(f"今日预测完成：成功{success_count}个，跳过{skip_count}个，失败{fail_count}个")
        except Exception as e:
            self.log(f"今日预测异常: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
        finally:
            self.set_btns_state('normal')
            self._lock.release()

    @staticmethod
    def _detect_3d_type(nums, base_type):
        """检测3D/排列三号码的具体玩法类型（薄委托）"""
        return _detect_3d_type(nums, base_type)

    def _generate_for_lot(self, lot, play_plan, scheme="默认方案", per_value=None, vote_value=False):
        """为指定彩种生成预测（同步，供today调用）

        Returns:
            str: "success" / "skip" / "fail"
        """
        from config import EXCLUDED_LOTS
        if lot in EXCLUDED_LOTS:
            return "skip"
        try:
            if per_value:
                per = int(per_value)
            else:
                per = Data.latest(lot) + 1
        except Exception:
            per = Data.latest(lot) + 1
        if Data.has_period(lot, per):
            self.log(f"{lot} 第{fmt_period(lot, per)}期已开奖，跳过", "WARNING")
            return "skip"
        self.log(f"开始生成 {lot} 预测...")
        try:
            svc = PredictionService(
                killer=self.killer,
                evolve=self.evolve,
                engine_states=self.engine_states,
                hot_window=self.hot_window,
                schemes=self.schemes,
                on_log=self.log
            )
            result = svc.generate(lot, play_plan=play_plan, scheme=scheme, hot_window=self.hot_window,
                                  per_value=per_value, vote_value=vote_value)
            if result["success"]:
                now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
                per = result.get("period", "")
                tickets = result.get("tickets", {})
                total_count = 0
                is_3d = lot in ("福彩3D", "排列三")
                # SQI 信号质量指数档位
                sqi = result.get("confidence", {})
                sqi_level = sqi.get("level", "unknown")
                sqi_score = sqi.get("score")
                _SQI_LABEL = {"strong": "强", "medium": "中", "weak": "弱", "unknown": "-"}
                sqi_label = _SQI_LABEL.get(sqi_level, "-")
                sqi_display = f"{sqi_label}" if sqi_score is None else f"{sqi_label}{sqi_score}"
                # 按玩法类型分别记录，界面可区分单注/复式/胆拖
                for play_type in ("单注", "复式", "胆拖", "直选推荐"):
                    for nums in tickets.get(play_type, []):
                        if not nums:
                            continue
                        # 3D/排列三：细化类型标签（组六/组三/豹子/组六复式）
                        display_type = play_type
                        if is_3d:
                            display_type = self._detect_3d_type(nums, play_type)
                        entry = {"scheme": scheme, "lot": lot, "period": per,
                                 "nums": str(nums), "type": display_type,
                                 "confidence": sqi_display,
                                 "date": now_str, "reviewed": False, "hits": 0}
                        self.preds.append(entry)
                        total_count += 1
                # 兜底：如果tickets为空但all_nums有值
                if total_count == 0:
                    for nums in result.get("all_nums", []):
                        display_type = self._detect_3d_type(nums, "单注") if is_3d else "单注"
                        entry = {"scheme": scheme, "lot": lot, "period": per,
                                 "nums": str(nums), "type": display_type,
                                 "confidence": sqi_display,
                                 "date": now_str, "reviewed": False, "hits": 0}
                        self.preds.append(entry)
                        total_count += 1
                self.save_preds()
                self.root.after(0, self.refresh_pred_panel)
                self.log(f"{lot} 预测完成，共 {total_count} 注 | SQI={sqi_display}")
                rf = result.get("ref_features")
                if rf and rf.get("supported"):
                    sm = rf.get("summary", {})
                    self.log(f"📊 {lot} 多维参考: 和值均{sm.get('和值均值')} 跨度均{sm.get('跨度均值')} 覆盖{rf.get('feature_coverage')}%", "DEBUG")
                return "success"
            else:
                self.log(f"{lot} 预测失败: {result.get('error', '未知错误')}", "WARNING")
                return "fail"
        except Exception as e:
            self.log(f"{lot} 生成异常: {e}", "ERROR")
            return "fail"

    # ------------------------------------------------------------------
    # 复盘
    # ------------------------------------------------------------------
    def review(self):
        """复盘所有未复盘预测"""
        if self._lock.locked():
            self.log("已有任务在运行，请稍后再试", "WARNING")
            return
        threading.Thread(target=self._review_job, daemon=True).start()

    def _review_job(self):
        """复盘工作线程"""
        if not self._lock.acquire(blocking=False):
            self.log("已有任务在运行，请稍后再试", "WARNING")
            return
        try:
            self.set_btns_state('disabled')
            if not self.preds:
                self.log("暂无预测记录", "INFO")
                return
            unrev = [p for p in self.preds if not p.get("reviewed")]
            total = len(unrev)
            if total == 0:
                self.log("所有预测均已复盘", "INFO")
                return
            self.log(f"开始复盘 {total} 条记录...")
            processed = 0
            hit_list = []
            skip_count = 0
            future_count = 0
            from collections import defaultdict
            lot_stats = defaultdict(lambda: {"0": 0, "1": 0, "2": 0, "3+": 0, "total": 0})
            latest_periods = {}
            for p in unrev:
                lt = p.get("lot", "")
                if lt and lt not in latest_periods:
                    try:
                        arr = Data.load(lt)
                        if arr:
                            latest_periods[lt] = max(int(d.get("period", 0)) for d in arr)
                    except Exception:
                        pass
            for p in unrev:
                processed += 1
                if processed % 5 == 0:
                    self.log(f"复盘进度：{processed}/{total}")
                lot = p.get("lot", "")
                per = p.get("period", 0)
                try:
                    per_int = int(per)
                except Exception:
                    per_int = 0
                if per_int > latest_periods.get(lot, 0):
                    future_count += 1
                    continue
                if not Data.has_period(lot, per):
                    skip_count += 1
                    continue
                act, dt = Data.result(lot, per)
                if not act:
                    skip_count += 1
                    continue
                p["draw_date"] = dt if dt else ""
                pn = clean_nums(p["nums"])
                ac = clean_nums(act)
                hits = 0
                if lot in ["福彩3D", "排列三"]:
                    from collections import Counter as _Ctr
                    pc = _Ctr(parse_reds(pn))
                    ac_ctr = _Ctr(parse_reds(ac))
                    hits = sum(min(pc[d], ac_ctr.get(d, 0)) for d in pc)
                elif lot == "快乐8":
                    hits = len(set(parse_reds(pn)) & set(parse_reds(ac)))
                else:
                    pr = pn.split("+")[0] if "+" in pn else pn
                    ar = ac.split("+")[0] if "+" in ac else ac
                    hits = len(set(parse_reds(pr)) & set(parse_reds(ar)))
                    if "+" in pn and "+" in ac:
                        hits += len(set(parse_reds(pn.split("+")[1])) & set(parse_reds(ac.split("+")[1])))
                p["reviewed"] = True
                p["hits"] = hits
                # 命中类型判定（直选/组选/未中）—— JS-20260724-02 口径统一：与彩票看板口径一致
                hit_type = "未中"
                if lot in ("福彩3D", "排列三"):
                    if pn == ac:                       # 位置精确匹配 = 直选
                        hit_type = "直选"
                    elif hits >= 3:                    # 3码多重集全中 = 组选
                        hit_type = "组选"
                else:
                    if hits > 0:                       # 多球种：任意奖级命中近似组选
                        hit_type = "组选"
                p["hit_type"] = hit_type
                # 复式覆盖度 = 命中号码数 / 开奖号码总数 —— JS-20260724-03
                # 衡量候选集合对开奖号码的覆盖程度（复式选更多号应覆盖更多）
                act_num_count = len(parse_reds(ac.replace("+", ",")))
                p["coverage"] = round(hits / act_num_count, 3) if act_num_count else 0
                hit_list.append(hits)
                self.schemes.update_hit(p.get("scheme", ""), hits)
                if hits == 0:
                    lot_stats[lot]["0"] += 1
                elif hits == 1:
                    lot_stats[lot]["1"] += 1
                elif hits == 2:
                    lot_stats[lot]["2"] += 1
                else:
                    lot_stats[lot]["3+"] += 1
                lot_stats[lot]["total"] += 1
                self.log(f"【{lot}】期{fmt_period(lot, per)} 命中 {hits} 个")
                time.sleep(0.01)
            valid_count = len(hit_list)
            self.log("=" * 40)
            self.log(f"复盘汇总：有效 {valid_count} 条 / 跳过 {skip_count} 条 / 未开奖 {future_count} 条")
            if valid_count > 0:
                total_hits = sum(hit_list)
                avg_hits = total_hits / valid_count
                hit_rate = len([h for h in hit_list if h > 0]) / valid_count * 100
                self.log(f"总命中 {total_hits} 个 / 平均 {avg_hits:.2f} 个 / 命中率 {hit_rate:.1f}%")
                self.log("口径说明：组选=任意1+码中; 直选=位置精确匹配; 覆盖度=命中号码/开奖号码总数; 与看板口径一致")
                for lot, stats in lot_stats.items():
                    if stats["total"] == 0:
                        continue
                    self.log(f"  {lot}: 0码{stats['0']}期 / 1码{stats['1']}期 / 2码{stats['2']}期 / 3+码{stats['3+']}期")
            self.log("=" * 40)
            self.save_preds()
            self.root.after(0, self.refresh_pred_panel)
            # 智能大脑学习
            if self.brain is not None:
                try:
                    reviewed_lots = set(p.get("lot", "") for p in unrev if p.get("reviewed"))
                    for lot_name in reviewed_lots:
                        lot_preds = [p for p in unrev if p.get("lot") == lot_name and p.get("reviewed")]
                        if not lot_preds:
                            continue
                        latest_per = max(p.get("period", 0) for p in lot_preds)
                        if Data.has_period(lot_name, latest_per):
                            act_data, _ = Data.result(lot_name, latest_per)
                            if act_data:
                                act_nums = parse_reds(clean_nums(act_data))
                                self.brain.learn_from_review(lot_name, lot_preds, act_nums)
                    self.log("智能大脑学习更新完成")
                except Exception as e:
                    self.log(f"智能大脑学习失败: {e}", "WARNING")
        except Exception as e:
            self.log(f"复盘异常: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
        finally:
            self.set_btns_state('normal')
            self._lock.release()

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
