# -*- coding: utf-8 -*-
"""金水谣系统 - 数据模型层

提供开奖数据的存储与查询：
- Data: 彩票开奖数据存取类（缓存、校验、查询）
"""

from .lottery_data import Data

__all__ = ["Data"]
