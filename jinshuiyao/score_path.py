# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 比分路径推演 v3.0

基于双泊松模型生成半场→全场的比分概率矩阵，提取 top-N 最可能路径。

核心假设：
  - 半场预期进球 = 全场 λ × 0.45（历史统计）
  - 半场和全场比分独立（泊松分布）
  - 输出 3 条概率最高的"半场 → 全场"路径

使用方式：
  paths = generate_score_paths(lambda_home=1.2, lambda_away=0.8)
  for p in paths:
      print(p.half_score, "→", p.full_score, p.probability)
"""

from typing import List, Tuple
from dataclasses import dataclass
import math


# 半场进球占比（历史统计均值约 43%）
HALF_TIME_RATIO = 0.43

# 最大模拟比分
MAX_GOALS_FULL = 5
MAX_GOALS_HALF = 3


@dataclass
class ScorePath:
    """单条比分路径"""
    half_home: int
    half_away: int
    full_home: int
    full_away: int
    probability: float

    @property
    def half_score(self) -> str:
        return f"{self.half_home}-{self.half_away}"

    @property
    def full_score(self) -> str:
        return f"{self.full_home}-{self.full_away}"

    @property
    def result(self) -> str:
        if self.full_home > self.full_away:
            return "主胜"
        elif self.full_home == self.full_away:
            return "平局"
        return "客胜"

    @property
    def is_draw(self) -> bool:
        return self.full_home == self.full_away

    def __repr__(self) -> str:
        return (f"半场 {self.half_score} → 全场 {self.full_score} "
                f"({self.probability:.1%}) [{self.result}]")


def _poisson_pmf(k: int, lam: float) -> float:
    """泊松概率质量函数（避免 scipy 依赖）"""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def generate_score_paths(
    lambda_home: float,
    lambda_away: float,
    top_n: int = 3,
    half_ratio: float = HALF_TIME_RATIO,
) -> List[ScorePath]:
    """
    生成比分路径推演

    Args:
        lambda_home: 主队预期进球数
        lambda_away: 客队预期进球数
        top_n: 返回前 N 条最可能路径
        half_ratio: 半场进球占比（默认 0.43）

    Returns:
        ScorePath 列表，按概率降序
    """
    half_lambda_home = lambda_home * half_ratio
    half_lambda_away = lambda_away * half_ratio

    paths: List[ScorePath] = []

    for fh in range(MAX_GOALS_FULL + 1):
        for fa in range(MAX_GOALS_FULL + 1):
            prob_full = _poisson_pmf(fh, lambda_home) * _poisson_pmf(fa, lambda_away)
            if prob_full < 0.01:
                continue

            # 尝试可能的半场比分（半场不能超过全场）
            for hh in range(min(fh, MAX_GOALS_HALF) + 1):
                for ha in range(min(fa, MAX_GOALS_HALF) + 1):
                    prob_half = (_poisson_pmf(hh, half_lambda_home) *
                                 _poisson_pmf(ha, half_lambda_away))
                    joint_prob = prob_half * prob_full
                    if joint_prob < 0.005:
                        continue
                    paths.append(ScorePath(
                        half_home=hh, half_away=ha,
                        full_home=fh, full_away=fa,
                        probability=joint_prob,
                    ))

    paths.sort(key=lambda p: p.probability, reverse=True)
    return paths[:top_n]


def generate_path_report(
    lambda_home: float,
    lambda_away: float,
    home_name: str = "主队",
    away_name: str = "客队",
) -> str:
    """
    生成比分路径文字报告（用于 GUI 展示）

    Returns:
        多行字符串
    """
    paths = generate_score_paths(lambda_home, lambda_away, top_n=5)

    report = f"【比分路径推演】{home_name} vs {away_name}\n"
    report += f"  预期进球: {home_name} {lambda_home:.2f}  {away_name} {lambda_away:.2f}\n"
    report += "-" * 42 + "\n"

    for i, p in enumerate(paths, 1):
        bar = "█" * int(p.probability * 40) + "░" * (40 - int(p.probability * 40))
        report += (f"  路径{i}: 半场 {p.half_score} → 全场 {p.full_score} "
                   f"({p.probability:.1%}) [{p.result}]\n")
        report += f"         {bar}\n"
    return report


def compute_expected_goals(
    home_goals_avg: float,
    away_goals_avg: float,
    home_conceded_avg: float,
    away_conceded_avg: float,
    home_advantage: bool = True,
) -> Tuple[float, float]:
    """
    根据攻防数据计算预期进球数（简化版）

    公式：
      λ_home = home_goals_avg * (1 + home_advantage_bias) * away_conceded_avg / league_avg
      λ_away = away_goals_avg * home_conceded_avg / league_avg

    其中 league_avg 取中位数 ~1.3

    Returns:
        (lambda_home, lambda_away)
    """
    league_avg = 1.35  # 联赛场均进球中位数
    home_bias = 1.15 if home_advantage else 1.0

    lambda_home = home_goals_avg * home_bias * away_conceded_avg / league_avg
    lambda_away = away_goals_avg * home_conceded_avg / league_avg

    # 边界保护
    lambda_home = max(0.2, min(5.0, lambda_home))
    lambda_away = max(0.2, min(5.0, lambda_away))

    return round(lambda_home, 2), round(lambda_away, 2)