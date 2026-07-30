# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 多元玩法预测引擎 v3.0

覆盖竞彩核心玩法：
  1. 胜平负 (1x2)          — 基础方向
  2. 让球胜平负 (Handicap) — 含盘口分析
  3. 总进球数 (Total Goals) — 泊松分布
  4. 半全场 (HT/FT)         — 基于比分路径
  5. 比分 (Correct Score)   — 精确比分概率

与 score_path.py 和 decision_engine.py 协同工作。

使用方式：
  engine = MultiPlayEngine()
  result = engine.analyze(lambda_home=1.2, lambda_away=0.8, odds={...})
  # result.handicap_recommendation, result.total_goals, etc.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import math


# ═══════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class HandicapAnalysis:
    """让球胜平负分析"""
    handicap: float                     # 让球数（如 -1, -2, +0.5）
    win_prob: float                     # 让球方胜概率
    draw_prob: float                    # 让球方平概率
    lose_prob: float                    # 让球方负概率
    recommendation: str                 # 推荐方向
    confidence: str                     # 置信度 (高/中/低)

@dataclass
class TotalGoalsAnalysis:
    """总进球数分析"""
    most_likely: int                    # 最可能总进球
    over_under_25: Tuple[float, float]  # (大2.5球概率, 小2.5球概率)
    distribution: Dict[int, float]      # {进球数: 概率}

@dataclass
class HalfFullAnalysis:
    """半全场分析"""
    top_combos: List[Tuple[str, str, float]]  # [(半场结果, 全场结果, 概率)]
    recommendation: str

@dataclass
class ScoreAnalysis:
    """比分分析"""
    top_scores: List[Tuple[int, int, float]]  # [(主进球, 客进球, 概率)]
    most_likely: Tuple[int, int]

