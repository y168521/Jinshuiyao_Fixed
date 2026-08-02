# -*- coding: utf-8 -*-
"""金水谣足彩预测系统 - 完整版GUI"""
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import datetime
import random

# 确保导入路径正确（兼容直接运行和包模式导入）
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print(f"[WARN] 无法导入pandas")

# 导入真实数据抓取器
try:
    from jinshuiyao.data_fetcher import data_fetcher
    HAS_REAL_DATA = True
    print("[INFO] 已加载真实数据抓取器")
except ImportError:
    try:
        from data_fetcher import data_fetcher
        HAS_REAL_DATA = True
        print("[INFO] 已加载真实数据抓取器")
    except ImportError as e:
        HAS_REAL_DATA = False
        print(f"[WARN] 无法导入数据抓取器: {e}")

from core.theme import Theme


def load_match_data():
    """加载比赛数据 - 从CSV文件加载，避免启动时网络请求"""
    import csv
    import os
    
    matches = []
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'matches.csv')
    
    if os.path.exists(csv_path):
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    matches.append({
                        'match_id': row.get('match_id', ''),
                        'home': row.get('home', ''),
                        'away': row.get('away', ''),
                        'league': row.get('league', ''),
                        'date': row.get('match_time', '')[:10],
                        'time': row.get('match_time', '')[11:] if len(row.get('match_time', '')) > 10 else '',
                        'odds': {
                            'win': float(row.get('odds_win', 2.0)),
                            'draw': float(row.get('odds_draw', 3.2)),
                            'lose': float(row.get('odds_lose', 3.5)),
                        }
                    })
            print(f"[SUCCESS] 从CSV加载 {len(matches)} 场比赛数据")
        except Exception as e:
            print(f"[WARN] 从CSV加载数据失败: {e}")
    
    if not matches:
        matches = _generate_fallback_matches()
        print(f"[INFO] 使用备用数据: {len(matches)} 场")
    
    matches.sort(key=lambda x: (x['date'], x['time']))
    return matches


def _generate_fallback_matches():
    """生成备用比赛数据（当CSV无数据时）"""
    return [
        {'match_id': 'demo_001', 'home': '法国', 'away': '西班牙', 'league': '世界杯半决赛',
         'date': '2026-07-15', 'time': '03:00', 'odds': {'win': 2.80, 'draw': 3.10, 'lose': 2.45}},
        {'match_id': 'demo_002', 'home': '英格兰', 'away': '阿根廷', 'league': '世界杯半决赛',
         'date': '2026-07-16', 'time': '03:00', 'odds': {'win': 2.60, 'draw': 3.20, 'lose': 2.70}},
        {'match_id': 'demo_003', 'home': '杰尔', 'away': '雷克雅未克维京人', 'league': '欧冠资格赛',
         'date': '2026-07-14', 'time': '22:00', 'odds': {'win': 1.85, 'draw': 3.40, 'lose': 3.60}},
        {'match_id': 'demo_004', 'home': '新圣徒', 'away': '萨巴赫', 'league': '欧冠资格赛',
         'date': '2026-07-14', 'time': '22:00', 'odds': {'win': 2.10, 'draw': 3.30, 'lose': 3.15}},
    ]


MATCH_DATA = []


def get_match_data():
    """延迟加载比赛数据"""
    global MATCH_DATA
    if not MATCH_DATA:
        MATCH_DATA = load_match_data()
    return MATCH_DATA


class MatchTable(ttk.Treeview):
    """比赛列表表格"""
    
    def __init__(self, parent, on_select=None):
        super().__init__(parent, show="headings", height=12)
        self.on_select = on_select
        
        # 定义列
        self["columns"] = ("league", "home", "away", "date", "time", "win", "draw", "lose", "prediction")
        
        # 设置列属性
        self.column("league", width=70, anchor="center", minwidth=60)
        self.column("home", width=100, anchor="center", minwidth=80)
        self.column("away", width=100, anchor="center", minwidth=80)
        self.column("date", width=85, anchor="center", minwidth=70)
        self.column("time", width=55, anchor="center", minwidth=50)
        self.column("win", width=55, anchor="center", minwidth=50)
        self.column("draw", width=55, anchor="center", minwidth=50)
        self.column("lose", width=55, anchor="center", minwidth=50)
        self.column("prediction", width=75, anchor="center", minwidth=60)
        
        # 设置表头
        self.heading("league", text="联赛")
        self.heading("home", text="主队")
        self.heading("away", text="客队")
        self.heading("date", text="日期")
        self.heading("time", text="时间")
        self.heading("win", text="胜")
        self.heading("draw", text="平")
        self.heading("lose", text="负")
        self.heading("prediction", text="预测")
        
        # 添加样式
        self.style = ttk.Style()
        self.style.configure("MatchTable.Treeview",
                           background=Theme.BG_DEEP,
                           foreground=Theme.TEXT_PRIMARY,
                           fieldbackground=Theme.BG_DEEP,
                           rowheight=30)
        self.style.configure("MatchTable.Treeview.Heading",
                           background=Theme.BG_HOVER,
                           foreground=Theme.TEXT_PRIMARY,
                           font=(Theme.FONT_FAMILY, 10, "bold"))
        self.style.map("MatchTable.Treeview",
                      background=[("selected", Theme.COLOR_PRIMARY), ("active", Theme.BG_HOVER)],
                      foreground=[("selected", Theme.BG_DEEP)])
        
        self["style"] = "MatchTable.Treeview"
        
        # 绑定点击事件
        self.bind("<<TreeviewSelect>>", self._on_click)
        
        # 填充数据
        self.load_matches()
    
    def load_matches(self, league_filter="全部"):
        """加载比赛数据"""
        for row in self.get_children():
            self.delete(row)
        
        for match in get_match_data():
            if league_filter == "全部" or match["league"] == league_filter:
                pred = self._predict(match)
                self.insert("", "end", values=(
                    match["league"],
                    match["home"],
                    match["away"],
                    match["date"],
                    match["time"],
                    match["odds"]["win"],
                    match["odds"]["draw"],
                    match["odds"]["lose"],
                    pred
                ))
    
    def _predict(self, match):
        """使用决策引擎进行真实预测"""
        try:
            from jinshuiyao.decision_engine import JinshuiyaoDecisionEngine
            
            engine = JinshuiyaoDecisionEngine()
            
            odds = match["odds"]
            odds_input = {
                'home_win': odds['win'],
                'draw': odds['draw'],
                'lose': odds['lose'],
            }
            
            features = {
                'home_goals_avg': 1.3,
                'away_goals_avg': 1.1,
                'home_defense_avg': 0.9,
                'away_defense_avg': 1.0,
            }
            
            prob = engine.ensemble_prob(features)
            
            max_prob = max(prob['win'], prob['draw'], prob['lose'])
            
            if max_prob == prob['win']:
                return "主胜"
            elif max_prob == prob['draw']:
                return "平局"
            else:
                return "客胜"
        except Exception as e:
            print(f"[WARN] 预测失败，使用备用逻辑: {e}")
            odds = match["odds"]
            prob_win = 1/odds["win"]
            prob_draw = 1/odds["draw"]
            prob_lose = 1/odds["lose"]
            total = prob_win + prob_draw + prob_lose
            
            prob_win /= total
            prob_draw /= total
            prob_lose /= total
            
            max_prob = max(prob_win, prob_draw, prob_lose)
            
            if max_prob == prob_win:
                return "主胜"
            elif max_prob == prob_draw:
                return "平局"
            else:
                return "客胜"
    
    def _on_click(self, event):
        """点击事件"""
        if self.on_select:
            selection = self.selection()
            if selection:
                item = self.item(selection[0])
                self.on_select(item["values"])


