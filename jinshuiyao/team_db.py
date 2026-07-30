# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 球队数据库 v3.0

世界杯32强六维雷达预设数据 + 球队名称模糊匹配。
数据基于公开信息（FIFA排名、Transfermarkt身价、近期赛果）测算。

使用方式：
  db = TeamDatabase()
  ratings = db.get_ratings("巴西")  # → {'大赛经验': 92, '世界排名': 88, ...}
  name = db.resolve_name("brazil")  # → "巴西"
"""

from typing import Dict, List, Optional, Tuple

# ── 32强六维雷达预设数据 ──
#   格式: {球队名: [大赛经验, 世界排名, 阵容身价, 防守稳定, 进攻火力, 近期状态]}
#   所有值 0~100

PRESET_TEAMS: Dict[str, List[int]] = {
    # ── 南美洲 ──
    "巴西":     [92, 88, 98, 65, 78, 58],
    "阿根廷":   [95, 92, 96, 70, 90, 52],
    "乌拉圭":   [82, 80, 78, 85, 72, 68],
    "厄瓜多尔": [60, 72, 68, 85, 55, 65],
    "哥伦比亚": [70, 76, 74, 72, 68, 70],
    "巴拉圭":   [72, 62, 55, 78, 45, 55],
    "智利":     [68, 58, 52, 65, 58, 48],
    "秘鲁":     [65, 50, 42, 62, 48, 45],

    # ── 欧洲 ──
    "德国":     [95, 85, 96, 72, 82, 91],
    "荷兰":     [82, 80, 88, 78, 75, 86],
    "瑞士":     [78, 82, 72, 88, 68, 82],
    "瑞典":     [72, 68, 70, 75, 62, 60],
    "苏格兰":   [48, 60, 65, 70, 58, 62],
    "土耳其":   [68, 76, 82, 65, 72, 78],
    "法国":     [94, 95, 99, 82, 95, 58],
    "英格兰":   [88, 90, 97, 75, 88, 55],
    "西班牙":   [90, 88, 94, 78, 85, 50],
    "葡萄牙":   [86, 86, 92, 80, 82, 65],
    "比利时":   [85, 84, 90, 72, 78, 55],
    "意大利":   [92, 82, 88, 85, 72, 68],
    "克罗地亚": [84, 78, 76, 80, 68, 72],
    "丹麦":     [75, 76, 74, 82, 65, 70],
    "塞尔维亚": [70, 70, 78, 62, 75, 55],

    # ── 非洲 ──
    "摩洛哥":   [55, 78, 52, 90, 85, 95],
    "科特迪瓦": [65, 70, 74, 68, 70, 75],
    "突尼斯":   [50, 58, 55, 72, 58, 55],
    "塞内加尔": [62, 74, 68, 78, 65, 72],

    # ── 亚洲 ──
    "日本":     [62, 72, 68, 80, 60, 88],
    "卡塔尔":   [35, 45, 48, 62, 45, 28],
    "澳大利亚": [55, 62, 58, 60, 52, 50],
    "韩国":     [60, 68, 62, 65, 58, 62],
    "沙特阿拉伯":[48, 55, 42, 58, 45, 50],

    # ── 中北美 ──
    "海地":     [18, 25, 22, 55, 40, 45],
    "美国":     [55, 70, 72, 68, 60, 62],
    "哥斯达黎加":[50, 52, 38, 72, 42, 48],

    # ── 未分类/常见球队扩展 ──
    "俄罗斯":   [72, 50, 60, 70, 58, 55],
}

# ── 球队名称别名映射（英文/简写 → 中文全称）──
NAME_ALIASES: Dict[str, str] = {
    "brazil": "巴西", "brasil": "巴西",
    "argentina": "阿根廷",
    "uruguay": "乌拉圭",
    "germany": "德国", "deutschland": "德国",
    "netherlands": "荷兰", "holland": "荷兰",
    "switzerland": "瑞士", "suisse": "瑞士",
    "sweden": "瑞典", "sverige": "瑞典",
    "scotland": "苏格兰",
    "turkey": "土耳其", "turkiye": "土耳其",
    "france": "法国",
    "england": "英格兰",
    "spain": "西班牙", "espana": "西班牙",
    "portugal": "葡萄牙",
    "belgium": "比利时",
    "italy": "意大利", "italia": "意大利",
    "croatia": "克罗地亚", "hrvatska": "克罗地亚",
    "denmark": "丹麦",
    "serbia": "塞尔维亚",
    "morocco": "摩洛哥", "maroc": "摩洛哥",
    "cote d'ivoire": "科特迪瓦", "ivory coast": "科特迪瓦",
    "tunisia": "突尼斯",
    "senegal": "塞内加尔",
    "japan": "日本",
    "qatar": "卡塔尔",
    "australia": "澳大利亚",
    "south korea": "韩国", "korea republic": "韩国",
    "saudi arabia": "沙特阿拉伯", "ksa": "沙特阿拉伯",
    "haiti": "海地",
    "usa": "美国", "united states": "美国",
    "costa rica": "哥斯达黎加",
    "russia": "俄罗斯",
    "ecuador": "厄瓜多尔",
    "colombia": "哥伦比亚",
    "paraguay": "巴拉圭",
    "chile": "智利",
    "peru": "秘鲁",
}

# 六维标签（保持与 radar.py 一致）
RADAR_LABELS = ["大赛经验", "世界排名", "阵容身价", "防守稳定", "进攻火力", "近期状态"]


class TeamDatabase:
    """球队数据库 — 六维雷达预设 + 模糊匹配"""

    def __init__(self):
        self._teams = dict(PRESET_TEAMS)
        self._aliases = {k.lower().strip(): v for k, v in NAME_ALIASES.items()}

    @property
    def team_names(self) -> List[str]:
        """获取所有已录入球队名"""
        return sorted(self._teams.keys())

    def resolve_name(self, name: str) -> Optional[str]:
        """
        模糊匹配球队名称

        - 直接匹配 PRESET_TEAMS 中的中文名
        - 通过 NAME_ALIASES 中英文名映射
        - 子串模糊匹配（如 "巴西队" → "巴西"）
        """
        name = name.strip()
        # 1. 精确匹配
        if name in self._teams:
            return name
        # 2. 别名匹配
        alias_key = name.lower().strip()
        if alias_key in self._aliases:
            return self._aliases[alias_key]
        # 3. 子串模糊匹配
        for cn_name in self._teams:
            if cn_name in name or name in cn_name:
                return cn_name
        return None

    def get_ratings(self, name: str) -> Optional[Dict[str, int]]:
        """
        获取球队六维评分

        Args:
            name: 球队名称（支持中英文/简写）

        Returns:
            {label: score} 或 None（未找到）
        """
        resolved = self.resolve_name(name)
        if not resolved:
            return None
        scores = self._teams[resolved]
        return dict(zip(RADAR_LABELS, scores))

    def get_radar_values(self, name: str) -> Optional[List[int]]:
        """获取纯数值列表（用于直接画图）"""
        resolved = self.resolve_name(name)
        if not resolved:
            return None
        return list(self._teams[resolved])

    def get_info(self, name: str) -> Optional[Dict]:
        """获取球队完整信息"""
        resolved = self.resolve_name(name)
        if not resolved:
            return None
        scores = self._teams[resolved]
        avg = sum(scores) / len(scores)
        return {
            'name': resolved,
            'ratings': dict(zip(RADAR_LABELS, scores)),
            'average': round(avg, 1),
            'strength': '强' if avg >= 70 else ('中' if avg >= 50 else '弱'),
        }

    def add_team(self, name: str, ratings: List[int]):
        """手动添加/覆盖球队数据"""
        if len(ratings) != 6:
            raise ValueError("需要6个维度评分")
        self._teams[name.strip()] = [max(0, min(100, v)) for v in ratings]

    def compare(self, home: str, away: str) -> Optional[Tuple]:
        """两队对比

        Returns:
            (home_vals, away_vals, home_name, away_name) 或 None
        """
        hv = self.get_radar_values(home)
        av = self.get_radar_values(away)
        if hv is None or av is None:
            return None
        hn = self.resolve_name(home)
        an = self.resolve_name(away)
        return hv, av, hn, an