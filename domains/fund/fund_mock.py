# -*- coding: utf-8 -*-
"""基金模拟数据生成器

akshare 不可用时的降级数据源。从 fetcher.FundFetcher 拆出以降低类复杂度。
"""
import random
from datetime import datetime, timedelta


def generate_mock_fund_list(category=None):
    """生成模拟基金列表"""
    import pandas as pd

    mock_data = [
        {"基金代码": "000001", "基金名称": "华夏成长混合", "基金类型": "混合型", "成立日期": "2001-12-18"},
        {"基金代码": "110011", "基金名称": "易方达中小盘混合", "基金类型": "混合型", "成立日期": "2008-06-19"},
        {"基金代码": "161725", "基金名称": "招商中证白酒指数", "基金类型": "指数型", "成立日期": "2015-05-27"},
        {"基金代码": "005827", "基金名称": "易方达蓝筹精选混合", "基金类型": "混合型", "成立日期": "2018-09-05"},
        {"基金代码": "001102", "基金名称": "前海开源国家比较优势", "基金类型": "股票型", "成立日期": "2015-05-21"},
        {"基金代码": "519674", "基金名称": "银河创新成长混合", "基金类型": "混合型", "成立日期": "2010-12-29"},
        {"基金代码": "003096", "基金名称": "中欧医疗健康混合", "基金类型": "混合型", "成立日期": "2016-09-29"},
        {"基金代码": "001071", "基金名称": "华安媒体互联网混合", "基金类型": "混合型", "成立日期": "2015-05-21"},
        {"基金代码": "001875", "基金名称": "前海开源沪港深优势精选", "基金类型": "混合型", "成立日期": "2016-04-19"},
        {"基金代码": "260108", "基金名称": "景顺长城新兴成长混合", "基金类型": "混合型", "成立日期": "2009-06-18"},
        {"基金代码": "000961", "基金名称": "天弘沪深300ETF联接A", "基金类型": "指数型", "成立日期": "2015-03-02"},
        {"基金代码": "110022", "基金名称": "易方达消费行业股票", "基金类型": "股票型", "成立日期": "2010-08-20"},
        {"基金代码": "000171", "基金名称": "易方达裕丰回报债券", "基金类型": "债券型", "成立日期": "2013-08-23"},
        {"基金代码": "003547", "基金名称": "鹏华丰禄债券", "基金类型": "债券型", "成立日期": "2016-10-27"},
        {"基金代码": "163406", "基金名称": "兴全合润混合", "基金类型": "混合型", "成立日期": "2010-04-22"},
    ]

    df = pd.DataFrame(mock_data)
    if category:
        df = df[df["基金类型"].str.contains(category.replace("型", ""), na=False)]
        if df.empty:
            df = pd.DataFrame(mock_data[:5])
    return df.reset_index(drop=True)


def _nav_date_range(start, end, days):
    """计算净值模拟的交易日区间"""
    import pandas as pd

    if start:
        start_date = datetime.strptime(start, "%Y%m%d")
    else:
        start_date = datetime.now() - timedelta(days=days)
    if end:
        end_date = datetime.strptime(end, "%Y%m%d")
    else:
        end_date = datetime.now()

    total_days = max(30, (end_date - start_date).days)
    return pd.date_range(start=start_date, end=end_date, freq="B")[:total_days]


def generate_mock_nav(fund_code, start=None, end=None, days=365):
    """生成模拟净值数据"""
    import pandas as pd

    random.seed(hash(fund_code) % (2**32))
    dates = _nav_date_range(start, end, days)

    base_nav = 1.0 + (hash(fund_code) % 200) / 100.0
    annual_return = 0.05 + (hash(fund_code + "r") % 200) / 1000.0
    volatility = 0.15 + (hash(fund_code + "v") % 200) / 1000.0

    data = []
    nav = base_nav
    cum_nav = base_nav * 1.5
    daily_return = annual_return / 252
    daily_vol = volatility / (252 ** 0.5)

    for date in dates:
        shock = random.gauss(daily_return, daily_vol)
        nav *= (1 + shock)
        cum_nav *= (1 + shock)
        prev_nav = data[-1]["单位净值"] if data else base_nav
        daily_growth = (nav - prev_nav) / prev_nav * 100 if prev_nav else 0
        data.append({
            "净值日期": date.strftime("%Y-%m-%d"),
            "单位净值": round(nav, 4),
            "累计净值": round(cum_nav, 4),
            "日增长率": round(daily_growth, 2),
        })

    random.seed()
    return pd.DataFrame(data)


