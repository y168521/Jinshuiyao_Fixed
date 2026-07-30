"""工具注册系统 — 统一发现和管理所有AI可调用的能力

用法:
    from core.agent_tools import tool, get_tools, call_tool

    @tool(name="lottery_predict", description="彩票号码预测", subsystem="lottery")
    def predict_lottery(target: str, params: dict = None) -> str:
        return f"预测结果: {target}"

    # 自动发现所有工具
    tools = get_tools()
    # 调用工具
    result = call_tool("lottery_predict", target="双色球")
"""

import inspect
from typing import Dict, List, Callable, Optional, Any

_TOOL_REGISTRY: Dict[str, dict] = {}


def tool(name: str = None, description: str = "", subsystem: str = "general"):
    """工具注册装饰器

    Args:
        name: 工具名（默认用函数名）
        description: 工具描述
        subsystem: 所属子系统
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        sig = inspect.signature(func)
        params = []
        for p_name, p_param in sig.parameters.items():
            params.append({
                "name": p_name,
                "default": None if p_param.default is inspect.Parameter.empty else p_param.default,
            })
        _TOOL_REGISTRY[tool_name] = {
            "name": tool_name,
            "description": description,
            "subsystem": subsystem,
            "params": params,
            "func": func,
        }
        return func
    return decorator


def get_tools(subsystem: str = None) -> List[Dict]:
    """获取已注册的工具列表

    Args:
        subsystem: 按子系统过滤（可选）

    Returns:
        [{name, description, subsystem, params}, ...]
    """
    result = []
    for info in _TOOL_REGISTRY.values():
        if subsystem and info["subsystem"] != subsystem:
            continue
        result.append({
            "name": info["name"],
            "description": info["description"],
            "subsystem": info["subsystem"],
            "params": info["params"],
        })
    return result


def call_tool(tool_name: str, **kwargs) -> Any:
    """调用已注册的工具

    Args:
        tool_name: 工具名
        **kwargs: 工具参数

    Returns:
        工具返回结果
    """
    info = _TOOL_REGISTRY.get(tool_name)
    if not info:
        return f"未知工具: {tool_name}"
    try:
        return info["func"](**kwargs)
    except Exception as e:
        return f"工具执行失败 [{tool_name}]: {e}"


def get_tool_descriptions() -> str:
    """返回所有工具的文本描述（用于构造 system prompt）"""
    lines = ["可用工具:"]
    for info in _TOOL_REGISTRY.values():
        params_str = ", ".join(p["name"] for p in info["params"])
        lines.append(f"  - {info['name']}({params_str}): {info['description']} [{info['subsystem']}]")
    return "\n".join(lines)
