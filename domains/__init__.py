# -*- coding: utf-8 -*-
"""金水谣系统 - 域子系统包

所有预测域（彩票、足彩、股票等）的注册入口。
每个域实现 DomainBase 标准接口，通过 core.registry 注册后由内核统一调度。
"""

# 延迟导入，避免循环依赖
def _init_domains():
    """初始化所有域子系统"""
    from core.registry import register
    from domains.lottery.domain import LotteryDomain
    from domains.football.domain import FootballDomain
    from domains.stock.domain import StockDomain
    from domains.music.domain import MusicDomain
    from domains.fund.domain import FundDomain
    from domains.creator.domain import CreatorDomain
    register("lottery", LotteryDomain, "彩票预测（双色球/大乐透/3D/排列三/七乐彩/七星彩/快乐8）")
    register("football", FootballDomain, "足球比赛预测（泊松模型 + ML集成 + 风控）")
    register("stock", StockDomain, "A股预测（技术指标 + 趋势分析 + 选股信号）")
    register("music", MusicDomain, "音乐/音频处理（格式转换/音量标准化/智能优化/旋律生成）")
    register("fund", FundDomain, "基金分析（净值分析/风险评估/经理评价/持仓分析/推荐生成）")
    register("creator", CreatorDomain, "创作者工具箱（AI文案/语音转文字/智能配音/OCR/音频提取/去水印）")

# 由内核在启动时调用
init_domains = _init_domains
