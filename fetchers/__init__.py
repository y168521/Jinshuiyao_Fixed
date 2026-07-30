# -*- coding: utf-8 -*-
"""金水谣系统 - 数据抓取模块

多数据源开奖数据抓取与合并：
- Fetcher: 多数据源抓取器（CWL/500/新浪/乐彩等多源融合）
"""

from .fetcher import Fetcher

__all__ = ["Fetcher"]
