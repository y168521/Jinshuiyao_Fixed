# -*- coding: utf-8 -*-
"""足彩专用 — 风控层

适用范围：足彩子系统（足球比赛推荐审批与资金管理）

与 engines/risk_controller.py 的关系（非重复，职责不同）：
  - jinshuiyao/risk_controller.py      — 足彩资金风控（止损/连错暂停/相关性检查/凯利仓位）
  - engines/risk_controller.py      — 彩票策略修正（号码池换血/组三组六对冲/冷热自适应）

增强要点：
- 明确资金单位（亏损比例 vs 亏损金额）
- 折扣凯利 (1/4 Kelly)
- 单日最大投注场次限制
- 相关性风控（同联赛/同球队/同时间窗口）
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta
from .schemas import Recommendation, MatchInfo
from .config import (
    KELLY_MULTIPLIER, MAX_STAKE_RATIO, DAILY_LOSS_LIMIT,
    MAX_DAILY_BETS, MAX_SAME_LEAGUE, MAX_SAME_TEAM, MAX_SAME_TIMESLOT,
)
from .logger import get_logger

logger = get_logger(__name__)

# 连错阈值：连续错误超过此值自动暂停
CONSECUTIVE_ERRORS_THRESHOLD = 3


class JinshuiyaoRiskController:
    """金水谣风控控制器"""

    def __init__(
        self,
        daily_loss_limit: float = None,
        max_daily_bets: int = None,
        max_same_league: int = None,
        max_same_team: int = None,
        max_same_timeslot: int = None,
        kelly_multiplier: float = None,
        max_stake_ratio: float = None,
        consecutive_errors_threshold: int = None,
    ):
        self.daily_loss_limit = daily_loss_limit if daily_loss_limit is not None else DAILY_LOSS_LIMIT
        self.max_daily_bets = max_daily_bets if max_daily_bets is not None else MAX_DAILY_BETS
        self.max_same_league = max_same_league if max_same_league is not None else MAX_SAME_LEAGUE
        self.max_same_team = max_same_team if max_same_team is not None else MAX_SAME_TEAM
        self.max_same_timeslot = max_same_timeslot if max_same_timeslot is not None else MAX_SAME_TIMESLOT
        self.kelly_multiplier = kelly_multiplier if kelly_multiplier is not None else KELLY_MULTIPLIER
        self.max_stake_ratio = max_stake_ratio if max_stake_ratio is not None else MAX_STAKE_RATIO
        self.consecutive_errors_threshold = consecutive_errors_threshold if consecutive_errors_threshold is not None else CONSECUTIVE_ERRORS_THRESHOLD

        # 当日状态
        self._today_bets: List[dict] = []
        self._today_loss_amount: float = 0.0
        self._today_date: str = ""

        # 连错追踪（跨日累计，不随 reset_daily 重置）
        self.consecutive_errors: int = 0
        self.consecutive_wins: int = 0
        self.auto_paused: bool = False  # 连错超限后自动暂停
        self._total_bets: int = 0       # 历史总投注数
        self._total_wins: int = 0       # 历史总胜场

    def reset_daily(self):
        """重置当日状态"""
        self._today_bets = []
        self._today_loss_amount = 0.0
        self._today_date = datetime.now().strftime("%Y-%m-%d")

    def check_daily_loss(self, today_loss_amount: float, bankroll: float) -> bool:
        """
        检查当日亏损是否超限

        Args:
            today_loss_amount: 当日累计亏损金额
            bankroll: 当前总资金

        Returns:
            True 表示可继续，False 表示已达止损线
        """
        loss_ratio = today_loss_amount / bankroll if bankroll > 0 else 0
        ok = loss_ratio <= self.daily_loss_limit
        if not ok:
            logger.warning(f"触发单日止损: 亏损{loss_ratio:.2%} > {self.daily_loss_limit:.2%}")
        return ok

    def check_daily_bets(self) -> bool:
        """检查当日推荐是否已达上限"""
        return len(self._today_bets) < self.max_daily_bets

    def check_correlation(
        self,
        match: MatchInfo,
        league: str = "",
        timeslot: str = "",
    ) -> bool:
        """
        相关性风控检查

        规则：
        1. 同一联赛最多 N 场
        2. 同一球队当天最多 1 场
        3. 同一时间窗口最多 N 场
        """
        # 联赛集中度
        if league:
            league_count = sum(1 for b in self._today_bets if b.get('league') == league)
            if league_count >= self.max_same_league:
                logger.info(f"联赛集中度超限: {league} 已达 {league_count} 场")
                return False

        # 球队重复
        home_id = match.home_team_id
        away_id = match.away_team_id
        for b in self._today_bets:
            b_home = b.get('home_team_id', '')
            b_away = b.get('away_team_id', '')
            if home_id and home_id in (b_home, b_away):
                logger.info(f"主队重复: {home_id}")
                return False
            if away_id and away_id in (b_home, b_away):
                logger.info(f"客队重复: {away_id}")
                return False

        # 时间窗口
        if timeslot:
            slot_count = sum(1 for b in self._today_bets if b.get('timeslot') == timeslot)
            if slot_count >= self.max_same_timeslot:
                logger.info(f"时间窗口集中: {timeslot} 已达 {slot_count} 场")
                return False

        return True

    def adjust_stake(self, suggested_stake: float, bankroll: float) -> float:
        """调整投注金额（应用折扣凯利和上限）"""
        adjusted = min(
            suggested_stake * self.kelly_multiplier,
            bankroll * self.max_stake_ratio,
        )
        return max(0.0, round(adjusted, 2))

    def approve_recommendation(
        self,
        rec: Recommendation,
        match: MatchInfo,
        bankroll: float,
        league: str = "",
        timeslot: str = "",
    ) -> tuple:
        """
        综合审批推荐

        Returns:
            (approved: bool, reason: str, adjusted_stake: float)
        """
        # 1. 单日场次
        if not self.check_daily_bets():
            return False, "单日推荐已达上限", 0.0

        # 2. 连错暂停
        if not self.check_consecutive_errors():
            return False, f"连错 {self.consecutive_errors} 场已自动暂停", 0.0

        # 3. 单日亏损
        if not self.check_daily_loss(self._today_loss_amount, bankroll):
            return False, "触发单日止损", 0.0

        # 4. 相关性
        if not self.check_correlation(match, league, timeslot):
            return False, "相关性风控拦截", 0.0

        # 5. 调整投注额
        adjusted_stake = self.adjust_stake(rec.suggested_stake, bankroll)

        if adjusted_stake <= 0:
            return False, "投注额为0", 0.0

        # 记录
        self._today_bets.append({
            'match_id': rec.match_id,
            'home_team_id': match.home_team_id,
            'away_team_id': match.away_team_id,
            'league': league,
            'timeslot': timeslot,
            'stake': adjusted_stake,
            'recommendation': rec.recommendation,
        })

        logger.info(f"审批通过: {rec.match_id} {rec.recommendation} stake={adjusted_stake:.2f}")
        return True, "OK", adjusted_stake

    def record_result(self, match_id: str, profit: float):
        """记录比赛结果盈亏，更新连错/连赢追踪"""
        self._today_loss_amount += abs(min(0, profit))
        self._total_bets += 1

        won = profit > 0
        if won:
            self._total_wins += 1
            self.consecutive_errors = 0
            self.consecutive_wins += 1
            # 连赢恢复自动暂停
            if self.auto_paused and self.consecutive_wins >= 2:
                self.auto_paused = False
                logger.info(f"连赢 {self.consecutive_wins} 场，自动恢复交易")
        else:
            self.consecutive_errors += 1
            self.consecutive_wins = 0
            if self.consecutive_errors >= self.consecutive_errors_threshold:
                self.auto_paused = True
                logger.warning(
                    f"连错 {self.consecutive_errors} 场 (>= {self.consecutive_errors_threshold})，"
                    f"自动暂停！建议检查模型状态"
                )

        logger.info(
            f"记录结果: {match_id} profit={profit:.2f} "
            f"连错={self.consecutive_errors} 连赢={self.consecutive_wins} "
            f"暂停={self.auto_paused}"
        )

    def check_consecutive_errors(self) -> bool:
        """检查是否触发连错暂停。True = 可继续，False = 已暂停"""
        if self.auto_paused:
            logger.warning(f"连错暂停中（{self.consecutive_errors} 场），需连赢 2 场自动恢复")
            return False
        return True

    def resume_manual(self):
        """手动恢复交易（重置连错计数）"""
        self.auto_paused = False
        self.consecutive_errors = 0
        self.consecutive_wins = 0
        logger.info("手动恢复: 连错计数已重置")

    @property
    def hit_rate(self) -> float:
        """历史胜率"""
        if self._total_bets == 0:
            return 0.0
        return self._total_wins / self._total_bets

    @property
    def status_summary(self) -> dict:
        """风控状态摘要（用于 GUI 展示）"""
        return {
            'consecutive_errors': self.consecutive_errors,
            'consecutive_wins': self.consecutive_wins,
            'auto_paused': self.auto_paused,
            'hit_rate': round(self.hit_rate, 4),
            'total_bets': self._total_bets,
            'total_wins': self._total_wins,
            'today_bets': len(self._today_bets),
            'today_loss': round(self._today_loss_amount, 2),
        }