# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 模型层入口"""

from .base_model import BaseModel
from .poisson_model import PoissonModel

__all__ = ["BaseModel", "PoissonModel"]