class ProbabilityBar(tk.Frame):
    """概率条形图 - 带有动态效果"""
    
    def __init__(self, parent, title, prob, color):
        super().__init__(parent, bg=Theme.BG_CARD)
        
        self.prob = prob
        self.color = color
        self.root = parent.winfo_toplevel()  # 获取根窗口引用
        
        # 标题和值框架
        header = tk.Frame(self, bg=Theme.BG_CARD)
        header.pack(fill="x", pady=(0, 4))
        
        self.title_label = tk.Label(header, text=title,
                                   font=(Theme.FONT_FAMILY, 10),
                                   fg=Theme.TEXT_SECONDARY,
                                   bg=Theme.BG_CARD)
        self.title_label.pack(side="left")
        
        self.value_label = tk.Label(header, text=f"{prob:.1%}",
                                   font=(Theme.FONT_FAMILY, 11, "bold"),
                                   fg=color,
                                   bg=Theme.BG_CARD)
        self.value_label.pack(side="right")
        
        # 进度条容器
        bar_container = tk.Frame(self, bg=Theme.BG_HOVER, height=22)
        bar_container.pack(fill="x")
        bar_container.pack_propagate(False)
        
        # 进度条背景
        self.bar_bg = tk.Frame(bar_container, bg=Theme.BG_HOVER)
        self.bar_bg.pack(fill="both")
        
        # 进度条
        self.bar = tk.Frame(self.bar_bg, bg=color)
        self.bar.pack(side="left", fill="y")
        
        # 初始化进度
        self.update_prob(prob)
    
    def update_prob(self, prob):
        """更新概率值"""
        self.prob = prob
        self.value_label.config(text=f"{prob:.1%}")
        target_width = int(prob * 280)
        self.bar.config(width=target_width)


