# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 嵌入式骨架

模块结构：
- config.py        : 全局配置
- schemas.py       : 统一数据结构 (dataclass)
- logger.py        : 日志模块
- data_provider.py : 数据提供层
- feature_engine.py: 特征工程
- odds_utils.py    : 赔率标准化
- calibrator.py    : 概率校准
- decision_engine.py: 决策引擎
- risk_controller.py: 风控层
- evaluator.py     : 评估层
- backtester.py    : 回测模块
- models/          : 模型层 (Poisson等)
- example_usage.py : 使用示例
"""

__version__ = "1.0.0"