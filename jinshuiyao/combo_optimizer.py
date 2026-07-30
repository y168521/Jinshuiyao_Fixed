# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 2串1自动优化组合推荐 v3.0

功能：
  1. 从多场比赛中选择最优2串1组合
  2. 支持多种玩法组合：胜平负+让球+总进球+半全场+比分
  3. EV驱动 + 风险约束
  4. 输出稳健/均衡/进取三种组合

使用方式：
  optimizer = ComboOptimizer()
  combos = optimizer.optimize(matches, bankroll=10000)
  for c in combos:
      print(c.leg1, c.leg2, c.ev, c.odds)
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import math


@dataclass
class ComboLeg:
    """串关单场"""
    match_id: str
    home: str
    away: str
    play_type: str          # 胜平负 / 让球胜平负 / 总进球 / 半全场 / 比分
    selection: str           # 具体选项
    odds: float
    probability: float       # 模型预测概率
    ev: float                # 单场 EV


@dataclass
class ComboTicket:
    """2串1推荐"""
    name: str                # 组合名（稳健/均衡/进取）
    leg1: ComboLeg
    leg2: ComboLeg
    combined_odds: float
    combined_prob: float
    combined_ev: float       # EV1 × EV2 归一化
    suggested_stake: float
    tier: str                # high/medium/low
    description: str         # 组合解释


