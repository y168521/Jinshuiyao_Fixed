# -*- coding: utf-8 -*-
"""金水谣足球预测系统 - 嵌入式骨架

【与 domains/football/ 的边界】
  本包是足球预测的 **ML 内核层**，负责纯计算：
    数据 → FeatureEngine → PoissonModel → Calibrator → DecisionEngine → RiskController
  不实现 DomainBase 接口，不直接被 core.dispatch.dispatch_football 调用。

  domains/football/domain.py 中的 FootballDomain 是 **适配层**，
  它继承 domains.base.DomainBase，内部复用本包的模型与决策引擎，
  对外暴露标准的 fetch/analyze/generate 流程。

  → 新增足球预测算法：改本包。
  → 调整足球域对外接口/流程：改 domains/football/。

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