# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 全局配置"""

# ============================================================
# 数据源配置
# ============================================================
import os
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DATA_DIR = _DATA_DIR
MATCHES_CSV = os.path.join(_DATA_DIR, "matches.csv")
TEAM_STATS_CSV = os.path.join(_DATA_DIR, "team_stats.csv")
ODDS_CSV = os.path.join(_DATA_DIR, "odds.csv")
RESULTS_CSV = os.path.join(_DATA_DIR, "results.csv")

# ============================================================
# 模型配置
# ============================================================
# 泊松模型
POISSON_MAX_GOALS = 10       # 比分矩阵上限 (0 ~ max_goals)
POISSON_MIN_LAMBDA = 0.05    # 最低进球期望，防止 log(0)

# 模型权重 (ensemble 时使用)
MODEL_WEIGHTS = {
    "poisson": 0.40,
    "xgboost": 0.35,
    "neural_net": 0.25,
}

# ============================================================
# 决策层配置
# ============================================================
EV_THRESHOLD = 0.03           # 最低期望价值
VALUE_GAP_THRESHOLD = 0.03    # 模型概率 vs 市场隐含概率最低差
MIN_ODDS = 1.35               # 最低赔率过滤
MAX_ODDS = 6.00               # 最高赔率过滤

# ============================================================
# 概率校准配置
# ============================================================
CALIBRATION_ALPHA = 0.75      # 模型置信度 (0=完全相信市场, 1=完全相信模型)

# ============================================================
# 风控配置
# ============================================================
KELLY_MULTIPLIER = 0.25       # 折扣凯利 (1/4 Kelly)
MAX_STAKE_RATIO = 0.05        # 单注最大资金占比
DAILY_LOSS_LIMIT = 0.08       # 单日最大亏损比例
MAX_DAILY_BETS = 5            # 单日最多推荐场次
MAX_SAME_LEAGUE = 2           # 同一联赛最多推荐
MAX_SAME_TEAM = 1             # 同一球队当天最多
MAX_SAME_TIMESLOT = 3         # 同一时间窗口最多
INITIAL_BANKROLL = 1000.0     # 初始资金

# ============================================================
# 特征默认值 (数据缺失时使用)
# ============================================================
DEFAULT_GOALS_SCORED_AVG = 1.3
DEFAULT_GOALS_CONCEDED_AVG = 1.3
DEFAULT_XG_AVG = 1.3
DEFAULT_XGA_AVG = 1.3