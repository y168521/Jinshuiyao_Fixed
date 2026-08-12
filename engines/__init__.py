# -*- coding: utf-8 -*-
"""金水谣引擎注册表

统一管理所有预测引擎的导入和注册。
通过 get_engine() 按引擎代码获取引擎类实例。
支持实例缓存（cached=True），避免重复创建无状态引擎。
"""
import logging
import threading

logger = logging.getLogger(__name__)

# ========== 引擎注册表 ==========
# 引擎代码 -> (模块路径, 类名)
_ENGINE_REGISTRY = {
    "killer": ("engines.killer", "Killer"),
    "evolve": ("engines.evolve", "Evolve"),
    "format_gen": ("engines.format_gen", "FormatGen"),
    "smart_brain": ("engines.smart_brain", "SmartBrain"),
    "evolution": ("engines.evolution", "EvolutionManager"),
    "morph": ("engines.morph", "MorphPredictor"),
    "correlation": ("engines.correlation", "CorrelationMatrix"),
    "hurst": ("engines.hurst", "HurstCalculator"),
    "cold_tunnel": ("engines.cold_tunnel", "ColdTunnel"),
    "position_analyzer": ("engines.position_analyzer", "PositionAnalyzer"),
    "reposition_engine": ("engines.reposition_engine", "RepositionEngine"),
    "miss_analyzer": ("engines.miss_analyzer", "MissAnalyzer"),
    "risk_controller": ("engines.risk_controller", "RiskController"),
    "trend_generator": ("engines.trend_generator", "TrendGenerator"),
    "validators": ("engines.validators", "AdvancedValidator"),
    "watchdog": ("engines.watchdog", "SystemWatchdog"),
    "health_check": ("engines.health_check", "HealthChecker"),
    "plugin_manager": ("engines.plugin_manager", "PluginManager"),
    "sync_manager": ("engines.sync_manager", "SyncManager"),
    "audit": ("engines.audit", "Audit"),
}

# ========== 引擎实例缓存 ==========
_ENGINE_CACHE = {}
_CACHE_LOCK = threading.Lock()


def get_engine(engine_code, *args, cached=False, **kwargs):
    """按引擎代码获取引擎实例
    
    Args:
        engine_code: 引擎代码（如 "killer", "smart_brain"）
        *args, **kwargs: 传递给引擎构造函数的参数
        cached: 若为 True，无参构造时复用已缓存的单例实例（线程安全）
        
    Returns:
        引擎实例，或 None（如果引擎不存在）
    """
    # 缓存命中：仅在无构造参数时生效
    if cached and not args and not kwargs:
        with _CACHE_LOCK:
            if engine_code in _ENGINE_CACHE:
                return _ENGINE_CACHE[engine_code]

    entry = _ENGINE_REGISTRY.get(engine_code)
    if not entry:
        logger.error("未知引擎代码: %s", engine_code)
        return None
    
    module_path, class_name = entry
    try:
        module = __import__(module_path, fromlist=[class_name])
        cls = getattr(module, class_name)
        instance = cls(*args, **kwargs)
        # 无参构造时写入缓存
        if cached and not args and not kwargs:
            with _CACHE_LOCK:
                _ENGINE_CACHE[engine_code] = instance
        return instance
    except Exception as e:
        logger.error("引擎 %s 加载失败: %s", engine_code, e)
        return None


def clear_engine_cache(engine_code=None):
    """清除引擎实例缓存（用于测试或热重载）
    
    Args:
        engine_code: 指定引擎代码则只清该引擎；None 则清空全部。
    """
    with _CACHE_LOCK:
        if engine_code:
            _ENGINE_CACHE.pop(engine_code, None)
        else:
            _ENGINE_CACHE.clear()
    logger.debug("引擎缓存已清除: %s", engine_code or "全部")


def list_engines():
    """列出所有已注册的引擎
    
    Returns:
        list: [(engine_code, class_name), ...]
    """
    return [(code, entry[1]) for code, entry in _ENGINE_REGISTRY.items()]


def is_registered(engine_code):
    """检查引擎是否已注册"""
    return engine_code in _ENGINE_REGISTRY
