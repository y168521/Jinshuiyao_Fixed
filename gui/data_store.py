# -*- coding: utf-8 -*-
"""数据持久化工具（预测/参考池/设置的JSON读写）

从 main_window.py 拆出的纯数据操作函数，零 GUI 依赖。
调用方传入数据即可，GUI 层负责同步 self.xxx 状态。
"""

import logging
from config import PRED_CACHE, ENGINE_SET, REFERENCE_CACHE
from utils.safe_json import safe_load_json, safe_write_json
from utils.locks import preds_lock

logger = logging.getLogger(__name__)


# ==================== 预测数据 ====================

def load_preds_data():
    """从 PRED_CACHE 加载预测数据（纯数据函数）

    Returns:
        list: 预测列表，失败返回空列表
    """
    try:
        data = safe_load_json(PRED_CACHE, default=[])
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_preds_data(preds):
    """保存预测数据到 PRED_CACHE（纯数据函数）

    Args:
        preds: 预测列表
    """
    try:
        with preds_lock:
            safe_write_json(PRED_CACHE, preds)
    except Exception as e:
        logger.error("保存预测失败: %s", e)


# ==================== 参考池 ====================

def load_reference_pool_data():
    """从 REFERENCE_CACHE 加载参考池（纯数据函数）

    Returns:
        list: 参考池列表，失败返回空列表
    """
    try:
        data = safe_load_json(REFERENCE_CACHE, default=[])
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_reference_pool_data(pool):
    """保存参考池到 REFERENCE_CACHE（纯数据函数）

    Args:
        pool: 参考池列表
    """
    try:
        safe_write_json(REFERENCE_CACHE, pool)
    except Exception as e:
        logger.error("保存参考池失败: %s", e)


def add_to_pool_data(pool, lot, period, nums, date_str=None):
    """添加条目到参考池（纯数据函数）

    Args:
        pool: 当前参考池列表
        lot: 彩种名称
        period: 期号
        nums: 号码字符串
        date_str: 日期字符串（可选）

    Returns:
        list: 更新后的参考池列表
    """
    import datetime
    entry = {
        "lot": lot,
        "period": period,
        "nums": nums,
        "date": date_str or datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    pool.append(entry)
    return pool


# ==================== 设置管理 ====================

def load_settings_data(engine_list):
    """从 ENGINE_SET 加载引擎设置（纯数据函数，不含tk变量同步）

    Args:
        engine_list: 引擎名称列表

    Returns:
        dict: 设置字典，包含引擎开关/预算/热号窗口等
    """
    try:
        settings = safe_load_json(ENGINE_SET, default={})
        return settings if isinstance(settings, dict) else {}
    except Exception:
        return {}


def save_settings_data(engine_states, engine_list, max_budget, hot_window, vote, debug_mode):
    """组装设置字典并保存到 ENGINE_SET（纯数据函数，不含tk变量读取）

    Args:
        engine_states: dict, 引擎名→布尔值
        engine_list: 引擎名称列表
        max_budget: 最大预算值
        hot_window: 热号窗口值
        vote: 是否投票
        debug_mode: 是否调试模式

    Returns:
        dict: 保存的设置字典
    """
    try:
        settings = {}
        for eng in engine_list:
            settings[eng] = engine_states.get(eng, False)
        settings["max_budget"] = max_budget
        settings["hot_window"] = hot_window
        settings["vote"] = vote
        settings["debug_mode"] = debug_mode
        safe_write_json(ENGINE_SET, settings)
        return settings
    except Exception as e:
        logger.error("保存设置失败: %s", e)
        return {}