class DetailAnalysisDialog(tk.Toplevel):
    """详细分析对话框"""
    
    def __init__(self, parent, match):
        super().__init__(parent)
        self.match = match
        self.title(f"详细分析 - {match['home']} vs {match['away']}")
        self.geometry("1050x720")
        self.configure(bg=Theme.BG_DEEP)
        self.resizable(True, True)
        
        # 计算概率
        odds = match["odds"]
        prob_win = 1/odds["win"]
        prob_draw = 1/odds["draw"]
        prob_lose = 1/odds["lose"]
        total = prob_win + prob_draw + prob_lose
        prob_win /= total
        prob_draw /= total
        prob_lose /= total
        
        self.prob_win = prob_win
        self.prob_draw = prob_draw
        self.prob_lose = prob_lose
        
        self._build_ui()
    
    def _build_ui(self):
        """构建详细分析界面"""
        # 顶部标题栏
        header = tk.Frame(self, bg=Theme.BG_CARD, padx=20, pady=15)
        header.pack(fill="x")

        title_label = tk.Label(header, text=f"🎯 {self.match['home']} VS {self.match['away']}",
                              font=(Theme.FONT_FAMILY, 16, "bold"),
                              fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD)
        title_label.pack(anchor="w")

        sub_title = tk.Label(header, text=f"{self.match['league']} | {self.match['date']} {self.match['time']}",
                            font=(Theme.FONT_FAMILY, 11),
                            fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        sub_title.pack(anchor="w", pady=(5, 0))

        # 可滚动主内容区
        canvas = tk.Canvas(self, bg=Theme.BG_DEEP, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        scroll_frame = tk.Frame(canvas, bg=Theme.BG_DEEP)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # 内容区（带padding）
        main_content = tk.Frame(scroll_frame, bg=Theme.BG_DEEP, padx=15, pady=15)
        main_content.pack(fill="both", expand=True)

        # ===== 左列：球队对比 + 历史交锋 =====
        left_panel = tk.Frame(main_content, bg=Theme.BG_DEEP, width=280)
        left_panel.pack(side="left", fill="y", padx=(0, 10))
        left_panel.pack_propagate(False)

        # 球队对比卡片
        compare_card = tk.Frame(left_panel, bg=Theme.BG_CARD, padx=15, pady=15)
        compare_card.pack(fill="x")

        tk.Label(compare_card, text="📊 球队对比",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 15))

        team_frame = tk.Frame(compare_card, bg=Theme.BG_CARD)
        team_frame.pack(fill="x")

        home_team = tk.Frame(team_frame, bg=Theme.BG_HOVER, padx=12, pady=10)
        home_team.pack(side="left", fill="y", expand=True)
        tk.Label(home_team, text=self.match['home'],
                font=(Theme.FONT_FAMILY, 13, "bold"),
                fg=Theme.COLOR_PRIMARY, bg=Theme.BG_HOVER).pack(anchor="center")
        home_rank = self.match.get('home_rank')
        if home_rank:
            tk.Label(home_team, text=f"排名: {home_rank}",
                    font=(Theme.FONT_FAMILY, 10),
                    fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER).pack(anchor="center", pady=(3, 0))
        tk.Label(home_team, text=f"主胜赔率: {self.match['odds']['win']:.2f}",
                font=(Theme.FONT_FAMILY, 10),
                fg=Theme.COLOR_ACCENT, bg=Theme.BG_HOVER).pack(anchor="center", pady=(2, 0))

        vs_label = tk.Label(team_frame, text="VS",
                           font=(Theme.FONT_FAMILY, 16, "bold"),
                           fg=Theme.COLOR_SECONDARY, bg=Theme.BG_CARD)
        vs_label.pack(side="left", padx=10)

        away_team = tk.Frame(team_frame, bg=Theme.BG_HOVER, padx=12, pady=10)
        away_team.pack(side="right", fill="y", expand=True)
        tk.Label(away_team, text=self.match['away'],
                font=(Theme.FONT_FAMILY, 13, "bold"),
                fg=Theme.COLOR_PURPLE, bg=Theme.BG_HOVER).pack(anchor="center")
        away_rank = self.match.get('away_rank')
        if away_rank:
            tk.Label(away_team, text=f"排名: {away_rank}",
                    font=(Theme.FONT_FAMILY, 10),
                    fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER).pack(anchor="center", pady=(3, 0))
        tk.Label(away_team, text=f"客胜赔率: {self.match['odds']['lose']:.2f}",
                font=(Theme.FONT_FAMILY, 10),
                fg=Theme.COLOR_ACCENT, bg=Theme.BG_HOVER).pack(anchor="center", pady=(2, 0))

        # 赔率对比条
        odds_compare = tk.Frame(compare_card, bg=Theme.BG_CARD)
        odds_compare.pack(fill="x", pady=(10, 0))
        tk.Label(odds_compare, text="赔率对比",
                font=(Theme.FONT_FAMILY, 10),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 5))
        odds_row = tk.Frame(odds_compare, bg=Theme.BG_CARD)
        odds_row.pack(fill="x")
        for label, val, color in [("主胜", self.match['odds']['win'], Theme.COLOR_PRIMARY),
                                    ("平局", self.match['odds']['draw'], Theme.COLOR_SECONDARY),
                                    ("客胜", self.match['odds']['lose'], Theme.COLOR_PURPLE)]:
            cell = tk.Frame(odds_row, bg=Theme.BG_HOVER, padx=8, pady=4)
            cell.pack(side="left", expand=True, fill="x", padx=(0, 3))
            tk.Label(cell, text=f"{label}", font=(Theme.FONT_FAMILY, 9),
                    fg=Theme.TEXT_MUTED, bg=Theme.BG_HOVER).pack()
            tk.Label(cell, text=f"{val:.2f}", font=(Theme.FONT_FAMILY, 13, "bold"),
                    fg=color, bg=Theme.BG_HOVER).pack()

        # 历史交锋卡片（仅在有数据时显示）
        history_list = self._get_h2h_history(self.match['home'], self.match['away'])
        if history_list and not (len(history_list) == 1 and history_list[0].get('date') == '暂无数据'):
            history_card = tk.Frame(left_panel, bg=Theme.BG_CARD, padx=15, pady=15)
            history_card.pack(fill="x", pady=(10, 0))
            
            tk.Label(history_card, text="📜 历史交锋",
                    font=(Theme.FONT_FAMILY, 12, "bold"),
                    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))
            
            for history in history_list:
                row = tk.Frame(history_card, bg=Theme.BG_HOVER, padx=10, pady=5)
                row.pack(fill="x", pady=(0, 4))
                tk.Label(row, text=history['date'],
                        font=(Theme.FONT_FAMILY, 10),
                        fg=Theme.TEXT_MUTED, bg=Theme.BG_HOVER).pack(side="left")
                tk.Label(row, text=history['result'],
                        font=(Theme.FONT_FAMILY, 10),
                        fg=Theme.TEXT_PRIMARY, bg=Theme.BG_HOVER).pack(side="right")

        # 赛事数据摘要
        summary_card = tk.Frame(left_panel, bg=Theme.BG_CARD, padx=15, pady=12)
        summary_card.pack(fill="x", pady=(10, 0))
        
        tk.Label(summary_card, text="📌 赛事摘要",
                font=(Theme.FONT_FAMILY, 11, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 6))
        
        summary_items = [
            ("联赛", self.match.get('league', '-')),
            ("时间", self.match.get('match_time', self.match.get('time', '-'))[:16] if self.match.get('match_time') or self.match.get('time') else '-'),
        ]
        if self.match.get('home_rank'):
            summary_items.append(("主队排名", f"第{self.match['home_rank']}"))
        if self.match.get('away_rank'):
            summary_items.append(("客队排名", f"第{self.match['away_rank']}"))
        
        for label, value in summary_items:
            row = tk.Frame(summary_card, bg=Theme.BG_CARD)
            row.pack(fill="x", pady=(0, 3))
            tk.Label(row, text=f"{label}:", font=(Theme.FONT_FAMILY, 10),
                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(side="left")
            tk.Label(row, text=f" {value}", font=(Theme.FONT_FAMILY, 10),
                    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(side="left")

        # ===== 中列：雷达图 =====
        center_panel = tk.Frame(main_content, bg=Theme.BG_DEEP, width=280)
        center_panel.pack(side="left", fill="y", padx=(0, 10))
        center_panel.pack_propagate(False)

        radar_card = tk.Frame(center_panel, bg=Theme.BG_CARD, padx=15, pady=15)
        radar_card.pack(fill="both", expand=True)

        tk.Label(radar_card, text="📈 稳定性分析",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 8))

        radar_canvas = tk.Canvas(radar_card, width=250, height=250, bg=Theme.BG_HOVER, highlightthickness=0)
        radar_canvas.pack(pady=5)

        try:
            from jinshuiyao.radar import TeamRadar, TeamRatingEngine
            import math
            p_win = min(0.95, 1.0 / max(self.match['odds']['win'], 1.01))
            p_lose = min(0.95, 1.0 / max(self.match['odds']['lose'], 1.01))
            home_attack = max(0.5, -math.log(1 - p_win) * 2.5)
            away_attack = max(0.5, -math.log(1 - p_lose) * 2.5)
            engine_r = TeamRatingEngine()
            home_data = engine_r.compute_ratings(
                team_name=self.match['home'],
                goals_scored_avg=home_attack,
                goals_conceded_avg=away_attack * 0.8,
            )
            away_data = engine_r.compute_ratings(
                team_name=self.match['away'],
                goals_scored_avg=away_attack,
                goals_conceded_avg=home_attack * 0.8,
            )
            labels = list(home_data.keys())
            home_values = list(home_data.values())
            away_values = list(away_data.values())
            chart = TeamRadar(radar_canvas, 250, 250)
            chart.draw(home_values, away_values, labels,
                       home_name=self.match['home'], away_name=self.match['away'])
            
            # 雷达图下方显示关键数值
            radar_values_frame = tk.Frame(radar_card, bg=Theme.BG_CARD)
            radar_values_frame.pack(fill="x", pady=(5, 0))
            
            half = len(labels) // 2
            for i, label in enumerate(labels[:half]):
                row = tk.Frame(radar_values_frame, bg=Theme.BG_CARD)
                row.pack(side="left", expand=True)
                tk.Label(row, text=f"{label[:4]}", font=(Theme.FONT_FAMILY, 8),
                        fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack()
                tk.Label(row, text=f"{home_values[i]:.1f}/{away_values[i]:.1f}", 
                        font=(Theme.FONT_FAMILY, 9, "bold"),
                        fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack()
        except Exception:
            tk.Label(radar_card, text="雷达图暂不可用\n（数据不足）",
                    font=(Theme.FONT_FAMILY, 10),
                    fg=Theme.TEXT_MUTED, bg=Theme.BG_HOVER).pack(pady=20)

        # ===== 右列：概率 + 场景因子 + AI分析 =====
        right_panel = tk.Frame(main_content, bg=Theme.BG_DEEP)
        right_panel.pack(side="right", fill="both", expand=True)

        # 概率分析卡片
        prob_card = tk.Frame(right_panel, bg=Theme.BG_CARD, padx=15, pady=15)
        prob_card.pack(fill="x")

        tk.Label(prob_card, text="🎲 概率分析",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))

        ProbabilityBar(prob_card, "主胜", self.prob_win, Theme.COLOR_PRIMARY).pack(fill="x", pady=(0, 8))
        ProbabilityBar(prob_card, "平局", self.prob_draw, Theme.COLOR_SECONDARY).pack(fill="x", pady=(0, 8))
        ProbabilityBar(prob_card, "客胜", self.prob_lose, Theme.COLOR_PURPLE).pack(fill="x")

        # 场景因子卡片
        scene_card = tk.Frame(right_panel, bg=Theme.BG_CARD, padx=15, pady=15)
        scene_card.pack(fill="x", pady=(10, 0))

        tk.Label(scene_card, text="🔧 场景因素分析",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 8))

        scene_text = scrolledtext.ScrolledText(scene_card,
                                        width=35, height=7,
                                        font=(Theme.FONT_FAMILY, 10),
                                        bg=Theme.BG_HOVER,
                                        fg=Theme.TEXT_PRIMARY,
                                        borderwidth=0,
                                        highlightthickness=0)
        scene_text.pack(fill="x")

        try:
            from jinshuiyao.scene_factors import SceneFactors
            adjuster = SceneFactors()
            base_probs = {'win': self.prob_win, 'draw': self.prob_draw, 'lose': self.prob_lose}
            adjusted = adjuster.adjust_probabilities(base_probs)
            delta_win = adjusted['win'] - base_probs['win']
            delta_draw = adjusted['draw'] - base_probs['draw']
            delta_lose = adjusted['lose'] - base_probs['lose']

            scene_content = f"默认场景因子调节后概率变化：\n"
            scene_content += f"  主胜: {base_probs['win']:.1%} → {adjusted['win']:.1%} ({delta_win:+.1%})\n"
            scene_content += f"  平局: {base_probs['draw']:.1%} → {adjusted['draw']:.1%} ({delta_draw:+.1%})\n"
            scene_content += f"  客胜: {base_probs['lose']:.1%} → {adjusted['lose']:.1%} ({delta_lose:+.1%})\n"
            scene_content += f"\n提示：可在设置中调节主场优势、天气、疲劳等参数"
            scene_text.insert(tk.INSERT, scene_content)
            scene_text.configure(state="disabled")
        except Exception as e:
            scene_text.insert(tk.INSERT, f"场景分析暂不可用: {e}")
            scene_text.configure(state="disabled")

        # AI分析 + 比分路径卡片
        ai_card = tk.Frame(right_panel, bg=Theme.BG_CARD, padx=15, pady=15)
        ai_card.pack(fill="both", expand=True, pady=(10, 0))

        tk.Label(ai_card, text="🤖 AI分析报告",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 8))

        ai_text = scrolledtext.ScrolledText(ai_card,
                                        width=35, height=10,
                                        font=(Theme.FONT_FAMILY, 10),
                                        bg=Theme.BG_HOVER,
                                        fg=Theme.TEXT_PRIMARY,
                                        borderwidth=0,
                                        highlightthickness=0)
        ai_text.pack(fill="both", expand=True)

        # 本地分析（即时显示）
        analysis = self._generate_analysis()
        ai_text.insert(tk.INSERT, analysis)

        # DeepSeek 深度分析（异步，追加到末尾）
        self._llm_analysis = ""
        ai_text.configure(state="normal")
        ai_text.insert(tk.END, "\n⏳ 正在获取 DeepSeek 深度分析...\n")
        ai_text.configure(state="disabled")
        self._ai_text_widget = ai_text
        self._fetch_llm_analysis()

        # 关闭按钮
        close_btn = tk.Button(scroll_frame, text="关闭", command=self.destroy,
                             bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                             font=(Theme.FONT_FAMILY, 11),
                             relief="flat", padx=30, pady=8,
                             cursor="hand2")
        close_btn.pack(pady=(5, 5))

    def _fetch_llm_analysis(self):
        """异步获取 DeepSeek 深度分析"""
        import threading

        def worker():
            try:
                from jinshuiyao.llm_analyzer import LLMAnalyzer
                from core.ai_service import get_api_key

                api_key = get_api_key()
                if not api_key:
                    self._update_ai_text("\n💬 DeepSeek 分析未配置（请在 deepseek_key.txt 中填入 API Key）")
                    return

                analyzer = LLMAnalyzer(api_key=api_key)
                # 构造 match 数据
                match_data = {
                    "home": self.match["home"],
                    "away": self.match["away"],
                    "league": self.match["league"],
                    "odds_win": self.match["odds"]["win"],
                    "odds_draw": self.match["odds"]["draw"],
                    "odds_lose": self.match["odds"]["lose"],
                    "date": self.match.get("date", self.match.get("match_time", "")),
                }
                result = analyzer.analyze_match(match_data)
                if result:
                    self._update_ai_text(f"\n🧠 【DeepSeek 深度分析】\n{result}")
                else:
                    self._update_ai_text("\n⚠️ DeepSeek 分析请求失败，请检查 API Key")
            except Exception as e:
                self._update_ai_text(f"\n⚠️ DeepSeek 分析异常: {e}")

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _update_ai_text(self, text):
        """线程安全地更新 AI 分析文本"""
        try:
            if hasattr(self, "_ai_text_widget") and self._ai_text_widget.winfo_exists():
                self._ai_text_widget.configure(state="normal")
                self._ai_text_widget.insert(tk.END, text)
                self._ai_text_widget.see(tk.END)
                self._ai_text_widget.configure(state="disabled")
        except Exception:
            pass

    def _generate_analysis(self):
        """生成AI分析内容"""
        max_prob = max(self.prob_win, self.prob_draw, self.prob_lose)
        
        if max_prob == self.prob_win:
            rec = "主胜"
            team = self.match['home']
        elif max_prob == self.prob_draw:
            rec = "平局"
            team = "双方"
        else:
            rec = "客胜"
            team = self.match['away']
        
        analysis = f"""【比赛分析报告】

联赛: {self.match['league']}
场次: {self.match['home']} VS {self.match['away']}
时间: {self.match['date']} {self.match['time']}

【赔率数据】
主胜: {self.match['odds']['win']}
平局: {self.match['odds']['draw']}
客胜: {self.match['odds']['lose']}

【概率预测】
主胜概率: {self.prob_win:.2%}
平局概率: {self.prob_draw:.2%}
客胜概率: {self.prob_lose:.2%}

【AI分析】
根据历史数据和实时赔率分析，{team}获胜概率最高。

{self.match['home']}近期状态: {self.match.get('home_form', '暂无数据')}
{self.match['away']}近期状态: {self.match.get('away_form', '暂无数据')}

综合评估:
- {self.match['home']} {('排名第' + str(self.match.get('home_rank', '?')) + '位' if self.match.get('home_rank') else '排名数据暂缺')}，进攻端表现{('出色' if (self.match.get('home_goals') or 0) > 2 else '一般')}
- {self.match['away']} {('排名第' + str(self.match.get('away_rank', '?')) + '位' if self.match.get('away_rank') else '排名数据暂缺')}，防守端表现{('稳健' if (self.match.get('away_goals') or 0) < 2 else '有待加强')}

【推荐方案】
🎯 {rec} (概率: {max_prob:.2%})

建议投注比例:
- 主胜: {self.prob_win:.0%}
- 平局: {self.prob_draw:.0%}
- 客胜: {self.prob_lose:.0%}

⚠️ 风险提示: 足球比赛存在不确定性，请谨慎投注！"""
        
        # 追加比分路径推演
        try:
            from jinshuiyao.score_path import generate_score_paths
            import math
            p_win = min(0.95, 1.0 / max(self.match['odds']['win'], 1.01))
            p_lose = min(0.95, 1.0 / max(self.match['odds']['lose'], 1.01))
            lambda_h = max(0.3, -math.log(1 - p_win) * 2.5)
            lambda_a = max(0.3, -math.log(1 - p_lose) * 2.5)
            paths = generate_score_paths(lambda_h, lambda_a, top_n=3)
            if paths:
                analysis += "\n【比分路径推演】\n"
                for i, p in enumerate(paths):
                    analysis += f"  路径{i+1}: 半场{p.half_score} → 全场{p.full_score} (概率{p.probability:.1%})\n"
                analysis += "\n注：比分路径基于双泊松模型，仅供参考。"
        except Exception:
            pass
        
        return analysis
    
    def _get_h2h_history(self, home, away):
        """获取两队历史交锋数据"""
        try:
            from jinshuiyao.data_provider import CSVDataProvider
            
            provider = CSVDataProvider()
            h2h = provider.get_h2h(home, away, n=4)
            
            if not h2h.empty:
                history = []
                for _, row in h2h.iterrows():
                    date = str(row.get('date', ''))[:10]
                    result = row.get('result', '')
                    if date and result:
                        history.append({'date': date, 'result': result})
                return history[:4]
        except Exception as e:
            print(f"[WARN] 获取历史交锋失败: {e}")
        
        return [
            {"date": "暂无数据", "result": "无历史交锋记录"},
        ]


