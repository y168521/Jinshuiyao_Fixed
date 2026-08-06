# -*- coding: utf-8 -*-
"""种子脚本：向金水谣知识库注入「股票/基金 量化案例与失败案例」。

数据来源：全网调研（量化七宗罪 / 量化系统12种死亡方式 / 回测陷阱五层检查 /
Alpha操作系统全栈平台 / 多因子投研系统 等公开资料）。

设计原则：
- 仅追加，不覆盖既有知识；MiroFishDB.add_card 按 title 自动去重（幂等可重跑）。
- 卡片 domain=stock/fund（修复审计发现的「stock/fund 三元组=0 / 股票卡误标general」）。
- 同步向 graph_triples.json 追加领域三元组，让 GraphRAG 真正覆盖股基域。
- 失败案例 value_level=智慧，最佳实践 value_level=知识，便于引擎按价值层检索。
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from knowledge.mirofish_db import MiroFishDB  # noqa: E402
from utils.shared_write import protected_write_json

DB = MiroFishDB()
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

CARDS = [
    dict(
        title="回测过拟合(Overfitting)·量化死亡方式2",
        domain="stock", category="resource", value_level="智慧",
        tags=["失败案例", "过拟合", "回测陷阱", "量化"],
        engine_hook="backtest_review",
        content=("策略在历史数据上过度优化，记住噪音而非信号。典型症状：回测夏普>3、实盘夏普<0.5；"
                 "换一段历史结果迥异；参数微调收益剧变。某ML团队用200个特征回测年化80%，实盘首月亏15%，"
                 "模型学会了'每月第三个周二买科技股'这种历史巧合。预防：严格样本外测试(OOS)、限制参数数量(2-3个)、"
                 "交叉验证+Walk-forward、对'完美'回测保持怀疑。来源：waylandz《量化系统的12种典型死亡方式》。"),
        source_url="https://waylandz.com/quant-book/%E9%99%84%E5%BD%95B%EF%BC%9A%E9%87%8F%E5%8C%96%E7%B3%BB%E7%BB%9F%E7%9A%8412%E7%A7%8D%E5%85%B8%E5%9E%8B%E6%AD%BB%E4%BA%A1%E6%96%B9%E5%BC%8F",
    ),
    dict(
        title="未来函数/前视偏差(Look-ahead Bias)·回测头号陷阱",
        domain="stock", category="resource", value_level="智慧",
        tags=["失败案例", "前视偏差", "数据泄漏", "量化"],
        engine_hook="feature_compute",
        content=("不小心使用未来信息导致回测收益虚高2-10倍、实盘必失效。常见情形：用当日收盘价预测当日走势、"
                 "用未来财报构造信号、用未来成分股筛选样本。预防铁律：信号T日生成、T+1日执行；所有特征用shift(1)或更早数据；"
                 "因子计算必须用后复权价且PIT(时点)对齐；训练/测试严格按时间分离。来源：waylandz《回测系统七大陷阱》。"),
        source_url="https://www.waylandz.com/quant-book/%E7%AC%AC07%E8%AF%BE%EF%BC%9A%E5%9B%9E%E6%B5%8B%E7%B3%BB%E7%BB%9F%E7%9A%84%E9%99%B7%E9%98%B1",
    ),
    dict(
        title="幸存者偏差(Survivorship Bias)·量化七宗罪1",
        domain="stock", category="resource", value_level="智慧",
        tags=["失败案例", "幸存者偏差", "量化"],
        engine_hook="backtest_review",
        content=("只使用存续至今的股票回测，忽略已退市/被收购样本，会高估收益50%+。用特定时点成分股做多空分组，"
                 "可能因幸存者偏差得出相反结论。预防：回测须含退市股票数据；覆盖多个经济周期。来源：JoinQuant《量化七宗罪》。"),
        source_url="https://www.joinquant.com/post/49809",
    ),
    dict(
        title="数据污染型死亡·量化死亡方式1",
        domain="stock", category="resource", value_level="智慧",
        tags=["失败案例", "数据质量", "量化"],
        engine_hook="data_quality_check",
        content=("系统使用错误/缺失/被污染数据导致信号失真。案例：某团队数据商更新后把所有价格除以100(日元误标美元)，"
                 "系统以为暴跌99%疯狂做多。预防：数据质量检查管道(异常值/缺失/跳变检测)、多数据源交叉验证、"
                 "实时vs历史一致性检查、数据变更告警。来源：waylandz《量化系统的12种典型死亡方式》。"),
        source_url="https://waylandz.com/quant-book/%E9%99%84%E5%BD%95B%EF%BC%9A%E9%87%8F%E5%8C%96%E7%B3%BB%E7%BB%9F%E7%9A%8412%E7%A7%8D%E5%85%B8%E5%9E%8B%E6%AD%BB%E4%BA%A1%E6%96%B9%E5%BC%8F",
    ),
    dict(
        title="回测成本建模缺失·年化100%实盘亏50%",
        domain="stock", category="resource", value_level="智慧",
        tags=["失败案例", "交易成本", "滑点", "量化"],
        engine_hook="backtest_cost_model",
        content=("回测常忽略手续费/印花税/冲击成本，实盘这些持续侵蚀收益。一个回测年化20%的策略算上10%年交易成本实盘可能只剩5%甚至亏损。"
                 "建模标准：A股手续费约万二、滑点保守0.1-0.3%、大单用平方根冲击模型、做空计借券费。收益衰减检验：回测收益×0.5后仍可接受才实盘。"),
        source_url="https://www.waylandz.com/quant-book/%E7%AC%AC07%E8%AF%BE%EF%BC%9A%E5%9B%9E%E6%B5%8B%E7%B3%BB%E7%BB%9F%E7%9A%84%E9%99%B7%E9%98%B1",
    ),
    dict(
        title="Regime漂移型死亡·量化死亡方式3",
        domain="stock", category="resource", value_level="智慧",
        tags=["失败案例", "regime", "量化"],
        engine_hook="regime_detection",
        content=("市场状态根本变化但策略仍按旧状态运行导致失效。案例：2020-21零利率环境下成长股大幅跑赢，"
                 "坚持价值因子策略的基金回撤超50%。预防：Regime Detection模块、策略收益与基准滚动相关性监控、"
                 "多策略多因子分散、定期审视策略假设是否仍成立。"),
        source_url="https://waylandz.com/quant-book/%E9%99%84%E5%BD%95B%EF%BC%9A%E9%87%8F%E5%8C%96%E7%B3%BB%E7%BB%9F%E7%9A%8412%E7%A7%8D%E5%85%B8%E5%9E%8B%E6%AD%BB%E4%BA%A1%E6%96%B9%E5%BC%8F",
    ),
    dict(
        title="样本过短·量化七宗罪3",
        domain="stock", category="resource", value_level="智慧",
        tags=["失败案例", "样本", "量化"],
        engine_hook="backtest_review",
        content=("样本数据过短只覆盖单一行情，策略稳定性未知。标准：训练+测试≥5年且含至少1次牛熊周期；"
                 "覆盖多个经济周期才能验证泛化能力。来源：JoinQuant《量化七宗罪》/waylandz回测检查表。"),
        source_url="https://www.joinquant.com/post/49809",
    ),
    dict(
        title="多因子选股框架·公募私募主流玩法",
        domain="stock", category="resource", value_level="知识",
        tags=["最佳实践", "选股", "多因子", "量化"],
        engine_hook="stock_screen",
        content=("把几十项指标变成打分公式给全市场股票打分：价值因子(PE/PB低位)、成长因子(净利润增长)、"
                 "动量因子(近20日上涨)、质量因子(盈利质量)、资金因子(主力净流入)。综合打分排名前N买入、末尾剔除，每月调仓。"
                 "因子库按归因分库(价值/成长/动量/情绪)，采用[实体,时间,因子,版本]四维索引。来源：rdagpt《Alpha操作系统》/雪球。"),
        source_url="https://www.rdagpt.cn/archives/ji-shu-zhuan-lan-alphacao-zuo-xi-tong-gou-jian-mian-xiang",
    ),
    dict(
        title="风控中心一票否决·投资生命线",
        domain="stock", category="resource", value_level="知识",
        tags=["最佳实践", "风控", "量化"],
        engine_hook="risk_control",
        content=("风控须独立于策略执行并拥有一票否决权。实时计量市场风险(Beta/波动率)、风格因子暴露、行业集中度、流动性风险；"
                 "内置可配置规则集(持仓比例限制、最大回撤、止损线)；全流程嵌入交易前(Pre-trade)/中(In-trade)/后(Post-trade)。"
                 "任何可能超限的委托在交易前被拦截。来源：rdagpt《Alpha操作系统》。"),
        source_url="https://www.rdagpt.cn/archives/ji-shu-zhuan-lan-alphacao-zuo-xi-tong-gou-jian-mian-xiang",
    ),
    dict(
        title="量化系统五大模块·完整架构",
        domain="stock", category="resource", value_level="知识",
        tags=["最佳实践", "架构", "量化"],
        engine_hook="system_design",
        content=("一套完整量化交易系统五大模块：①数据获取与处理(行情/财务/新闻，复权与对齐)；"
                 "②策略研究与回测(买卖规则、参数优化、避开未来函数与过拟合)；③自动交易执行(信号触发自动下单)；"
                 "④风险管理(仓位管理、止损规则)；⑤性能监控与优化(实时监控、交易报告)。回测重点看四数：年化收益、最大回撤、胜率盈亏比、夏普比率。"),
        source_url="https://www.joinquant.com/post/44958",
    ),
    dict(
        title="基金定投微笑曲线·定期定额策略",
        domain="fund", category="resource", value_level="知识",
        tags=["最佳实践", "定投", "基金"],
        engine_hook="fund_dca",
        content=("基金定投核心：定期定额在下跌期积累更多份额、上涨期获利，形成'微笑曲线'。落地需模拟引擎计算累计份额/成本摊薄/收益，"
                 "而非仅存储计划。结合止盈信号(如收益达16.4%触发)与急跌/限购检测。来源：项目fund域审计+用户知识库《基金定投策略要点》。"),
    ),
    dict(
        title="基金分析核心功能清单·对照缺口",
        domain="fund", category="resource", value_level="知识",
        tags=["最佳实践", "基金分析", "功能清单"],
        engine_hook="fund_feature_gap",
        content=("完整基金分析工具应含：①基金筛选(按业绩/规模/经理多维排序)；②回测(历史净值回测，项目目前缺run_fund)；"
                 "③定投模拟(DCA收益测算，项目仅存储计划)；④资产配置(相关矩阵/均值方差优化，项目仅分组)；"
                 "⑤风险评估(波动/夏普/最大回撤，项目analyzer已强)；⑥基金经理分析(真实任职期与在管产品，项目误用成立日期)；"
                 "⑦基金对比(并排，项目一次一只)。来源：金水谣fund域能力审计。"),
    ),
]


def seed_cards():
    for c in CARDS:
        cid = DB.add_card(
            title=c["title"], content=c["content"], domain=c["domain"],
            category=c["category"], value_level=c["value_level"], tags=c["tags"],
            engine_hook=c.get("engine_hook"), source="全网调研·量化案例库",
            source_url=c.get("source_url"), extracted_at=NOW,
        )
        print("  + card", cid, "::", c["title"])


def seed_triples():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "knowledge", "graph_triples.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    existing = {(t["subject"], t["predicate"], t["object"]) for t in data["triples"]}
    triples = [
        ("量化回测", "必须避免", "过拟合(Overfitting)"),
        ("量化回测", "必须避免", "未来函数/前视偏差"),
        ("量化回测", "必须避免", "幸存者偏差"),
        ("量化回测", "必须建模", "交易成本(手续费/滑点/冲击)"),
        ("量化回测", "需要覆盖", "≥5年含牛熊周期的样本"),
        ("因子计算", "必须使用", "后复权价格且PIT对齐"),
        ("多因子选股", "是", "公募私募主流玩法"),
        ("基金定投", "依赖", "微笑曲线效应"),
        ("风控中心", "拥有", "一票否决权"),
        ("量化系统", "包含", "数据/回测/执行/风控/监控五层"),
        ("Regime漂移", "导致", "有效策略突然失效"),
        ("数据污染", "导致", "信号失真与实盘亏损"),
        ("基金分析", "应包含", "筛选/回测/定投/配置/风控/经理/对比"),
        ("金水谣fund域", "缺口", "run_fund回测引擎"),
        ("金水谣stock域", "缺口", "真实股票池筛选"),
    ]
    added = 0
    for s, p, o in triples:
        if (s, p, o) in existing:
            continue
        data["triples"].append(dict(subject=s, predicate=p, object=o,
                                    source="quant_case_studies_seed", extracted_at=NOW))
        existing.add((s, p, o))
        added += 1
    protected_write_json(path, data, intent="注入量化知识三元组")
    print("  + triples added:", added, "/ total:", len(data["triples"]))


if __name__ == "__main__":
    print("== 注入量化案例与失败案例知识 ==")
    seed_cards()
    seed_triples()
    stats = DB.stats()
    print("== 知识库统计 ==", stats.get("total_cards"), "cards;", stats.get("by_domain", {}))
    print("DONE")
