# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 数据提供层

修复要点：
- 明确区分 team_id 和 team_name
- get_match_basic() 同时返回 id 和 name
- 新增 get_result() 用于回测
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import pandas as pd
from .schemas import MatchInfo
from .config import MATCHES_CSV, TEAM_STATS_CSV, ODDS_CSV, RESULTS_CSV
from .logger import get_logger

logger = get_logger(__name__)


class DataProvider(ABC):
    """数据提供抽象基类"""

    @abstractmethod
    def get_match_basic(self, match_id: str) -> MatchInfo:
        """获取比赛基本信息"""
        pass

    @abstractmethod
    def get_recent_form(self, team_id: str, n: int = 10) -> pd.DataFrame:
        """获取球队近 N 场数据"""
        pass

    @abstractmethod
    def get_odds(self, match_id: str) -> Dict[str, float]:
        """获取赔率：{'home_win': 2.1, 'draw': 3.2, 'away_win': 3.5}"""
        pass

    @abstractmethod
    def get_result(self, match_id: str) -> str:
        """返回实际赛果：'win' / 'draw' / 'lose'"""
        pass

    @abstractmethod
    def get_h2h(self, team_id_a: str, team_id_b: str, n: int = 5) -> pd.DataFrame:
        """获取两队历史交锋"""
        pass


class CSVDataProvider(DataProvider):
    """CSV 文件数据提供器"""

    def __init__(self):
        self._matches: Optional[pd.DataFrame] = None
        self._stats: Optional[pd.DataFrame] = None
        self._odds: Optional[pd.DataFrame] = None
        self._results: Optional[pd.DataFrame] = None
        self._load_data()

    def _load_data(self):
        """加载 CSV 数据"""
        import os.path
        try:
            if os.path.exists(MATCHES_CSV):
                self._matches = pd.read_csv(MATCHES_CSV)
                logger.info(f"加载比赛数据: {len(self._matches)} 条")
            else:
                self._matches = pd.DataFrame()
                logger.warning(f"比赛数据文件不存在: {MATCHES_CSV}")
        except Exception as e:
            self._matches = pd.DataFrame()
            logger.error(f"加载比赛数据失败: {e}")

        try:
            if os.path.exists(TEAM_STATS_CSV):
                self._stats = pd.read_csv(TEAM_STATS_CSV)
            else:
                self._stats = pd.DataFrame()
        except Exception:
            self._stats = pd.DataFrame()

        try:
            if os.path.exists(ODDS_CSV):
                self._odds = pd.read_csv(ODDS_CSV)
            else:
                self._odds = pd.DataFrame()
        except Exception:
            self._odds = pd.DataFrame()

        try:
            if os.path.exists(RESULTS_CSV):
                self._results = pd.read_csv(RESULTS_CSV)
            else:
                self._results = pd.DataFrame()
        except Exception:
            self._results = pd.DataFrame()

    def get_match_basic(self, match_id: str) -> MatchInfo:
        """获取比赛基本信息，同时返回 team_id 和 team_name"""
        if self._matches is None or self._matches.empty:
            raise ValueError(f"比赛数据为空，无法查询 {match_id}")

        row = self._matches[self._matches['match_id'] == match_id]
        if row.empty:
            raise ValueError(f"未找到比赛: {match_id}")

        r = row.iloc[0]
        return MatchInfo(
            match_id=str(r.get('match_id', match_id)),
            home_team_id=str(r.get('home_team_id', '')),
            away_team_id=str(r.get('away_team_id', '')),
            home_team_name=str(r.get('home_team_name', r.get('home_team', ''))),
            away_team_name=str(r.get('away_team_name', r.get('away_team', ''))),
            league=str(r.get('league', '')),
            date=str(r.get('date', '')),
            kickoff_time=str(r.get('kickoff_time', '')),
        )

    def get_recent_form(self, team_id: str, n: int = 10) -> pd.DataFrame:
        """获取球队近 N 场统计数据"""
        if self._stats is None or self._stats.empty:
            return pd.DataFrame()

        df = self._stats[self._stats['team_id'] == team_id].copy()
        if df.empty:
            logger.warning(f"未找到球队数据: team_id={team_id}")
            return pd.DataFrame()

        return df.sort_values('date', ascending=False).head(n)

    def get_odds(self, match_id: str) -> Dict[str, float]:
        """获取赔率"""
        if self._odds is None or self._odds.empty:
            return {'home_win': 2.0, 'draw': 3.2, 'away_win': 3.5}

        row = self._odds[self._odds['match_id'] == match_id]
        if row.empty:
            logger.warning(f"未找到赔率: {match_id}")
            return {'home_win': 2.0, 'draw': 3.2, 'away_win': 3.5}

        r = row.iloc[0]
        return {
            'home_win': float(r.get('home_win', 2.0)),
            'draw': float(r.get('draw', 3.2)),
            'away_win': float(r.get('away_win', 3.5)),
        }

    def get_result(self, match_id: str) -> str:
        """返回实际赛果：'win' / 'draw' / 'lose'"""
        if self._results is None or self._results.empty:
            raise ValueError(f"无赛果数据: {match_id}")

        row = self._results[self._results['match_id'] == match_id]
        if row.empty:
            raise ValueError(f"未找到赛果: {match_id}")

        result = str(row.iloc[0].get('result', '')).lower()
        if result in ('win', 'home', 'h'):
            return 'win'
        elif result in ('draw', 'd'):
            return 'draw'
        elif result in ('lose', 'away', 'a'):
            return 'lose'
        else:
            raise ValueError(f"未知赛果: {result}")

    def get_h2h(self, team_id_a: str, team_id_b: str, n: int = 5) -> pd.DataFrame:
        """获取两队历史交锋（兼容 team_id 和队名匹配）"""
        if self._matches is None or self._matches.empty:
            return pd.DataFrame()

        # 优先用 team_id 匹配，如果没有该列则用队名匹配
        has_id_cols = 'home_team_id' in self._matches.columns
        if has_id_cols:
            h2h = self._matches[
                ((self._matches['home_team_id'] == team_id_a) & (self._matches['away_team_id'] == team_id_b)) |
                ((self._matches['home_team_id'] == team_id_b) & (self._matches['away_team_id'] == team_id_a))
            ].copy()
        else:
            has_name_cols = 'home' in self._matches.columns and 'away' in self._matches.columns
            if has_name_cols:
                h2h = self._matches[
                    ((self._matches['home'] == team_id_a) & (self._matches['away'] == team_id_b)) |
                    ((self._matches['home'] == team_id_b) & (self._matches['away'] == team_id_a))
                ].copy()
            else:
                return pd.DataFrame()

        return h2h.sort_values('date', ascending=False).head(n)

    def get_match_ids(self, league: str = None, date: str = None) -> List[str]:
        """获取比赛 ID 列表，可按联赛和日期过滤"""
        if self._matches is None or self._matches.empty:
            return []

        df = self._matches.copy()
        if league:
            df = df[df['league'] == league]
        if date:
            df = df[df['date'] == date]

        return df['match_id'].tolist()