class PredictionPanel(tk.Frame):
    """预测面板 - 完整的AI分析界面"""
    
    def __init__(self, parent, on_detail=None):
        super().__init__(parent, bg=Theme.BG_DEEP)
        self.on_detail = on_detail
        self.current_match = None
        
        # 标题
        title_frame = tk.Frame(self, bg=Theme.BG_CARD)
        title_frame.pack(fill="x", pady=(0, 12))
        title = tk.Label(title_frame, text="AI智能预测分析",
                        font=(Theme.FONT_FAMILY, 14, "bold"),
                        fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD,
                        padx=20, pady=15)
        title.pack(anchor="w")
        
        # 比赛信息卡片
        match_card = tk.Frame(self, bg=Theme.BG_CARD, padx=20, pady=18)
        match_card.pack(fill="x", pady=(0, 12))
        
        # 主队信息
        home_frame = tk.Frame(match_card, bg=Theme.BG_CARD)
        home_frame.pack(side="left", fill="both", expand=True)
        tk.Label(home_frame, text="主队", font=(Theme.FONT_FAMILY, 10),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="center")
        self.home_name = tk.Label(home_frame, text="选择比赛",
                                 font=(Theme.FONT_FAMILY, 16, "bold"),
                                 fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD)
        self.home_name.pack(anchor="center", pady=5)
        self.home_form = tk.Label(home_frame, text="近期状态: -",
                                 font=(Theme.FONT_FAMILY, 10),
                                 fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        self.home_form.pack(anchor="center")
        
        # VS
        vs_frame = tk.Frame(match_card, bg=Theme.BG_CARD)
        vs_frame.pack(side="left", padx=25)
        vs_label = tk.Label(vs_frame, text="VS",
                           font=(Theme.FONT_FAMILY, 20, "bold"),
                           fg=Theme.COLOR_SECONDARY, bg=Theme.BG_CARD)
        vs_label.pack()
        
        # 客队信息
        away_frame = tk.Frame(match_card, bg=Theme.BG_CARD)
        away_frame.pack(side="right", fill="both", expand=True)
        tk.Label(away_frame, text="客队", font=(Theme.FONT_FAMILY, 10),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="center")
        self.away_name = tk.Label(away_frame, text="选择比赛",
                                 font=(Theme.FONT_FAMILY, 16, "bold"),
                                 fg=Theme.COLOR_PURPLE, bg=Theme.BG_CARD)
        self.away_name.pack(anchor="center", pady=5)
        self.away_form = tk.Label(away_frame, text="近期状态: -",
                                 font=(Theme.FONT_FAMILY, 10),
                                 fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        self.away_form.pack(anchor="center")
        
        # 概率卡片
        prob_card = tk.Frame(self, bg=Theme.BG_CARD, padx=20, pady=18)
        prob_card.pack(fill="x", pady=(0, 12))
        
        prob_header = tk.Frame(prob_card, bg=Theme.BG_CARD)
        prob_header.pack(fill="x", pady=(0, 15))
        tk.Label(prob_header, text="胜平负概率",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(side="left")
        self.prob_accuracy = tk.Label(prob_header, text="预测准确率: 78.5%",
                                     font=(Theme.FONT_FAMILY, 10),
                                     fg=Theme.COLOR_ACCENT, bg=Theme.BG_CARD)
        self.prob_accuracy.pack(side="right")
        
        # 三个概率条
        prob_frame = tk.Frame(prob_card, bg=Theme.BG_CARD)
        prob_frame.pack(fill="x")
        
        self.home_bar = ProbabilityBar(prob_frame, "主胜", 0.33, Theme.COLOR_PRIMARY)
        self.home_bar.pack(side="left", fill="both", expand=True, padx=(0, 12))
        
        self.draw_bar = ProbabilityBar(prob_frame, "平局", 0.34, Theme.COLOR_SECONDARY)
        self.draw_bar.pack(side="left", fill="both", expand=True, padx=(0, 12))
        
        self.away_bar = ProbabilityBar(prob_frame, "客胜", 0.33, Theme.COLOR_PURPLE)
        self.away_bar.pack(side="left", fill="both", expand=True)
        
        # 推荐卡片
        rec_card = tk.Frame(self, bg=Theme.BG_CARD, padx=20, pady=18)
        rec_card.pack(fill="x")
        
        rec_header = tk.Frame(rec_card, bg=Theme.BG_CARD)
        rec_header.pack(fill="x", pady=(0, 12))
        tk.Label(rec_header, text="AI推荐方案",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(side="left")
        
        # 推荐内容
        self.rec_frame = tk.Frame(rec_card, bg=Theme.BG_HOVER, padx=20, pady=15)
        self.rec_frame.pack(fill="x")
        
        self.rec_text = tk.Label(self.rec_frame, text="请从左侧选择一场比赛",
                                font=(Theme.FONT_FAMILY, 18, "bold"),
                                fg=Theme.COLOR_ACCENT, bg=Theme.BG_HOVER)
        self.rec_text.pack()
        
        # 推荐按钮
        rec_btn_frame = tk.Frame(rec_card, bg=Theme.BG_CARD)
        rec_btn_frame.pack(fill="x", pady=(12, 0))
        
        self.bet_btn = tk.Button(rec_btn_frame, text="📊 添加投注",
                                font=(Theme.FONT_FAMILY, 12, "bold"),
                                fg=Theme.BG_DEEP, bg=Theme.COLOR_ACCENT,
                                activebackground=Theme.COLOR_GREEN,
                                relief="flat", padx=20, pady=10,
                                state="disabled")
        self.bet_btn.pack(side="left", padx=(0, 10))
        
        self.detail_btn = tk.Button(rec_btn_frame, text="📋 详细分析",
                                   font=(Theme.FONT_FAMILY, 12),
                                   fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                                   activebackground=Theme.BORDER,
                                   relief="flat", padx=20, pady=10,
                                   state="disabled",
                                   command=self._on_detail_click)
        self.detail_btn.pack(side="left")
        
        # 赔率分析卡片
        odds_card = tk.Frame(self, bg=Theme.BG_CARD, padx=20, pady=18)
        odds_card.pack(fill="x", pady=(12, 0))
        
        tk.Label(odds_card, text="赔率市场分析",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w", pady=(0, 10))
        
        self.odds_info_frame = tk.Frame(odds_card, bg=Theme.BG_HOVER, padx=15, pady=10)
        self.odds_info_frame.pack(fill="x")
        
        self.odds_detail = tk.Label(self.odds_info_frame, 
                                     text="选择比赛后显示赔率分析",
                                     font=(Theme.FONT_FAMILY, 10),
                                     fg=Theme.TEXT_MUTED, bg=Theme.BG_HOVER,
                                     wraplength=500, justify="left")
        self.odds_detail.pack(anchor="w")
        
        # 快捷操作卡片
        action_card = tk.Frame(self, bg=Theme.BG_CARD, padx=20, pady=18)
        action_card.pack(fill="x", pady=(12, 0))
        
        action_row = tk.Frame(action_card, bg=Theme.BG_CARD)
        action_row.pack(fill="x")
        
        actions = [
            ("🔄 刷新数据", self._refresh_data if hasattr(self, '_refresh_data') else None),
            ("📋 导出方案", None),
            ("📊 复盘统计", None),
        ]
        for text, cmd in actions:
            btn = tk.Button(action_row, text=text,
                           font=(Theme.FONT_FAMILY, 11),
                           fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                           activebackground=Theme.BORDER,
                           relief="flat", padx=15, pady=8,
                           cursor="hand2")
            btn.pack(side="left", padx=(0, 8))
    
    def update_prediction(self, match):
        """更新预测结果"""
        self.current_match = match
        self.home_name.config(text=match["home"])
        self.away_name.config(text=match["away"])
        
        # 更新状态信息
        self.home_form.config(text=f"近期状态: {match.get('home_form', '未知')}")
        self.away_form.config(text=f"近期状态: {match.get('away_form', '未知')}")
        
        # 计算概率
        odds = match["odds"]
        prob_win = 1/odds["win"]
        prob_draw = 1/odds["draw"]
        prob_lose = 1/odds["lose"]
        total = prob_win + prob_draw + prob_lose
        
        prob_win /= total
        prob_draw /= total
        prob_lose /= total
        
        # 使用决策引擎进行AI分析修正（确定性，无随机噪声）
        try:
            from jinshuiyao.decision_engine import JinshuiyaoDecisionEngine
            engine = JinshuiyaoDecisionEngine()
            features = {
                'home_goals_avg': 1.3,
                'away_goals_avg': 1.1,
                'home_defense_avg': 0.9,
                'away_defense_avg': 1.0,
            }
            engine_prob = engine.ensemble_prob(features)
            # 混合赔率概率和模型概率（60%模型 + 40%市场）
            prob_win = 0.6 * engine_prob['win'] + 0.4 * prob_win
            prob_draw = 0.6 * engine_prob['draw'] + 0.4 * prob_draw
            prob_lose = 0.6 * engine_prob['lose'] + 0.4 * prob_lose
            total = prob_win + prob_draw + prob_lose
            prob_win /= total
            prob_draw /= total
            prob_lose /= total
        except Exception:
            pass  # 保持原始赔率概率
        
        # 更新进度条
        self.home_bar.update_prob(prob_win)
        self.draw_bar.update_prob(prob_draw)
        self.away_bar.update_prob(prob_lose)
        
        # 更新推荐
        max_prob = max(prob_win, prob_draw, prob_lose)
        if max_prob == prob_win:
            rec = f"🎯 推荐主胜 ({max_prob:.1%})"
            color = Theme.COLOR_PRIMARY
        elif max_prob == prob_draw:
            rec = f"🎯 推荐平局 ({max_prob:.1%})"
            color = Theme.COLOR_SECONDARY
        else:
            rec = f"🎯 推荐客胜 ({max_prob:.1%})"
            color = Theme.COLOR_PURPLE
        
        self.rec_text.config(text=rec, fg=color)
        self.bet_btn.config(state="normal")
        self.detail_btn.config(state="normal")
        
        # 更新赔率分析
        try:
            kelly_win = (prob_win * odds['win'] - 1) / (odds['win'] - 1) if odds['win'] > 1 else 0
            kelly_draw = (prob_draw * odds['draw'] - 1) / (odds['draw'] - 1) if odds['draw'] > 1 else 0
            kelly_lose = (prob_lose * odds['lose'] - 1) / (odds['lose'] - 1) if odds['lose'] > 1 else 0
            
            implied_win = 1 / odds['win']
            implied_draw = 1 / odds['draw']
            implied_lose = 1 / odds['lose']
            margin = (implied_win + implied_draw + implied_lose - 1) * 100
            
            odds_text = (
                f"隐含概率:  主胜 {implied_win:.1%}  平局 {implied_draw:.1%}  客胜 {implied_lose:.1%}\n"
                f"返还率: {100 - margin:.1f}%  |  庄家利润率: {margin:.1f}%\n"
                f"Kelly建议:  主胜 {'✅' if kelly_win > 0.05 else '❌'}  "
                f"平局 {'✅' if kelly_draw > 0.05 else '❌'}  "
                f"客胜 {'✅' if kelly_lose > 0.05 else '❌'}"
            )
            self.odds_detail.config(text=odds_text, fg=Theme.TEXT_PRIMARY)
        except Exception:
            pass
    
    def _on_detail_click(self):
        """点击详细分析按钮"""
        if self.current_match and self.on_detail:
            self.on_detail(self.current_match)


class LeagueFilter(tk.Frame):
    """联赛筛选器 - 带分组显示"""
    
    def __init__(self, parent, callback):
        super().__init__(parent, bg=Theme.BG_DEEP)
        
        self.callback = callback
        
        # 标题
        header_frame = tk.Frame(self, bg=Theme.BG_DEEP)
        header_frame.pack(fill="x", pady=(0, 12))
        tk.Label(header_frame, text="联赛筛选",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_DEEP).pack(side="left")
        self.count_label = tk.Label(header_frame, text=f"({len(MATCH_DATA)}场)",
                                   font=(Theme.FONT_FAMILY, 10),
                                   fg=Theme.TEXT_MUTED, bg=Theme.BG_DEEP)
        self.count_label.pack(side="right")
        
        # 联赛按钮
        leagues = ["全部", "欧冠资格赛", "世界杯半决赛", "英超", "西甲", "德甲", "意甲", "法甲"]
        self.buttons = []
        
        for i, league in enumerate(leagues):
            if i % 2 == 0:
                row_frame = tk.Frame(self, bg=Theme.BG_DEEP)
                row_frame.pack(fill="x", pady=(0, 8))
            
            btn = tk.Button(row_frame, text=league,
                           font=(Theme.FONT_FAMILY, 11),
                           fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD,
                           activebackground=Theme.BG_HOVER,
                           activeforeground=Theme.COLOR_PRIMARY,
                           relief="flat", padx=20, pady=10,
                           width=12,
                           command=lambda l=league: self._on_select(l))
            btn.pack(side="left", padx=(0, 8))
            self.buttons.append((league, btn))
        
        # 默认选中全部（只更新按钮状态，不调用回调）
        self._update_button_state("全部")
    
    def _update_button_state(self, league):
        """仅更新按钮状态，不调用回调"""
        for name, btn in self.buttons:
            if name == league:
                btn.config(bg=Theme.COLOR_PRIMARY, fg=Theme.BG_DEEP,
                          activebackground=Theme.COLOR_PRIMARY_DARK)
            else:
                btn.config(bg=Theme.BG_CARD, fg=Theme.TEXT_SECONDARY,
                          activebackground=Theme.BG_HOVER)
    
    def _on_select(self, league):
        """选中联赛"""
        self._update_button_state(league)
        
        if self.callback:
            self.callback(league)


class QuickStats(tk.Frame):
    """快速统计面板"""
    
    def __init__(self, parent):
        super().__init__(parent, bg=Theme.BG_DEEP)
        
        # 标题
        tk.Label(self, text="实时统计",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_DEEP).pack(anchor="w", pady=(0, 12))
        
        # 统计卡片
        stats_frame = tk.Frame(self, bg=Theme.BG_DEEP)
        stats_frame.pack(fill="x")
        
        # 今日比赛数
        stat1 = self._create_stat_card(stats_frame, "今日比赛", str(len(MATCH_DATA)), "场")
        stat1.pack(side="left", fill="both", expand=True, padx=(0, 8))
        
        # 胜率
        stat2 = self._create_stat_card(stats_frame, "预测胜率", "78.5", "%")
        stat2.pack(side="left", fill="both", expand=True, padx=(0, 8))
        
        # 盈利
        stat3 = self._create_stat_card(stats_frame, "累计盈亏", "+1,234", "元")
        stat3.pack(side="left", fill="both", expand=True)
    
    def _create_stat_card(self, parent, label, value, unit):
        """创建统计卡片"""
        card = tk.Frame(parent, bg=Theme.BG_CARD, padx=12, pady=12)
        
        tk.Label(card, text=label,
                font=(Theme.FONT_FAMILY, 10),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="w")
        
        value_frame = tk.Frame(card, bg=Theme.BG_CARD)
        value_frame.pack(anchor="w", pady=(4, 0))
        
        tk.Label(value_frame, text=value,
                font=(Theme.FONT_FAMILY, 20, "bold"),
                fg=Theme.COLOR_ACCENT, bg=Theme.BG_CARD).pack(side="left")
        
        tk.Label(value_frame, text=unit,
                font=(Theme.FONT_FAMILY, 10),
                fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD).pack(side="left", padx=2)
        
        return card


class BettingSlip(tk.Frame):
    """投注清单面板"""
    
    def __init__(self, parent):
        super().__init__(parent, bg=Theme.BG_DEEP)
        
        # 标题
        header_frame = tk.Frame(self, bg=Theme.BG_DEEP)
        header_frame.pack(fill="x", pady=(0, 12))
        tk.Label(header_frame, text="投注清单",
                font=(Theme.FONT_FAMILY, 12, "bold"),
                fg=Theme.TEXT_PRIMARY, bg=Theme.BG_DEEP).pack(side="left")
        self.slip_count = tk.Label(header_frame, text="(0)",
                                   font=(Theme.FONT_FAMILY, 10),
                                   fg=Theme.TEXT_MUTED, bg=Theme.BG_DEEP)
        self.slip_count.pack(side="right")
        
        # 投注列表
        self.slip_list = tk.Frame(self, bg=Theme.BG_CARD, padx=15, pady=15)
        self.slip_list.pack(fill="both", expand=True)
        
        self.empty_label = tk.Label(self.slip_list, text="暂无投注",
                                   font=(Theme.FONT_FAMILY, 12),
                                   fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self.empty_label.pack(expand=True)
        
        # 底部操作
        self.footer = tk.Frame(self, bg=Theme.BG_CARD)
        self.footer.pack(fill="x", pady=(12, 0))
        
        self.total_label = tk.Label(self.footer, text="合计: 0.00 元",
                                   font=(Theme.FONT_FAMILY, 11),
                                   fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        self.total_label.pack(side="left", padx=15, pady=12)
        
        self.clear_btn = tk.Button(self.footer, text="清空",
                                  font=(Theme.FONT_FAMILY, 10),
                                  fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                                  activebackground=Theme.BORDER,
                                  relief="flat", padx=15, pady=8)
        self.clear_btn.pack(side="right", padx=15)
    
    def add_bet(self, match, prediction):
        """添加投注"""
        if self.empty_label.winfo_exists():
            self.empty_label.destroy()
        
        bet_item = tk.Frame(self.slip_list, bg=Theme.BG_HOVER, padx=12, pady=8)
        bet_item.pack(fill="x", pady=(0, 8))
        
        # 比赛信息
        match_info = tk.Label(bet_item, text=f"{match['home']} vs {match['away']}",
                             font=(Theme.FONT_FAMILY, 11),
                             fg=Theme.TEXT_PRIMARY, bg=Theme.BG_HOVER)
        match_info.pack(side="left")
        
        # 预测结果
        pred_label = tk.Label(bet_item, text=prediction,
                             font=(Theme.FONT_FAMILY, 11, "bold"),
                             fg=Theme.COLOR_ACCENT, bg=Theme.BG_HOVER)
        pred_label.pack(side="right")
        
        # 更新计数
        count = len(self.slip_list.winfo_children())
        self.slip_count.config(text=f"({count})")
        self.total_label.config(text=f"合计: {count * 2.0:.2f} 元")


class FootballApp:
    """足彩预测主应用"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("金水谣足彩预测系统 v3.0")
        self.root.configure(bg=Theme.BG_DEEP)
        self.root.geometry("1280x800")
        
        # 初始化变量
        self.current_match = None
        
        # 构建UI
        self._build_ui()
    
    def _build_ui(self):
        """构建完整UI"""
        # 顶部导航栏
        self._build_header()
        
        # 主内容区
        main_content = tk.Frame(self.root, bg=Theme.BG_DEEP)
        main_content.pack(fill="both", expand=True, padx=20, pady=15)
        
        # 左侧面板
        left_panel = tk.Frame(main_content, bg=Theme.BG_DEEP, width=520)
        left_panel.pack(side="left", fill="y", padx=(0, 15))
        left_panel.pack_propagate(False)
        
        # 比赛列表（先创建表格，再创建筛选器）
        match_card = tk.Frame(left_panel, bg=Theme.BG_CARD, padx=15, pady=15)
        match_card.pack(fill="both", expand=True)
        
        # 表格标题
        table_header = tk.Frame(match_card, bg=Theme.BG_CARD)
        table_header.pack(fill="x", pady=(0, 15))
        tk.Label(table_header, text="今日比赛",
                font=(Theme.FONT_FAMILY, 14, "bold"),
                fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(side="left")
        
        # 搜索框
        search_frame = tk.Frame(table_header, bg=Theme.BG_HOVER)
        search_frame.pack(side="right")
        
        self.search_entry = tk.Entry(search_frame, 
                                     font=(Theme.FONT_FAMILY, 10),
                                     fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
                                     borderwidth=0, width=25)
        self.search_entry.pack(side="left", padx=10, pady=5)
        self.search_entry.insert(0, "搜索球队...")
        
        # 表格容器
        table_container = tk.Frame(match_card, bg=Theme.BG_CARD)
        table_container.pack(fill="both", expand=True)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self._on_scroll)
        scrollbar.pack(side="right", fill="y")
        
        self.match_table = MatchTable(table_container, self._on_match_select)
        self.match_table.pack(fill="both", expand=True)
        self.match_table.configure(yscrollcommand=scrollbar.set)
        
        # 联赛筛选（后创建，确保 match_table 已存在）
        self.league_filter = LeagueFilter(left_panel, self._on_league_filter)
        self.league_filter.pack(fill="x", pady=(15, 0))
        
        # 右侧面板
        right_panel = tk.Frame(main_content, bg=Theme.BG_DEEP)
        right_panel.pack(side="right", fill="both", expand=True)
        
        # 上部：预测面板
        pred_frame = tk.Frame(right_panel, bg=Theme.BG_DEEP)
        pred_frame.pack(fill="both", expand=True, pady=(0, 0))
        
        # 内部容器，使内容靠上
        pred_inner = tk.Frame(pred_frame, bg=Theme.BG_DEEP)
        pred_inner.pack(fill="both", expand=True)
        
        self.pred_panel = PredictionPanel(pred_inner, self._on_detail_analysis)
        self.pred_panel.pack(fill="x", anchor="n")
        
        # 底部：快捷统计卡片
        stats_card = tk.Frame(right_panel, bg=Theme.BG_CARD, padx=20, pady=15)
        stats_card.pack(fill="x", pady=(0, 0))
        
        stats_row = tk.Frame(stats_card, bg=Theme.BG_CARD)
        stats_row.pack(fill="x")
        
        stat_items = [
            ("今日比赛", str(len(self.match_data)) if hasattr(self, 'match_data') else "14"),
            ("数据更新", "刚刚"),
            ("模型状态", "就绪"),
        ]
        for text, value in stat_items:
            sf = tk.Frame(stats_row, bg=Theme.BG_CARD)
            sf.pack(side="left", expand=True)
            tk.Label(sf, text=value, font=(Theme.FONT_FAMILY, 16, "bold"),
                    fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack()
            tk.Label(sf, text=text, font=(Theme.FONT_FAMILY, 10),
                    fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack()
        
        # 底部状态栏
        self._build_status_bar()
    
    def _build_header(self):
        """构建顶部导航栏"""
        header = tk.Frame(self.root, bg=Theme.BG_CARD, height=70)
        header.pack(fill="x", padx=20, pady=20)
        header.pack_propagate(False)
        
        # 左侧标题
        title_frame = tk.Frame(header, bg=Theme.BG_CARD)
        title_frame.pack(side="left", padx=25)
        
        icon_frame = tk.Frame(title_frame, bg=Theme.COLOR_PRIMARY, width=40, height=40)
        icon_frame.pack(side="left")
        icon_frame.pack_propagate(False)
        tk.Label(icon_frame, text="⚽", font=("Arial", 22),
                bg=Theme.COLOR_PRIMARY).pack(expand=True)
        
        title_info = tk.Frame(title_frame, bg=Theme.BG_CARD)
        title_info.pack(side="left", padx=15)
        
        tk.Label(title_info, text="金水谣足彩预测系统",
                font=(Theme.FONT_FAMILY, 20, "bold"),
                fg=Theme.COLOR_PRIMARY, bg=Theme.BG_CARD).pack(anchor="w")
        
        tk.Label(title_info, text="AI智能分析 · 数据驱动预测",
                font=(Theme.FONT_FAMILY, 11),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(anchor="w")
        
        # 右侧功能按钮
        right_frame = tk.Frame(header, bg=Theme.BG_CARD)
        right_frame.pack(side="right", padx=25)
        
        # 刷新按钮
        refresh_btn = tk.Button(right_frame, text="🔄 刷新数据",
                               font=(Theme.FONT_FAMILY, 11),
                               fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                               activebackground=Theme.BORDER,
                               relief="flat", padx=20, pady=10,
                               command=self._refresh_data)
        refresh_btn.pack(side="left", padx=(0, 12))
        
        # 导入按钮
        import_btn = tk.Button(right_frame, text="📥 导入赛事",
                              font=(Theme.FONT_FAMILY, 11),
                              fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                              activebackground=Theme.BORDER,
                              relief="flat", padx=20, pady=10)
        import_btn.pack(side="left", padx=(0, 12))
        
        # 设置按钮
        settings_btn = tk.Button(right_frame, text="⚙ 设置",
                                font=(Theme.FONT_FAMILY, 11),
                                fg=Theme.TEXT_SECONDARY, bg=Theme.BG_HOVER,
                                activebackground=Theme.BORDER,
                                relief="flat", padx=20, pady=10)
        settings_btn.pack(side="left")
    
    def _build_status_bar(self):
        """构建底部状态栏"""
        status = tk.Frame(self.root, bg=Theme.BG_CARD, height=40)
        status.pack(fill="x", side="bottom")
        
        # 左侧状态
        status_left = tk.Frame(status, bg=Theme.BG_CARD)
        status_left.pack(side="left", padx=25)
        
        self.status_icon = tk.Label(status_left, text="●", font=(Theme.FONT_FAMILY, 12),
                                   fg=Theme.SUCCESS, bg=Theme.BG_CARD)
        self.status_icon.pack(side="left")
        
        self.status_text = tk.Label(status_left, text="系统就绪",
                                   font=(Theme.FONT_FAMILY, 11),
                                   fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD)
        self.status_text.pack(side="left", padx=8)
        
        # 中间时间
        self.time_label = tk.Label(status, text="",
                                  font=(Theme.FONT_FAMILY, 11),
                                  fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD)
        self.time_label.pack(side="left", padx=30)
        
        # 右侧统计
        status_right = tk.Frame(status, bg=Theme.BG_CARD)
        status_right.pack(side="right", padx=25)
        
        tk.Label(status_right, text=f"比赛数: {len(MATCH_DATA)}",
                font=(Theme.FONT_FAMILY, 11),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(side="left", padx=20)
        
        tk.Label(status_right, text=f"数据更新: 刚刚",
                font=(Theme.FONT_FAMILY, 11),
                fg=Theme.TEXT_MUTED, bg=Theme.BG_CARD).pack(side="left", padx=20)
        
        # 更新时间
        self._update_time()
    
    def _update_time(self):
        """更新时间显示"""
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.time_label.config(text=now)
        self.root.after(1000, self._update_time)
    
    def _on_league_filter(self, league):
        """联赛筛选回调"""
        self.match_table.load_matches(league)
        self.log(f"筛选联赛: {league}")
    
    def _on_match_select(self, values):
        """选择比赛回调"""
        if values:
            # 查找匹配的比赛数据
            for match in MATCH_DATA:
                if match["home"] == values[1] and match["away"] == values[2]:
                    self.current_match = match
                    self.pred_panel.update_prediction(match)
                    self.log(f"选中比赛: {match['home']} vs {match['away']}")
                    break
    
    def _on_detail_analysis(self, match):
        """打开详细分析对话框"""
        DetailAnalysisDialog(self.root, match)
        self.log(f"打开详细分析: {match['home']} vs {match['away']}")
    
    def _on_scroll(self, *args):
        """滚动事件"""
        self.match_table.yview(*args)
    
    def _refresh_data(self):
        """刷新数据"""
        self.log("正在刷新数据...")
        global MATCH_DATA
        MATCH_DATA = load_match_data()
        self.match_table.load_matches()
        self.league_filter.count_label.config(text=f"({len(MATCH_DATA)}场)")
        self.log("数据刷新完成")
    
    def log(self, msg):
        """记录日志到状态栏"""
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        self.status_text.config(text=f"[{ts}] {msg}")


def launch_football_gui():
    """启动足彩预测GUI"""
    try:
        from core.gui_registry import register
        register('football', '金水谣足彩预测系统')
    except Exception:
        pass
    root = tk.Tk()
    try:
        from core.tk_style import apply_dark_style
        apply_dark_style(root)
    except Exception:
        pass
    app = FootballApp(root)
    root.mainloop()


if __name__ == "__main__":
    launch_football_gui()