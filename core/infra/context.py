# -*- coding: utf-8 -*-
"""金水谣内核 - 子系统上下文隔离

使用 Python contextvars 实现协程安全的子系统上下文传递。
所有模块通过 get_current_subsystem() 获取当前子系统ID，
无需层层传参，自动隔离不同子系统的运行状态。

借鉴: Jupyter Kernel 的进程隔离思想 + AWS Lambda 多租户隔离实践
"""
import contextvars
import logging

logger = logging.getLogger(__name__)

# ========== 子系统上下文变量 ==========
# 当前子系统ID（如 "lottery", "football", "stock"）
current_subsystem_id: contextvars.ContextVar = contextvars.ContextVar(
    "current_subsystem_id", default="lottery"
)

# 当前子系统引擎实例（可选，用于快速获取引擎引用）
current_engine_instance: contextvars.ContextVar = contextvars.ContextVar(
    "current_engine_instance", default=None
)


# ========== 辅助函数 ==========

def get_current_subsystem() -> str:
    """获取当前子系统ID
    
    Returns:
        str: 子系统标识符，如 "lottery", "football", "stock"
    """
    return current_subsystem_id.get()


def set_subsystem_context(subsystem_id: str):
    """设置子系统上下文（返回token用于恢复）
    
    Args:
        subsystem_id: 子系统标识符
        
    Returns:
        token: 用于 reset() 恢复上下文
    """
    return current_subsystem_id.set(subsystem_id)


def reset_subsystem_context(token):
    """恢复子系统上下文
    
    Args:
        token: set_subsystem_context() 返回的token
    """
    current_subsystem_id.reset(token)


def run_in_subsystem(subsystem_id: str, func, *args, **kwargs):
    """在指定子系统上下文中执行函数（自动管理token生命周期）
    
    Args:
        subsystem_id: 子系统标识符
        func: 要执行的函数
        *args, **kwargs: 传递给func的参数
        
    Returns:
        func的返回值
    """
    token = set_subsystem_context(subsystem_id)
    try:
        return func(*args, **kwargs)
    finally:
        reset_subsystem_context(token)