class ComboOptimizer:
    """2串1自动优化器"""

    def __init__(self, max_stake_ratio: float = 0.015, kelly_mult: float = 0.25):
        self.max_stake_ratio = max_stake_ratio
        self.kelly_mult = kelly_mult

    def generate_candidates(
        self,
        matches: List[Dict],
    ) -> List[ComboLeg]:
        """
        从比赛列表生成所有可选的单场投注

        每场比赛生成多个可选方向：
          - 胜平负 3 个方向 (win/draw/lose)
          - 大小球 2 个方向 (over/under)

        Args:
            matches: [{home, away, odds_win, odds_draw, odds_lose,
                       model_prob_win, model_prob_draw, model_prob_lose,
                       total_goals_over_25, total_goals_under_25}, ...]
        """
        legs = []

        for m in matches:
            mid = m.get('match_id', '')
            home = m.get('home', '主队')
            away = m.get('away', '客队')

            # ── 胜平负 ──
            for key, label, odds_key in [
                ('win', '主胜', 'odds_win'),
                ('draw', '平局', 'odds_draw'),
                ('lose', '客胜', 'odds_lose'),
            ]:
                odds = m.get(odds_key, 0) or 0
                prob = m.get(f'model_prob_{key}', 0) or 0
                if odds <= 1.0 or prob <= 0:
                    continue
                ev = prob * (odds - 1) - (1 - prob)
                if ev <= 0:
                    continue
                legs.append(ComboLeg(
                    match_id=mid, home=home, away=away,
                    play_type='胜平负', selection=label,
                    odds=odds, probability=prob, ev=ev,
                ))

            # ── 大小球（如果有数据）──
            over_prob = m.get('total_goals_over_25', 0) or 0
            under_prob = m.get('total_goals_under_25', 0) or 0
            over_odds = m.get('odds_over25', 0) or 0
            under_odds = m.get('odds_under25', 0) or 0

            if over_prob > 0 and over_odds > 1.0:
                ev = over_prob * (over_odds - 1) - (1 - over_prob)
                if ev > 0:
                    legs.append(ComboLeg(
                        match_id=mid, home=home, away=away,
                        play_type='总进球', selection='大2.5球',
                        odds=over_odds, probability=over_prob, ev=ev,
                    ))

            if under_prob > 0 and under_odds > 1.0:
                ev = under_prob * (under_odds - 1) - (1 - under_prob)
                if ev > 0:
                    legs.append(ComboLeg(
                        match_id=mid, home=home, away=away,
                        play_type='总进球', selection='小2.5球',
                        odds=under_odds, probability=under_prob, ev=ev,
                    ))

        return legs

    def optimize(
        self,
        matches: List[Dict],
        bankroll: float = 10000.0,
        max_combos: int = 6,
    ) -> List[ComboTicket]:
        """
        优化 2 串 1 组合

        算法：
        1. 生成所有单场投注 legs
        2. 两两组合（不同比赛），计算组合 EV 和赔率
        3. 按 EV 排序，去重，取 top-N
        4. 分级：稳健/均衡/进取

        Args:
            matches: 比赛列表（多场）
            bankroll: 当前资金
            max_combos: 最多返回组合数

        Returns:
            ComboTicket 列表
        """
        legs = self.generate_candidates(matches)
        if len(legs) < 2:
            return []

        # 两两组合
        combos: List[Tuple] = []
        for i, l1 in enumerate(legs):
            for j, l2 in enumerate(legs):
                if i >= j:
                    continue
                # 必须不同比赛
                if l1.match_id == l2.match_id:
                    continue
                # 组合赔率
                combined_odds = l1.odds * l2.odds
                # 组合概率（独立假设）
                combined_prob = l1.probability * l2.probability
                # 组合 EV = 组合赔率 * 组合概率 - 1
                combined_ev = (combined_odds * combined_prob) - 1

                if combined_ev <= 0:
                    continue

                combos.append((combined_ev, combined_odds, combined_prob, l1, l2))

        if not combos:
            return []

        # 按 EV 排序
        combos.sort(key=lambda x: x[0], reverse=True)

        # 去重（同一个 match_id 对只保留最优）
        seen_pairs = set()
        tickets = []

        for ev, odds, prob, l1, l2 in combos:
            pair_key = tuple(sorted([l1.match_id, l2.match_id]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            # 分级
            if ev > 0.08:
                tier = "high"
                name_base = "进取"
            elif ev > 0.04:
                tier = "medium"
                name_base = "均衡"
            else:
                tier = "low"
                name_base = "稳健"

            name = f"{name_base}{len(tickets)+1}"

            # 凯利仓位
            b = odds - 1
            full_kelly = (b * prob - (1 - prob)) / b if b > 0 else 0
            half_kelly = full_kelly * self.kelly_mult
            stake = min(max(0, half_kelly * bankroll), bankroll * self.max_stake_ratio)

            tickets.append(ComboTicket(
                name=name,
                leg1=l1, leg2=l2,
                combined_odds=round(odds, 2),
                combined_prob=round(prob, 4),
                combined_ev=round(ev, 4),
                suggested_stake=round(stake, 2),
                tier=tier,
                description=(
                    f"{l1.home}vs{l1.away}({l1.play_type}:{l1.selection}@{l1.odds}) × "
                    f"{l2.home}vs{l2.away}({l2.play_type}:{l2.selection}@{l2.odds})"
                ),
            ))

            if len(tickets) >= max_combos:
                break

        return tickets

    def format_tickets(self, tickets: List[ComboTicket]) -> str:
        """格式化2串1推荐为文本"""
        if not tickets:
            return "暂无可推荐的2串1组合"

        lines = ["【2串1 智能优化推荐】", ""]
        for t in tickets:
            lines.append(f"  [{t.tier.upper()}] {t.name}")
            lines.append(f"  {t.description}")
            lines.append(f"  组合赔率: {t.combined_odds:.2f} | EV: {t.combined_ev:.4f}")
            lines.append(f"  建议仓位: {t.suggested_stake:.1f}元")
            lines.append("")

        return "\n".join(lines)

    def get_shop_script(self, tickets: List[ComboTicket], total_tickets: int = 2) -> str:
        """
        生成店外话术
        """
        if not tickets:
            return "暂无2串1推荐"

        scripts = []
        for i, t in enumerate(tickets[:total_tickets]):
            script = (f"「2串1，{t.leg1.home} vs {t.leg1.away} "
                      f"{t.leg1.play_type}{t.leg1.selection}@{t.leg1.odds}，串 "
                      f"{t.leg2.home} vs {t.leg2.away} "
                      f"{t.leg2.play_type}{t.leg2.selection}@{t.leg2.odds}，"
                      f"打2元」")
            scripts.append(script)

        return "\n".join(scripts)