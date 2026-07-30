# -*- coding: utf-8 -*-
"""金水谣足彩系统 - 球队稳定性监控 v3.0

6维度稳定性追踪 + 自动预警：
  1. 进攻火力稳定性 — 近N场 xG 标准差
  2. 防守稳固稳定性 — 近N场 xGA 标准差
  3. 阵容完整度     — 核心球员缺阵数量
  4. 近期战绩稳定性 — 胜率波动 + 连胜/连败检测
  5. 战术执行稳定性 — 控球率/传球成功率标准差
  6. 大赛心理稳定性 — 历史淘汰赛/点球胜率
"""

from typing import List, Dict, Tuple
from dataclasses import dataclass, field


# 预警阈值
@dataclass
class AlertThresholds:
    xg_std: float = 0.35        # 进攻波动
    xga_std: float = 0.30       # 防守波动
    key_injuries: int = 2       # 核心缺阵数
    possession_std: float = 8.0  # 控球率标准差%
    pass_std: float = 6.0       # 传球成功率标准差%
    penalty_winrate: float = 0.40  # 点球/加时胜率
    losing_streak: int = 2      # 连败场次
    points_last5: int = 4       # 近5场最低积分


@dataclass
class StabilityReport:
    """稳定性诊断报告"""
    team_name: str
    dimensions: Dict[str, float] = field(default_factory=dict)  # 6维度值 (0~100，越高越稳定)
    alerts: List[str] = field(default_factory=list)
    overall_score: float = 50.0   # 综合稳定性分
    level: str = "normal"         # normal / warning / critical


class TeamStabilityTracker:
    """球队稳定性追踪器"""

    def __init__(self, thresholds: AlertThresholds = None):
        self.thresholds = thresholds or AlertThresholds()

    def analyze(
        self,
        team_name: str,
        recent_xg: List[float],         # 近 N 场 xG 列表
        recent_xga: List[float],        # 近 N 场 xGA 列表
        possession_list: List[float],   # 近 N 场控球率
        pass_accuracy_list: List[float],# 近 N 场传球成功率
        recent_results: List[str],      # 近 N 场结果 ['W','L','D',...]
        key_injuries: int = 0,          # 核心缺阵人数
        penalty_winrate: float = 0.5,   # 历史点球/加时胜率
    ) -> StabilityReport:
        """
        分析球队稳定性并生成诊断报告
        """
        report = StabilityReport(team_name=team_name)
        alerts = []

        # 1. 进攻稳定性
        xg_std = _safe_std(recent_xg)
        offense_stability = max(0, 100 - xg_std * 200)
        if xg_std > self.thresholds.xg_std:
            alerts.append(f"⚡ 进攻端状态起伏大 (xG标准差={xg_std:.2f})")

        # 2. 防守稳定性
        xga_std = _safe_std(recent_xga)
        defense_stability = max(0, 100 - xga_std * 250)
        if xga_std > self.thresholds.xga_std:
            alerts.append(f"🛡 防守端不稳定 (xGA标准差={xga_std:.2f})")

        # 3. 阵容完整度
        squad_stability = max(0, 100 - key_injuries * 35)
        if key_injuries >= self.thresholds.key_injuries:
            alerts.append(f"🏥 缺少 {key_injuries} 名核心球员")

        # 4. 战绩稳定性
        points, streak = _analyze_results(recent_results)
        form_stability = points / (len(recent_results) * 3) * 100
        if streak <= -self.thresholds.losing_streak:
            alerts.append(f"📉 连败 {abs(streak)} 场，状态低迷")
        if streak >= 3:
            alerts.append(f"📈 连胜 {streak} 场，注意拐点风险")
        if points <= self.thresholds.points_last5 and len(recent_results) >= 5:
            alerts.append(f"⚠ 近{len(recent_results)}场仅积{points}分")

        # 5. 战术执行稳定性
        poss_std = _safe_std(possession_list)
        pass_std = _safe_std(pass_accuracy_list)
        tactic_stability = max(0, 100 - poss_std * 8 - pass_std * 10)
        if poss_std > self.thresholds.possession_std:
            alerts.append(f"🔄 控球率波动大 (std={poss_std:.1f}%)")
        if pass_std > self.thresholds.pass_std:
            alerts.append(f"🔄 传球成功率波动大 (std={pass_std:.1f}%)")

        # 6. 大赛心理稳定性
        mental_stability = penalty_winrate * 100
        if penalty_winrate < self.thresholds.penalty_winrate:
            alerts.append(f"💔 大赛抗压能力不足 (点球/加时胜率={penalty_winrate:.0%})")

        # 综合评分
        dims = {
            '进攻稳定': round(offense_stability),
            '防守稳定': round(defense_stability),
            '阵容完整': round(squad_stability),
            '战绩稳定': round(form_stability),
            '战术执行': round(tactic_stability),
            '大赛心理': round(mental_stability),
        }
        report.dimensions = dims
        report.alerts = alerts

        # 综合分 = 均值 + 预警惩罚
        avg = sum(dims.values()) / len(dims)
        report.overall_score = round(max(0, avg - len(alerts) * 5))

        if len(alerts) >= 3:
            report.level = "critical"
        elif len(alerts) >= 1:
            report.level = "warning"
        else:
            report.level = "normal"

        return report

    def compare(
        self,
        home_report: StabilityReport,
        away_report: StabilityReport,
    ) -> str:
        """两队稳定性对比文字报告"""
        lines = [
            f"【稳定性对比】{home_report.team_name} vs {away_report.team_name}",
            f"  {home_report.team_name}: {home_report.overall_score}分 "
            f"({home_report.level}) 预警{len(home_report.alerts)}项",
            f"  {away_report.team_name}: {away_report.overall_score}分 "
            f"({away_report.level}) 预警{len(away_report.alerts)}项",
            "",
        ]

        dims = list(home_report.dimensions.keys())
        lines.append(f"  {'维度':　<8} {home_report.team_name:　<10} {away_report.team_name:　<10}")
        lines.append("  " + "-" * 32)
        for d in dims:
            hv = home_report.dimensions[d]
            av = away_report.dimensions[d]
            marker = " ←" if hv > av + 5 else (" →" if av > hv + 5 else "  ")
            lines.append(f"  {d:　<8} {hv:>3}  {marker}  {av:<3}")

        if home_report.alerts:
            lines.append(f"\n  [{home_report.team_name} 预警]")
            for a in home_report.alerts:
                lines.append(f"    {a}")
        if away_report.alerts:
            lines.append(f"\n  [{away_report.team_name} 预警]")
            for a in away_report.alerts:
                lines.append(f"    {a}")

        return "\n".join(lines)


def _safe_std(values: List[float]) -> float:
    """安全计算标准差"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return variance ** 0.5


def _analyze_results(results: List[str]) -> Tuple[int, int]:
    """
    分析近期战绩

    Returns:
        (总积分, 连胜/连败数) — 正数=连胜，负数=连败
    """
    points = 0
    max_streak = 0
    current_streak = 0

    for r in results:
        r = r.upper().strip()
        if r == 'W':
            points += 3
            if current_streak >= 0:
                current_streak += 1
            else:
                current_streak = 1
        elif r == 'D':
            points += 1
            current_streak = 0
        elif r == 'L':
            if current_streak <= 0:
                current_streak -= 1
            else:
                current_streak = -1
        else:
            current_streak = 0

        if abs(current_streak) > abs(max_streak):
            max_streak = current_streak

    return points, max_streak