def generate_mock_fund_info(fund_code):
    """生成模拟基金信息"""
    mock_names = {
        "000001": ("华夏成长混合", "王亚伟", "混合型", 150.5, "2001-12-18"),
        "110011": ("易方达中小盘混合", "张坤", "混合型", 280.3, "2008-06-19"),
        "161725": ("招商中证白酒指数", "侯昊", "指数型", 650.8, "2015-05-27"),
        "005827": ("易方达蓝筹精选混合", "张坤", "混合型", 520.6, "2018-09-05"),
        "001102": ("前海开源国家比较优势", "曲扬", "股票型", 85.2, "2015-05-21"),
        "519674": ("银河创新成长混合", "郑巍山", "混合型", 120.4, "2010-12-29"),
        "003096": ("中欧医疗健康混合", "葛兰", "混合型", 410.7, "2016-09-29"),
        "001071": ("华安媒体互联网混合", "胡宜斌", "混合型", 95.6, "2015-05-21"),
        "001875": ("前海开源沪港深优势精选", "曲扬", "混合型", 65.8, "2016-04-19"),
        "260108": ("景顺长城新兴成长混合", "刘彦春", "混合型", 350.2, "2009-06-18"),
    }

    if fund_code in mock_names:
        name, manager, ftype, scale, found_date = mock_names[fund_code]
    else:
        name = f"基金{fund_code}"
        manager = f"经理{fund_code[-2:]}"
        ftype = "混合型"
        scale = round(50 + (hash(fund_code) % 500), 1)
        found_date = f"20{15 + hash(fund_code) % 9}-01-01"

    return {
        "基金代码": fund_code,
        "基金名称": name,
        "基金经理": manager,
        "基金类型": ftype,
        "基金规模(亿元)": scale,
        "成立日期": found_date,
        "基金公司": f"{name[:2]}基金",
        "业绩比较基准": "沪深300指数收益率×60% + 中债总指数收益率×40%",
    }


def generate_mock_rank(category=None):
    """生成模拟基金排名数据"""
    import pandas as pd

    funds = [
        ("000001", "华夏成长混合", 2.3, 8.5, 12.1, 18.5, 45.2, 35.6),
        ("110011", "易方达中小盘混合", -1.2, 5.3, 9.8, 15.2, 52.3, 42.1),
        ("161725", "招商中证白酒指数", 3.5, 10.2, -5.6, 8.5, 38.9, 28.4),
        ("005827", "易方达蓝筹精选混合", 1.8, 6.7, 11.3, 22.1, 58.6, 48.2),
        ("001102", "前海开源国家比较优势", -2.5, 4.2, 8.9, 12.3, 35.1, 25.8),
        ("519674", "银河创新成长混合", 4.2, 12.5, 15.6, 28.7, 62.4, 55.3),
        ("003096", "中欧医疗健康混合", -3.1, 2.8, 6.5, 10.2, 32.6, 22.1),
        ("001071", "华安媒体互联网混合", 2.9, 9.1, 13.8, 24.5, 55.7, 46.8),
        ("001875", "前海开源沪港深优势精选", 0.5, 7.3, 10.2, 19.8, 48.3, 38.9),
        ("260108", "景顺长城新兴成长混合", -0.8, 5.9, 8.7, 16.5, 42.1, 36.7),
    ]

    data = []
    for i, (code, name, w1, m1, m3, m6, y1, y3) in enumerate(funds):
        data.append({
            "基金代码": code,
            "基金名称": name,
            "近1周": w1,
            "近1月": m1,
            "近3月": m3,
            "近6月": m6,
            "近1年": y1,
            "近3年": y3,
            "同类排名": f"{i+1}/1500",
        })

    return pd.DataFrame(data)


def generate_mock_holdings(fund_code):
    """生成模拟基金持仓数据"""
    import pandas as pd

    mock_stocks = [
        ("600519", "贵州茅台", 9.85, 120.5, 58600),
        ("000858", "五粮液", 8.32, 180.2, 32400),
        ("601318", "中国平安", 6.75, 250.3, 18900),
        ("000333", "美的集团", 5.42, 165.8, 16200),
        ("600036", "招商银行", 4.98, 210.6, 11500),
        ("002594", "比亚迪", 4.56, 95.3, 28300),
        ("300750", "宁德时代", 4.21, 88.7, 19800),
        ("601899", "紫金矿业", 3.89, 320.4, 7650),
        ("002415", "海康威视", 3.56, 145.2, 8900),
        ("600900", "长江电力", 3.21, 195.6, 6800),
    ]

    seed = hash(fund_code) % (2**32)
    rng = random.Random(seed)
    shuffled = mock_stocks[:]
    rng.shuffle(shuffled)

    data = []
    for code, name, ratio, shares, value in shuffled:
        adjusted = round(ratio * (0.8 + rng.random() * 0.4), 2)
        data.append({
            "股票代码": code,
            "股票名称": name,
            "占净值比例": adjusted,
            "持股数(万股)": shares,
            "持仓市值(万元)": value,
        })

    return pd.DataFrame(data)
