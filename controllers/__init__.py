# -*- coding: utf-8 -*-
"""金水谣系统 - 业务控制层

提供方案管理和预算分配等业务逻辑：
- SchemeManager: 方案管理器（增删改查、命中率追踪）
- BudgetControllerV2: 预算分配器（按彩种分配投注预算）
"""

from .scheme_manager import SchemeManager
from .budget_controller import BudgetControllerV2

__all__ = ["SchemeManager", "BudgetControllerV2"]
