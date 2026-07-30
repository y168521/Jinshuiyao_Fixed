# -*- coding: utf-8 -*-
"""金水谣引擎 · 七色暗色体系公共GUI主题

所有GUI窗口统一使用此主题配置，与 workbench.html / theme.css / Ardot 画布完全对齐。
核心四色（占 ~96%）：深海墨蓝 #0B1A2F / 深蓝灰 #162840 / 暖银白 #E8ECF1 / 香槟金 #C9A96E
功能三辅色（占 ~4%）：冰水蓝 #5BC0DE / 墨绿金 #2D8B7E / 赤铜 #C8755A
绝对禁用：红 / 橙 / 黄 / 棕 / 绿(非墨绿金) / 紫 / 粉 / 灰紫
"""
import sys
import os


class Theme:
    """金水谣七色暗色体系 — 所有GUI共用"""

    # ── 核心四色 ──
    DEEP = '#0B1A2F'              # 深海墨蓝 · 主背景（画布）
    CARD_BG = '#162840'           # 深蓝灰 · 卡片/区块/侧栏
    INK = '#E8ECF1'               # 暖银白 · 主文字
    GOLD = '#C9A96E'              # 香槟金 · 强调/按钮/边框

    # ── 功能三辅色 ──
    ICE = '#5BC0DE'               # 冰水蓝 · 数据/链接/交互
    JADE = '#2D8B7E'              # 墨绿金 · 成功/盈利/正向
    COPPER = '#C8755A'            # 赤铜 · 警示/亏损/开发中

    # ── 层次衍生（半透明变体 → tkinter实色近似，底色#0B1A2F）──
    INK_DIM = '#858e9a'           # rgba(232,236,241,0.55) 近似
    INK_MID = '#a6adb7'           # rgba(232,236,241,0.7) 近似
    INK_FAINT = '#5f6a79'         # rgba(232,236,241,0.38) 近似
    GOLD_SOFT = '#222b37'         # rgba(201,169,110,0.12) 近似
    GOLD_BORDER = '#2d343a'       # rgba(201,169,110,0.18) 近似
    ICE_SOFT = '#152e44'          # rgba(91,192,222,0.12) 近似
    JADE_SOFT = '#0f2838'         # rgba(45,139,126,0.12) 近似
    COPPER_SOFT = '#222534'       # rgba(200,117,90,0.12) 近似

    # ── 背景色（兼容旧引用名）──
    BG_DEEP = DEEP                # 主背景
    BG_CARD = CARD_BG             # 卡片/区块
    BG_HOVER = '#1e3048'          # 悬停态
    BG_INPUT = '#0f2035'          # 输入框（tkinter 不支持 rgba，用实色近似）
    BG_ACTIVE = '#1a3350'         # 激活态

    # ── 文字色（兼容旧引用名）──
    TEXT_PRIMARY = INK            # 主文字
    TEXT_SECONDARY = INK_DIM      # 次要文字
    TEXT_DIM = INK_FAINT          # 弱化文字
    TEXT_MUTED = INK_FAINT        # 弱化文字（别名）

    # ── 功能色（七色映射，兼容旧引用名）──
    COLOR_PRIMARY = ICE           # 主操作色 → 冰蓝
    COLOR_PRIMARY_DARK = '#4ABBD8'# 主操作深色 → 冰蓝亮
    COLOR_SECONDARY = GOLD        # 次要强调 → 香槟金
    COLOR_ACCENT = JADE           # 强调色 → 墨绿金
    COLOR_GREEN = JADE            # 绿色禁用 → 映射墨绿金
    COLOR_RED = COPPER            # 红色禁用 → 映射赤铜
    COLOR_AMBER = GOLD            # 琥珀 → 映射香槟金
    COLOR_PURPLE = ICE            # 紫色禁用 → 映射冰蓝
    COLOR_PINK = COPPER_SOFT      # 粉色禁用 → 映射赤铜淡

    # ── 边框 ──
    BORDER = '#2d4a3a'            # 金色淡边框（tkinter 实色近似）
    BORDER_LIGHT = '#3d5a4a'
    BORDER_HOVER = ICE            # 悬停边框 → 冰蓝

    # ── 状态色（七色映射）──
    SUCCESS = JADE                # 成功 → 墨绿金
    WARNING = '#907e5b'           # 警告 → 金色调（rgba(201,169,110,0.7)近似）
    ERROR = COPPER                # 错误 → 赤铜
    INFO = ICE                    # 信息 → 冰蓝

    # ── 字体 ──
    FONT_FAMILY = 'Microsoft YaHei' if sys.platform == 'win32' else 'Noto Sans CJK SC'
    FONT_SIZE = 10
    FONT_SIZE_SM = 9
    FONT_SIZE_LG = 12
    FONT_SIZE_TITLE = 14
    FONT_WEIGHT_BOLD = 'bold'

    # ── 窗口 ──
    WIN_WIDTH = 1400
    WIN_HEIGHT = 900

    # ── 图表（七色映射）──
    CHART_UP = JADE               # 涨 → 墨绿金（中国股市：涨=绿/正）
    CHART_DOWN = COPPER           # 跌 → 赤铜（中国股市：跌=红/负）
    CHART_MA5 = GOLD              # MA5均线 → 香槟金
    CHART_MA20 = ICE              # MA20均线 → 冰蓝
    CHART_MA60 = '#4ABBD8'        # MA60均线 → 冰蓝亮
    CHART_VOLUME = '#2d4a3a'      # 成交量 → 金色淡
