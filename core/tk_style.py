# -*- coding: utf-8 -*-
"""金水谣引擎 · ttk 全组件暗色美化（深海熔金七色体系）

解决"桌面程序老土"根因：tkinter 的 ttk 组件（按钮/输入框/下拉/选项卡/
进度条/滚动条等）默认使用 Windows 原生浅色样式，与 Theme 深海暗色背景
混搭显得突兀。本模块提供一个入口函数，一次调用把所有通用 ttk 组件
全面覆盖为与 web 端 theme.css 对齐的暗色科技风。

用法（每个 GUI 的 main 入口加一行）：
    from core.tk_style import apply_dark_style
    apply_dark_style(root)

注意：GUI 自己的专属样式（如 "MatchTable.Treeview"）在 apply_dark_style
之后配置会自动覆盖同名冲突项；通用样式名（TButton/TNotebook/...）统一走
这里，保证全站一致。
"""
import sys

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None
    ttk = None

try:
    from core.theme import Theme
except ImportError:
    try:
        from theme import Theme
    except ImportError:
        Theme = None


def apply_dark_style(root=None):
    """给 root 应用全套 ttk 暗色样式（深海熔金七色）。root 可为 None（用默认根窗）。"""
    if tk is None or ttk is None:
        return None
    if Theme is None:
        return None

    try:
        root = root or tk._default_root
    except Exception:
        root = None
    if root is None:
        return None

    style = ttk.Style(root)
    try:
        style.theme_use('clam')  # clam 主题支持完整自定义配色
    except Exception:
        pass

    fg = Theme.TEXT_PRIMARY
    fg_dim = Theme.TEXT_SECONDARY
    bg = Theme.BG_DEEP
    card = Theme.CARD_BG
    field = Theme.BG_INPUT
    hover = Theme.BG_HOVER
    active = Theme.BG_ACTIVE
    gold = Theme.GOLD
    gold_border = Theme.BORDER
    ice = Theme.ICE
    jade = Theme.JADE
    copper = Theme.COPPER
    fam = Theme.FONT_FAMILY
    s12 = Theme.FONT_SIZE_LG
    s10 = Theme.FONT_SIZE
    s9 = Theme.FONT_SIZE_SM

    # ── 按钮 ──
    style.configure('TButton', background=card, foreground=fg, borderwidth=1,
                     focusthickness=1, font=(fam, s10), padding=(12, 6),
                     bordercolor=gold_border, relief='flat')
    style.map('TButton',
              background=[('pressed', active), ('active', hover)],
              foreground=[('disabled', fg_dim)],
              bordercolor=[('active', gold), ('focus', gold)])
    # 主操作按钮（金色）
    style.configure('Accent.TButton', background=gold, foreground=bg,
                     bordercolor=gold, font=(fam, s10, 'bold'), padding=(14, 7))
    style.map('Accent.TButton',
              background=[('pressed', '#a88c56'), ('active', '#d9bb82')],
              foreground=[('disabled', bg)])

    # ── 标签 ──
    style.configure('TLabel', background=bg, foreground=fg, font=(fam, s10))
    style.configure('Card.TLabel', background=card, foreground=fg, font=(fam, s10))
    style.configure('Dim.TLabel', background=bg, foreground=fg_dim, font=(fam, s9))
    style.configure('Title.TLabel', background=bg, foreground=gold,
                     font=(fam, s12, 'bold'))
    style.configure('CardTitle.TLabel', background=card, foreground=gold,
                     font=(fam, s12, 'bold'))
    style.configure('Jade.TLabel', background=bg, foreground=jade, font=(fam, s10, 'bold'))
    style.configure('Ice.TLabel', background=bg, foreground=ice, font=(fam, s10, 'bold'))
    style.configure('Copper.TLabel', background=bg, foreground=copper, font=(fam, s10, 'bold'))

    # ── 输入框 ──
    style.configure('TEntry', fieldbackground=field, foreground=fg,
                     bordercolor=gold_border, insertcolor=gold, padding=4,
                     font=(fam, s10))
    style.map('TEntry',
              bordercolor=[('focus', ice), ('active', gold)],
              fieldbackground=[('disabled', bg)])
    style.configure('TCombobox', fieldbackground=field, foreground=fg,
                     background=card, bordercolor=gold_border, arrowcolor=gold,
                     font=(fam, s10), padding=4)
    style.map('TCombobox',
              bordercolor=[('focus', ice)],
              fieldbackground=[('readonly', field), ('disabled', bg)],
              background=[('readonly', card)])

    # ── 选项卡（Notebook） ──
    style.configure('TNotebook', background=bg, bordercolor=gold_border)
    style.configure('TNotebook.Tab',
                     background=card, foreground=fg_dim, padding=(14, 7),
                     font=(fam, s10), bordercolor=gold_border)
    style.map('TNotebook.Tab',
              background=[('selected', active), ('active', hover)],
              foreground=[('selected', gold), ('active', fg)])

    # ── 表格 ──
    style.configure('Treeview',
                     background=bg, fieldbackground=bg, foreground=fg,
                     rowheight=30, bordercolor=gold_border,
                     font=(fam, s10))
    style.configure('Treeview.Heading',
                     background=hover, foreground=fg,
                     font=(fam, s10, 'bold'), bordercolor=gold_border,
                     relief='flat')
    style.map('Treeview',
              background=[('selected', active)],
              foreground=[('selected', gold)])
    style.map('Treeview.Heading',
              background=[('active', active)])

    # ── 进度条 ──
    style.configure('TProgressbar', background=jade, troughcolor=field,
                     bordercolor=gold_border, lightcolor=jade,
                     darkcolor=jade)

    # ── 滚动条 ──
    style.configure('Vertical.TScrollbar', background=hover, troughcolor=field,
                     bordercolor=bg, arrowcolor=gold, width=12)
    style.configure('Horizontal.TScrollbar', background=hover, troughcolor=field,
                     bordercolor=bg, arrowcolor=gold, height=12)
    style.map('Vertical.TScrollbar', background=[('active', gold)])
    style.map('Horizontal.TScrollbar', background=[('active', gold)])

    # ── 复选/单选 ──
    style.configure('TCheckbutton', background=bg, foreground=fg,
                     font=(fam, s10), selectcolor=field)
    style.map('TCheckbutton',
              background=[('active', bg)],
              foreground=[('selected', gold)])
    style.configure('TRadiobutton', background=bg, foreground=fg,
                     font=(fam, s10), selectcolor=field)
    style.map('TRadiobutton',
              background=[('active', bg)],
              foreground=[('selected', gold)])

    # ── 分组框 ──
    style.configure('TLabelframe', background=bg, bordercolor=gold_border,
                     relief='solid', borderwidth=1)
    style.configure('TLabelframe.Label', background=bg, foreground=gold,
                     font=(fam, s10, 'bold'))

    # ── 分隔条 ──
    style.configure('TSeparator', background=gold_border)

    return style