@dataclass
class MultiPlayResult:
    """多元玩法综合结果"""
    home_name: str = ""
    away_name: str = ""
    lambda_home: float = 0.0
    lambda_away: float = 0.0

    # 基础概率
    win_prob: float = 0.0
    draw_prob: float = 0.0
    lose_prob: float = 0.0

    # 各玩法
    handicap: Optional[HandicapAnalysis] = None
    total_goals: Optional[TotalGoalsAnalysis] = None
    half_full: Optional[HalfFullAnalysis] = None
    score: Optional[ScoreAnalysis] = None

    # 推荐汇总
    recommendations: List[Dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 引擎核心
# ═══════════════════════════════════════════════════════════════

def _poisson_pmf(k: int, lam: float) -> float:
    """泊松 PMF"""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _poisson_cdf(k: int, lam: float) -> float:
    """泊松 CDF (P(X <= k))"""
    return sum(_poisson_pmf(i, lam) for i in range(k + 1))


class MultiPlayEngine:
    """多元玩法预测引擎"""

    def __init__(self):
        pass

    def compute_base_probs(self, lambda_home: float, lambda_away: float) -> Dict[str, float]:
        """
        从预期进球计算基础胜平负概率（泊松比分矩阵汇总）

        Returns:
            {'win': p, 'draw': p, 'lose': p}
        """
        wins = draws = loses = 0.0
        for h in range(10):
            for a in range(10):
                prob = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
                if h > a:
                    wins += prob
                elif h == a:
                    draws += prob
                else:
                    loses += prob
        total = wins + draws + loses
        if total == 0:
            return {'win': 1/3, 'draw': 1/3, 'lose': 1/3}
        return {
            'win': round(wins / total, 4),
            'draw': round(draws / total, 4),
            'lose': round(loses / total, 4),
        }

    # ── 1. 胜平负 ──
    def predict_1x2(self, probs: Dict[str, float]) -> Tuple[str, float]:
        """预测胜平负方向"""
        best = max(probs, key=probs.get)
        mapping = {'win': '主胜', 'draw': '平局', 'lose': '客胜'}
        return mapping[best], probs[best]

    # ── 2. 让球胜平负 ──
    def predict_handicap(
        self,
        lambda_home: float,
        lambda_away: float,
        handicap: float = -1.0,
    ) -> HandicapAnalysis:
        """
        让球 < 0: 主队让球（如 -1 表示主队让1球）
        让球 > 0: 客队让球

        让球后结果：
          比较 (h + handicap) vs a
          即：主队得分 = h + handicap
        """
        wins = draws = loses = 0.0
        for h in range(10):
            for a in range(10):
                prob = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
                effective_home = h + handicap
                if effective_home > a:
                    wins += prob
                elif effective_home == a:
                    draws += prob
                else:
                    loses += prob
        total = wins + draws + loses
        if total == 0:
            probs = {'win': 1/3, 'draw': 1/3, 'lose': 1/3}
        else:
            probs = {
                'win': round(wins / total, 4),
                'draw': round(draws / total, 4),
                'lose': round(loses / total, 4),
            }

        # 推荐
        best_key = max(probs, key=probs.get)
        mapping = {'win': '让胜', 'draw': '让平', 'lose': '让负'}

        return HandicapAnalysis(
            handicap=handicap,
            win_prob=probs['win'],
            draw_prob=probs['draw'],
            lose_prob=probs['lose'],
            recommendation=mapping[best_key],
            confidence='高' if probs[best_key] > 0.45 else ('中' if probs[best_key] > 0.35 else '低'),
        )

    # ── 3. 总进球数 ──
    def predict_total_goals(
        self,
        lambda_home: float,
        lambda_away: float,
    ) -> TotalGoalsAnalysis:
        """
        预测总进球数

        使用双泊松卷积：总进球 λ = λ_home + λ_away
        """
        lambda_total = lambda_home + lambda_away
        dist = {}
        for g in range(8):
            dist[g] = _poisson_pmf(g, lambda_total)

        # 最可能
        most_likely = max(dist, key=dist.get)

        # 大小球 2.5
        over_25 = 1 - _poisson_cdf(2, lambda_total)
        under_25 = _poisson_cdf(2, lambda_total)

        return TotalGoalsAnalysis(
            most_likely=most_likely,
            over_under_25=(round(over_25, 4), round(under_25, 4)),
            distribution={k: round(v, 4) for k, v in dist.items()},
        )

    # ── 4. 半全场 ──
    def predict_half_full(
        self,
        lambda_home: float,
        lambda_away: float,
        half_ratio: float = 0.43,
    ) -> HalfFullAnalysis:
        """
        预测半全场

        基于半场预期进球独立计算，组合概率
        """
        half_lambda_home = lambda_home * half_ratio
        half_lambda_away = lambda_away * half_ratio

        combos = []
        half_results = ['胜', '平', '负']
        full_results = ['胜', '平', '负']

        for hh in range(5):
            for ha in range(5):
                half_prob = _poisson_pmf(hh, half_lambda_home) * _poisson_pmf(ha, half_lambda_away)
                if half_prob < 0.01:
                    continue

                half_result = '胜' if hh > ha else ('平' if hh == ha else '负')

                for fh in range(hh, 8):
                    for fa in range(ha, 8):
                        full_prob = _poisson_pmf(fh, lambda_home) * _poisson_pmf(fa, lambda_away)
                        if full_prob < 0.005:
                            continue
                        full_result = '胜' if fh > fa else ('平' if fh == fa else '负')

                        joint = half_prob * full_prob
                        combo_name = f"{half_result}{full_result}"
                        combos.append((combo_name, joint))

        # 聚合同名组合
        aggregated: Dict[str, float] = {}
        for name, prob in combos:
            aggregated[name] = aggregated.get(name, 0) + prob

        sorted_combos = sorted(aggregated.items(), key=lambda x: x[1], reverse=True)
        top = [(c[0][0], c[0][1], c[1]) for c in sorted_combos[:5]]

        best = sorted_combos[0][0] if sorted_combos else '平平'

        return HalfFullAnalysis(
            top_combos=top,
            recommendation=f"{best[0]}/{best[1]} ({aggregated[best]:.1%})",
        )

    # ── 5. 精确比分 ──
    def predict_score(
        self,
        lambda_home: float,
        lambda_away: float,
        top_n: int = 5,
    ) -> ScoreAnalysis:
        """预测精确比分"""
        scores = []
        for h in range(6):
            for a in range(6):
                prob = _poisson_pmf(h, lambda_home) * _poisson_pmf(a, lambda_away)
                scores.append((h, a, prob))

        scores.sort(key=lambda x: x[2], reverse=True)
        top = scores[:top_n]
        most = top[0] if top else (1, 0)

        return ScoreAnalysis(
            top_scores=[(s[0], s[1], round(s[2], 4)) for s in top],
            most_likely=(most[0], most[1]),
        )

    # ── 综合分析 ──
    def analyze(
        self,
        lambda_home: float,
        lambda_away: float,
        home_name: str = "主队",
        away_name: str = "客队",
        odds: Optional[Dict[str, float]] = None,
    ) -> MultiPlayResult:
        """
        完整多元玩法分析

        Args:
            lambda_home: 主队预期进球
            lambda_away: 客队预期进球
            home_name: 主队名
            away_name: 客队名
            odds: 赔率数据 {'home_win': 1.75, 'draw': 3.30, 'lose': 3.92}

        Returns:
            MultiPlayResult
        """
        result = MultiPlayResult(
            home_name=home_name,
            away_name=away_name,
            lambda_home=lambda_home,
            lambda_away=lambda_away,
        )

        # 基础概率
        probs = self.compute_base_probs(lambda_home, lambda_away)
        result.win_prob = probs['win']
        result.draw_prob = probs['draw']
        result.lose_prob = probs['lose']

        # 2. 让球分析（默认-1盘）
        result.handicap = self.predict_handicap(lambda_home, lambda_away, handicap=-1.0)

        # 3. 总进球
        result.total_goals = self.predict_total_goals(lambda_home, lambda_away)

        # 4. 半全场
        result.half_full = self.predict_half_full(lambda_home, lambda_away)

        # 5. 比分
        result.score = self.predict_score(lambda_home, lambda_away)

        # 汇总推荐
        recs = []

        # 胜平负方向
        best_1x2, p_1x2 = self.predict_1x2(probs)
        recs.append({
            'play': '胜平负',
            'recommendation': best_1x2,
            'probability': f"{p_1x2:.1%}",
        })

        # 让球方向
        hc = result.handicap
        recs.append({
            'play': '让球胜平负(-1)',
            'recommendation': hc.recommendation,
            'detail': f"让胜{hc.win_prob:.1%}/让平{hc.draw_prob:.1%}/让负{hc.lose_prob:.1%}",
        })

        # 总进球
        tg = result.total_goals
        recs.append({
            'play': '总进球数',
            'recommendation': f"看好{tg.most_likely}球",
            'detail': f"大2.5 {tg.over_under_25[0]:.1%} | 小2.5 {tg.over_under_25[1]:.1%}",
        })

        # 半全场
        hf = result.half_full
        recs.append({
            'play': '半全场',
            'recommendation': hf.recommendation,
        })

        # 比分
        sc = result.score
        recs.append({
            'play': '比分',
            'recommendation': f"{sc.most_likely[0]}-{sc.most_likely[1]}",
            'detail': f"概率 {sc.top_scores[0][2]:.1%}" if sc.top_scores else "",
        })

        result.recommendations = recs
        return result

    def generate_report(self, result: MultiPlayResult) -> str:
        """生成多玩法综合报告"""
        r = result
        lines = [
            f"╔══════════════════════════════════════════╗",
            f"║  多玩法综合预测: {r.home_name} vs {r.away_name}",
            f"╠══════════════════════════════════════════╣",
            f"║ 预期进球: {r.home_name} {r.lambda_home:.2f}  {r.away_name} {r.lambda_away:.2f}",
            f"╠══════════════════════════════════════════╣",
            f"║ 胜平负: 主{r.win_prob:.1%} 平{r.draw_prob:.1%} 客{r.lose_prob:.1%}",
        ]

        if r.handicap:
            hc = r.handicap
            lines.extend([
                f"╠══ 让球胜平负(-1) ═══════════════════════╣",
                f"║ 让胜: {hc.win_prob:.1%} | 让平: {hc.draw_prob:.1%} | 让负: {hc.lose_prob:.1%}",
                f"║ 推荐: {hc.recommendation} ({hc.confidence}置信度)",
            ])

        if r.total_goals:
            tg = r.total_goals
            lines.extend([
                f"╠══ 总进球数 ═════════════════════════════╣",
                f"║ 最可能: {tg.most_likely}球",
                f"║ 大2.5: {tg.over_under_25[0]:.1%} | 小2.5: {tg.over_under_25[1]:.1%}",
            ])

        if r.half_full:
            hf = r.half_full
            lines.extend([
                f"╠══ 半全场 ═══════════════════════════════╣",
                f"║ 推荐: {hf.recommendation}",
            ])
            for combo in hf.top_combos[:3]:
                lines.append(f"║  {combo[0]}/{combo[1]}: {combo[2]:.1%}")

        if r.score:
            sc = r.score
            lines.extend([
                f"╠══ 精确比分 ═════════════════════════════╣",
            ])
            for h, a, prob in sc.top_scores:
                lines.append(f"║  {h}-{a}: {prob:.1%}")

        lines.append(f"╚══════════════════════════════════════════╝")
        return "\n".join(lines)