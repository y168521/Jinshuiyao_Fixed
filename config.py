# -*- coding: utf-8 -*-
"""金水谣系统 - 全局配置常量"""
import os
import datetime
import json
import logging

logger = logging.getLogger(__name__)

VERSION = "金水谣·十二穹武 V23.6 终版（3单+1复+1胆拖 + 线程安全修复版）"
# 使用脚本所在目录构建绝对路径，避免 cwd 不是项目根时解析到错误位置
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(_SCRIPT_DIR, "金水谣数据")
DATA_SAVE = os.path.join(BASE_DIR, "lot_data")
PRED_CACHE = os.path.join(BASE_DIR, "predictions.json")
ENGINE_SET = os.path.join(BASE_DIR, "engines.json")
SCHEME_CACHE = os.path.join(BASE_DIR, "schemes.json")
REFERENCE_CACHE = os.path.join(BASE_DIR, "reference_pool.json")
MATRIX_CACHE = os.path.join(BASE_DIR, "correlation_matrix.json")
CONFIG_RULE_PATH = os.path.join(BASE_DIR, "rule_config.json")
LOG_DIR = os.path.join(BASE_DIR, "log")
ERR_LOG_DIR = os.path.join(LOG_DIR, "err_log")

for d in [BASE_DIR, DATA_SAVE, LOG_DIR, ERR_LOG_DIR]:
    os.makedirs(d, exist_ok=True)

LOTTERY_RULES = {
    "双色球": {"red": (1, 33, 6), "blue": (1, 16, 1), "period_len": 7, "ssq": True, "draw_days": [1, 3, 6]},
    "大乐透": {"red": (1, 35, 5), "blue": (1, 12, 2), "period_len": 7, "ssq": True, "draw_days": [0, 2, 5]},
    "福彩3D": {"red": (0, 9, 3), "period_len": 7, "digit": True, "draw_days": "daily"},
    "排列三": {"red": (0, 9, 3), "period_len": 7, "digit": True, "draw_days": "daily"},
    "七乐彩": {"red": (1, 30, 7), "special": True, "period_len": 7, "draw_days": [0, 2, 4]},
    "七星彩": {"red": (0, 9, 6), "period_len": 7, "digit": True, "special_code": (0, 14, 1), "draw_days": [1, 4, 6]},
    "快乐8": {"red": (1, 80, 10), "flexible": True, "period_len": 7, "draw_days": "daily"},
}

if os.path.exists(CONFIG_RULE_PATH):
    try:
        with open(CONFIG_RULE_PATH, "r", encoding="utf-8") as f:
            LOTTERY_RULES.update(json.load(f))
    except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
        logger.warning("[config] rule_config.json 加载失败: %s，尝试备份恢复", e)
        try:
            from utils.safe_json import safe_load_json
            recovered = safe_load_json(CONFIG_RULE_PATH, default={})
            if recovered:
                LOTTERY_RULES.update(recovered)
                logger.info("[config] rule_config.json 已从备份恢复")
        except ImportError:
            logger.warning("[config] safe_json不可用，使用默认规则配置")
    # 加载rule_config后对每个彩种做关键字段补全
    _default_keys = {"red": (1, 33, 6), "blue": None, "period_len": 7,
                     "digit": False, "ssq": False, "special": False, "flexible": False,
                     "draw_days": None, "special_code": None}
    for _lot_name, _lot_cfg in LOTTERY_RULES.items():
        for _key, _default_val in _default_keys.items():
            if _key not in _lot_cfg:
                _lot_cfg[_key] = _default_val

EXCLUDED_LOTS = ["排列五"]

# 大盘彩诚实降级（JS-20260727 十七模型元分析缺口#3 闭环）：
# 依据诚实回测(walk-forward)+随机基准接线的实测定论——预测无超越随机的能力，
# 生成预测时必须强制附带该警示（domains/lottery/domain.py generate() 读取），前端须展示。
# 数据出处：backtest_lottery_honest.py / lottery_health_report.json（gain 全域≈0）。
DEGRADED_LOTS = {
    "七星彩": "诚实回测 0/180 命中、随机基准增益≈0：无预测力。仅供展示，强烈建议不投注大盘彩。",
    "双色球": "诚实回测增益 -0.78%（跑输随机基准）：无预测力。固定小额娱乐可以，勿信任何选号策略。",
    "大乐透": "大盘彩诚实回测无超越随机的证据：无预测力。固定小额娱乐可以，勿信任何选号策略。",
}

LOT_ALL = [l for l in LOTTERY_RULES.keys() if l not in EXCLUDED_LOTS]
LOT_ALIAS = {l: l for l in LOT_ALL}
LOT_ALIAS.update({
    "3D": "福彩3D", "kl8": "快乐8", "ssq": "双色球", "dlt": "大乐透",
    "qxc": "七星彩", "七星彩": "七星彩", "7星彩": "七星彩",
    "排列3": "排列三", "排三": "排列三", "P3": "排列三", "排3": "排列三"
})

ENGINE_NAMES = {
    "trend": "趋势惯性", "turning": "拐点突变", "missing": "遗漏极值",
    "cycle": "冷热轮回", "antikill": "反杀纠错", "filter": "过滤防护",
    "risk": "风控熔断", "morph": "形态引擎", "killcheck": "杀号校验",
    "correlation": "关联矩阵", "cold_tunnel": "冷号突破",
    "hurst": "赫斯特指数", "vote": "多引擎投票", "hot_freq": "热号频次法"
}

TICKET_PRICE = 2
DEFAULT_MAX_BUDGET = 149
MAX_BUDGET_LIMIT = 5000
DEFAULT_HOT_WINDOW = 10