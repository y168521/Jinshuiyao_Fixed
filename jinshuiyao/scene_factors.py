# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 场景因素调节引擎 v3.0

支持两层因素调节：
  1. 快速模式（GUI滑块）— 7参数：主场优势、阵容完整度、天气、赛事重要性、德比、疲劳、状态
  2. 精确模式（v3.0 10因子）— F01~F10：核心缺阵量化、天气、裁判、市场波动等

10因子体系（对齐抖音AI模型）：
  F01 核心前锋缺阵 → 主胜-8%, 平局+3%, 客胜+5%
  F02 核心中场缺阵 → 主胜-6%, 平局+5%, 客胜+1%
  F03 核心后卫缺阵 → 主胜-4%, 平局-2%, 客胜+6%
  F04 暴雨/场地积水 → 大球-12%, 小球+12%
  F05 高温(>32°C)   → 下半场进球-15%, 平局+4%
  F06 裁判尺度宽松   → 大球+6%, 红牌概率+3%
  F07 东道主/主场    → 主胜+5%, 平局-2%
  F08 体能劣势       → 主胜-4%, 下半场失球+10%
  F09 主胜赔率上升   → 主胜置信度-10%, 平局+5%
  F10 平局赔率下降   → 平局概率+8%

使用方式：
  factors = SceneFactors()
  factors.set_home_advantage(0.65)
  factors.set_weather("rain")
  adjusted = factors.adjust_probabilities(base_probs)

  # 精确因子模式：
  result = factors.apply_precision_factors(base_probs, [('F01', 'home'), ('F07', 'home')])
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class SceneFactors:
    """场景因素配置"""

    # === 场内因素 ===
    home_advantage: float = 0.55
    squad_integrity_home: float = 1.0
    squad_integrity_away: float = 1.0

    # === 场外因素 ===
    weather: str = "normal"
    travel_fatigue_away: float = 0.0

    # === 比赛形式 ===
    match_importance: str = "league"
    is_derby: bool = False
    is_must_win: bool = False

    # === 近期状态 ===
    form_boost_home: float = 0.0
    form_boost_away: float = 0.0

    # === 天气影响映射 ===
    WEATHER_IMPACT: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "normal": {"attack_penalty": 0.00, "defense_boost": 0.00},
        "rain":   {"attack_penalty": 0.04, "defense_boost": 0.02},
        "snow":   {"attack_penalty": 0.08, "defense_boost": 0.04},
        "hot":    {"attack_penalty": 0.03, "defense_boost": 0.01},
        "windy":  {"attack_penalty": 0.05, "defense_boost": 0.03},
    })

    # === 赛事重要性对平局概率的影响 ===
    IMPORTANCE_DRAW_BIAS: Dict[str, float] = field(default_factory=lambda: {
        "league":       0.00,
        "cup":          0.02,
        "cup_final":    0.05,
        "derby":        0.01,
        "friendly":    -0.03,
    })

    # ═══════════════════════════════════════════════════
    # v3.0 精确10因子体系
    # ═══════════════════════════════════════════════════
    # 因子注册表：{factor_id: {desc, home_delta, draw_delta, away_delta, condition}}
    FACTOR_REGISTRY: Dict[str, Dict] = field(default_factory=lambda: {
        # ── 核心球员缺阵 ──
        'F01': {
            'category': '核心缺阵',
            'desc': '核心前锋缺阵（贡献≥30%进球）',
            'impact_home_side': {'win': -0.08, 'draw': +0.03, 'lose': +0.05},
            'impact_away_side': {'win': +0.05, 'draw': +0.03, 'lose': -0.08},
        },
        'F02': {
            'category': '核心缺阵',
            'desc': '核心中场缺阵（场均关键传球≥2）',
            'impact_home_side': {'win': -0.06, 'draw': +0.05, 'lose': +0.01},
            'impact_away_side': {'win': +0.01, 'draw': +0.05, 'lose': -0.06},
        },
        'F03': {
            'category': '核心缺阵',
            'desc': '核心后卫缺阵（防守核心）',
            'impact_home_side': {'win': -0.04, 'draw': -0.02, 'lose': +0.06},
            'impact_away_side': {'win': +0.06, 'draw': -0.02, 'lose': -0.04},
        },
        # ── 天气 ──
        'F04': {
            'category': '天气',
            'desc': '暴雨/场地积水 → 大球概率-12%，小球+12%',
            'impact_home_side': {'win': -0.02, 'draw': +0.04, 'lose': -0.02},
            'impact_away_side': {'win': -0.02, 'draw': +0.04, 'lose': -0.02},
        },
        'F05': {
            'category': '天气',
            'desc': '高温(>32°C) → 下半场进球-15%，平局+4%',
            'impact_home_side': {'win': -0.02, 'draw': +0.04, 'lose': -0.02},
            'impact_away_side': {'win': -0.01, 'draw': +0.04, 'lose': -0.03},
        },
        # ── 裁判 ──
        'F06': {
            'category': '裁判',
            'desc': '裁判尺度宽松（场均出牌<3.5）→ 大球+6%',
            'impact_home_side': {'win': +0.01, 'draw': -0.02, 'lose': +0.01},
            'impact_away_side': {'win': +0.01, 'draw': -0.02, 'lose': +0.01},
        },
        # ── 主场 ──
        'F07': {
            'category': '主场',
            'desc': '东道主/真正主场 → 主胜+5%，平局-2%',
            'impact_home_side': {'win': +0.05, 'draw': -0.02, 'lose': -0.03},
            'impact_away_side': {'win': -0.03, 'draw': -0.02, 'lose': +0.05},
        },
        # ── 体能 ──
        'F08': {
            'category': '体能',
            'desc': '比对手少休息≥2天 → 胜率-4%，下半场失球+10%',
            'impact_home_side': {'win': -0.04, 'draw': +0.01, 'lose': +0.03},
            'impact_away_side': {'win': +0.03, 'draw': +0.01, 'lose': -0.04},
        },
        # ── 市场波动 ──
        'F09': {
            'category': '市场',
            'desc': '主胜赔率上升≥0.15 → 主胜置信度-10%，平局+5%',
            'impact_home_side': {'win': -0.06, 'draw': +0.04, 'lose': +0.02},
            'impact_away_side': {'win': +0.02, 'draw': +0.04, 'lose': -0.06},
        },
        'F10': {
            'category': '市场',
            'desc': '平局赔率下降≥0.20 → 平局概率+8%',
            'impact_home_side': {'win': -0.04, 'draw': +0.08, 'lose': -0.04},
            'impact_away_side': {'win': -0.04, 'draw': +0.08, 'lose': -0.04},
        },
    })

    # ═══════════════════════════════════════════════════
    # 快速模式（GUI友好）
    # ═══════════════════════════════════════════════════
    def set_home_advantage(self, value: float):
        self.home_advantage = max(0.5, min(0.7, value))

    def set_weather(self, condition: str):
        if condition in self.WEATHER_IMPACT:
            self.weather = condition

    def set_importance(self, level: str):
        if level in self.IMPORTANCE_DRAW_BIAS:
            self.match_importance = level

    def adjust_probabilities(
        self,
        base_probs: Dict[str, float],
    ) -> Dict[str, float]:
        """快速模式：根据场景因素调整基础概率

        Args:
            base_probs: {'win': 0.39, 'draw': 0.28, 'lose': 0.33}

        Returns:
            调整后归一化概率
        """
        p_win = base_probs.get('win', 0.33)
        p_draw = base_probs.get('draw', 0.33)
        p_lose = base_probs.get('lose', 0.33)

        # 1. 主场优势
        home_bias = (self.home_advantage - 0.5) * 2
        p_win += home_bias * 0.15
        p_lose -= home_bias * 0.15

        # 2. 阵容完整度
        p_win *= self.squad_integrity_home
        p_lose *= self.squad_integrity_away

        # 3. 天气 → 攻击力下降，平局上升
        weather = self.WEATHER_IMPACT.get(self.weather,
                                          {"attack_penalty": 0, "defense_boost": 0})
        attack_loss = weather["attack_penalty"]
        p_draw += attack_loss
        p_win -= attack_loss * 0.5
        p_lose -= attack_loss * 0.5

        # 4. 客队旅途疲劳
        p_win += self.travel_fatigue_away * 0.08
        p_lose -= self.travel_fatigue_away * 0.08

        # 5. 赛事重要性 → 平局偏差
        draw_bias = self.IMPORTANCE_DRAW_BIAS.get(self.match_importance, 0.0)
        p_draw += draw_bias
        total = p_win + p_lose
        if total > 0:
            p_win -= draw_bias * (p_win / total)
            p_lose -= draw_bias * (p_lose / total)

        # 6. 状态加成
        p_win += self.form_boost_home * 0.1
        p_lose += self.form_boost_away * 0.1

        # 7. 德比战
        if self.is_derby:
            p_draw += 0.02
            p_win -= 0.01
            p_lose -= 0.01

        # 归一化 + 边界裁剪
        p_win = max(0.05, min(0.85, p_win))
        p_draw = max(0.05, min(0.60, p_draw))
        p_lose = max(0.05, min(0.85, p_lose))
        total = p_win + p_draw + p_lose

        return {
            'win': round(p_win / total, 4),
            'draw': round(p_draw / total, 4),
            'lose': round(p_lose / total, 4),
        }

    # ═══════════════════════════════════════════════════
    # 精确模式（v3.0 10因子）
    # ═══════════════════════════════════════════════════
    def apply_precision_factors(
        self,
        base_probs: Dict[str, float],
        active_factors: List[Tuple[str, str]],
    ) -> Dict[str, float]:
        """
        精确因子模式：基于 F01-F10 因子体系调整概率

        Args:
            base_probs: {'win': 0.39, 'draw': 0.28, 'lose': 0.33}
            active_factors: 激活的因子列表
                每个元素为 (factor_id, side)
                side 可选: 'home'（主队受影响）, 'away'（客队受影响）, 'neutral'（中性）

        Returns:
            调整后归一化概率

        Example:
            # 摩洛哥核心后卫缺阵 + 巴西主场
            result = sf.apply_precision_factors(
                {'win': 0.55, 'draw': 0.25, 'lose': 0.20},
                [('F03', 'away'), ('F07', 'home')]
            )
        """
        p_win = base_probs.get('win', 0.33)
        p_draw = base_probs.get('draw', 0.33)
        p_lose = base_probs.get('lose', 0.33)

        for fid, side in active_factors:
            if fid not in self.FACTOR_REGISTRY:
                continue
            fact = self.FACTOR_REGISTRY[fid]

            if side == 'home':
                delta = fact['impact_home_side']
            elif side == 'away':
                delta = fact['impact_away_side']
            else:
                # neutral: 取平均值
                hi = fact['impact_home_side']
                ai = fact['impact_away_side']
                delta = {k: (hi[k] + ai[k]) / 2 for k in hi}

            p_win += delta.get('win', 0)
            p_draw += delta.get('draw', 0)
            p_lose += delta.get('lose', 0)

        # 边界裁剪 + 归一化
        p_win = max(0.03, min(0.90, p_win))
        p_draw = max(0.03, min(0.65, p_draw))
        p_lose = max(0.03, min(0.90, p_lose))
        total = p_win + p_draw + p_lose

        return {
            'win': round(p_win / total, 4),
            'draw': round(p_draw / total, 4),
            'lose': round(p_lose / total, 4),
        }

    def get_precision_factors_catalog(self) -> Dict[str, Dict]:
        """获取完整10因子目录"""
        return dict(self.FACTOR_REGISTRY)

    def get_precision_factors_by_category(self) -> Dict[str, List[str]]:
        """按类别获取因子分组"""
        cats: Dict[str, List[str]] = {}
        for fid, info in self.FACTOR_REGISTRY.items():
            cat = info['category']
            cats.setdefault(cat, []).append(fid)
        return cats

    def get_factor_desc(self, fid: str) -> Optional[str]:
        """获取单个因子描述"""
        if fid in self.FACTOR_REGISTRY:
            return self.FACTOR_REGISTRY[fid]['desc']
        return None

    # ═══════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════
    def get_factors_summary(self) -> Dict[str, str]:
        """获取因素摘要（用于 GUI 显示）"""
        weather_cn = {"normal": "正常", "rain": "雨天", "snow": "雪天",
                       "hot": "高温", "windy": "大风"}.get(self.weather, self.weather)
        importance_cn = {"league": "联赛", "cup": "杯赛",
                          "cup_final": "决赛", "derby": "德比",
                          "friendly": "友谊赛"}.get(self.match_importance, self.match_importance)
        return {
            '主场优势': f"{self.home_advantage:.0%}",
            '天气': weather_cn,
            '赛事': importance_cn,
            '德比': "是" if self.is_derby else "否",
            '必须赢': "是" if self.is_must_win else "否",
            '主阵容': f"{self.squad_integrity_home:.0%}",
            '客阵容': f"{self.squad_integrity_away:.0%}",
            '客疲劳': f"{self.travel_fatigue_away:.0%}",
        }

    @staticmethod
    def list_all_precision_factors() -> List[Tuple[str, str, str]]:
        """列出所有10个精确因子（ID, 类别, 描述）"""
        # 直接构建（dataclass field 是实例属性，不能从类访问）
        registry = {
            'F01': {'category': '核心缺阵', 'desc': '核心前锋缺阵（贡献≥30%进球）'},
            'F02': {'category': '核心缺阵', 'desc': '核心中场缺阵（场均关键传球≥2）'},
            'F03': {'category': '核心缺阵', 'desc': '核心后卫缺阵（防守核心）'},
            'F04': {'category': '天气', 'desc': '暴雨/场地积水 → 大球概率-12%，小球+12%'},
            'F05': {'category': '天气', 'desc': '高温(>32°C) → 下半场进球-15%，平局+4%'},
            'F06': {'category': '裁判', 'desc': '裁判尺度宽松（场均出牌<3.5）→ 大球+6%'},
            'F07': {'category': '主场', 'desc': '东道主/真正主场 → 主胜+5%，平局-2%'},
            'F08': {'category': '体能', 'desc': '比对手少休息≥2天 → 胜率-4%，下半场失球+10%'},
            'F09': {'category': '市场', 'desc': '主胜赔率上升≥0.15 → 主胜置信度-10%，平局+5%'},
            'F10': {'category': '市场', 'desc': '平局赔率下降≥0.20 → 平局概率+8%'},
        }
        return [(fid, registry[fid]['category'], registry[fid]['desc'])
                for fid in sorted(registry.keys())]