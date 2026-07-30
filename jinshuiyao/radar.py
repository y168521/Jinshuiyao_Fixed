# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 六维雷达图

根据视频启发，实现 6 维度球队实力对比雷达图：
  1. 大赛经验    (基于世界排名/欧战经验)
  2. 世界排名    (FIFA 排名或联赛积分折算)
  3. 阵容身价    (球队总身价估值)
  4. 防守稳定    (近期场均失球)
  5. 进攻火力    (近期场均进球)
  6. 近期状态    (近 5 场战绩)

使用方式：
  radar = TeamRadar(canvas, width=300, height=300)
  radar.draw(home_values, away_values, labels, home_name="主队", away_name="客队")
"""

import math
import tkinter as tk
from typing import List, Dict


class TeamRadar:
    """六维雷达图 — 纯 Tkinter Canvas 实现（无外部依赖）"""

    # 配色
    HOME_COLOR = "#2196F3"      # 主队蓝
    HOME_FILL = "#BBDEFB"       # 主队半透明蓝
    AWAY_COLOR = "#FF5722"      # 客队橙
    AWAY_FILL = "#FFCCBC"       # 客队半透明橙
    GRID_COLOR = "#E0E0E0"      # 网格灰
    LABEL_COLOR = "#424242"     # 标签灰

    def __init__(self, canvas: tk.Canvas, width: int = 300, height: int = 300):
        self.cv = canvas
        self.w = width
        self.h = height
        self.cx = width / 2
        self.cy = height / 2
        self.radius = min(width, height) / 2 - 40

    def draw(
        self,
        home_values: List[float],
        away_values: List[float],
        labels: List[str],
        home_name: str = "主队",
        away_name: str = "客队",
    ):
        """绘制六维雷达图

        Args:
            home_values: 主队 6 维数值 (0~100)
            away_values: 客队 6 维数值 (0~100)
            labels: 6 维标签
            home_name: 主队名称
            away_name: 客队名称
        """
        self.cv.delete("all")
        n = len(labels)
        if n < 3:
            return

        angles = [math.pi / 2 - 2 * math.pi * i / n for i in range(n)]

        # 绘制同心网格（5 圈，每圈 20 分）
        for level in range(1, 6):
            r = self.radius * level / 5
            points = []
            for angle in angles:
                x = self.cx + r * math.cos(angle)
                y = self.cy - r * math.sin(angle)
                points.extend([x, y])
            self.cv.create_polygon(points, outline=self.GRID_COLOR,
                                    fill="", width=1, tags="grid")

        # 绘制轴线
        for i, angle in enumerate(angles):
            x = self.cx + self.radius * math.cos(angle)
            y = self.cy - self.radius * math.sin(angle)
            self.cv.create_line(self.cx, self.cy, x, y,
                                fill=self.GRID_COLOR, width=1, tags="axis")

            # 标签 (稍微往外放)
            lx = self.cx + (self.radius + 18) * math.cos(angle)
            ly = self.cy - (self.radius + 18) * math.sin(angle)
            lbl = labels[i]
            # 第一个标签较长，特殊处理
            if len(lbl) > 4:
                lbl = lbl[:2] + "\n" + lbl[2:4]
            self.cv.create_text(lx, ly, text=lbl, font=("Microsoft YaHei", 9),
                                fill=self.LABEL_COLOR, tags="label")

        # 绘制客队区域（先画，后画主队覆盖在上面）
        self._draw_polygon(away_values, angles, self.AWAY_COLOR, self.AWAY_FILL, "away")

        # 绘制主队区域
        self._draw_polygon(home_values, angles, self.HOME_COLOR, self.HOME_FILL, "home")

        # 绘制数值点
        self._draw_dots(home_values, angles, self.HOME_COLOR)
        self._draw_dots(away_values, angles, self.AWAY_COLOR)

        # 图例
        self._draw_legend(home_name, away_name)

    def _draw_polygon(self, values, angles, color, fill_color, tag):
        points = []
        for v, angle in zip(values, angles):
            r = self.radius * max(0, min(100, v)) / 100
            x = self.cx + r * math.cos(angle)
            y = self.cy - r * math.sin(angle)
            points.extend([x, y])
        if len(points) >= 6:
            self.cv.create_polygon(points, outline=color, fill=fill_color,
                                    width=2, stipple="", tags=tag)

    def _draw_dots(self, values, angles, color):
        for v, angle in zip(values, angles):
            r = self.radius * max(0, min(100, v)) / 100
            x = self.cx + r * math.cos(angle)
            y = self.cy - r * math.sin(angle)
            self.cv.create_oval(x - 3, y - 3, x + 3, y + 3,
                                fill=color, outline=color, tags="dot")

    def _draw_legend(self, home_name, away_name):
        y_base = self.h - 25
        self.cv.create_rectangle(10, y_base - 6, 22, y_base + 6,
                                  fill=self.HOME_COLOR, outline="")
        self.cv.create_text(28, y_base, text=home_name,
                            anchor="w", font=("Microsoft YaHei", 9),
                            fill=self.LABEL_COLOR)
        self.cv.create_rectangle(110, y_base - 6, 122, y_base + 6,
                                  fill=self.AWAY_COLOR, outline="")
        self.cv.create_text(128, y_base, text=away_name,
                            anchor="w", font=("Microsoft YaHei", 9),
                            fill=self.LABEL_COLOR)


class TeamRatingEngine:
    """根据球队统计数据计算六维评分 (0~100)"""

    @staticmethod
    def compute_ratings(
        team_name: str,
        world_rank: int = 50,
        squad_value_million: float = 100.0,
        goals_scored_avg: float = 1.3,
        goals_conceded_avg: float = 1.3,
        recent_wins: int = 2,
        recent_total: int = 5,
    ) -> Dict[str, float]:
        """
        计算六维评分

        Args:
            team_name: 球队名称
            world_rank: 世界排名 (1~200)
            squad_value_million: 阵容身价（百万欧元）
            goals_scored_avg: 场均进球
            goals_conceded_avg: 场均失球
            recent_wins: 近 5 场胜场数
            recent_total: 近 5 场总场数

        Returns:
            {label: score} 六维评分字典
        """
        # 1. 大赛经验 (排名越高分越高)
        exp_score = max(10, min(95, 95 - (world_rank - 1) * 0.42))

        # 2. 世界排名 (同大赛经验，但曲线更陡)
        rank_score = max(10, min(95, 100 - (world_rank ** 0.6) * 3))

        # 3. 阵容身价 (100M=50分, 300M=65分, 800M=87分, 1B=93分)
        value_score = max(10, min(95, 30 + (squad_value_million ** 0.5) * 2))

        # 4. 防守稳定 (失球少 = 高分)
        #    场均失球 0.5 → 90分, 1.0 → 70分, 1.5 → 50分, 2.5 → 20分
        defense_score = max(5, min(95, 105 - goals_conceded_avg * 35))

        # 5. 进攻火力 (进球多 = 高分)
        #    场均进球 0.5 → 20分, 1.5 → 55分, 2.5 → 85分
        attack_score = max(5, min(95, goals_scored_avg * 35))

        # 6. 近期状态 (胜率)
        win_rate = recent_wins / max(1, recent_total)
        form_score = max(5, min(95, win_rate * 95))

        return {
            '大赛经验': round(exp_score),
            '世界排名': round(rank_score),
            '阵容身价': round(value_score),
            '防守稳定': round(defense_score),
            '进攻火力': round(attack_score),
            '近期状态': round(form_score),
        }