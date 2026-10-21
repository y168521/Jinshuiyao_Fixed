# -*- coding: utf-8 -*-
"""基金数据标准化（JS-20261021-04 从 `fetcher.FundFetcher` 拆出）

把 akshare 返回的列名归一成项目内部口径。与 `fund_mock.py`、`fund_cache.py`
同一路拆包：让 `FundFetcher` 只负责"取数调度"，列名映射这类纯变换独立可测。

这四个函数都是**纯函数**（无 I/O、无状态），改列名映射不影响取数链路。
"""
import logging

logger = logging.getLogger(__name__)


def standardize_fund_list(df):
    """标准化基金列表列名"""
    col_map = {
        "基金代码": "基金代码",
        "基金简称": "基金名称",
        "基金类型": "基金类型",
        "成立日期": "成立日期",
        "发行日期": "发行日期",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    # 确保必要列存在
    required = ["基金代码", "基金名称"]
    for col in required:
        if col not in df.columns:
            df[col] = ""
    return df


def standardize_nav(df):
    """标准化净值数据列名"""
    col_map = {
        "净值日期": "净值日期",
        "单位净值": "单位净值",
        "累计净值": "累计净值",
        "日增长率": "日增长率",
        "日期": "净值日期",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "净值日期" in df.columns:
        df["净值日期"] = df["净值日期"].astype(str)
    return df


def standardize_rank(df):
    """标准化排名数据列名"""
    col_map = {
        "基金代码": "基金代码",
        "基金简称": "基金名称",
        "近1周": "近1周",
        "近1月": "近1月",
        "近3月": "近3月",
        "近6月": "近6月",
        "近1年": "近1年",
        "近3年": "近3年",
        "今年来": "今年来",
        "成立来": "成立来",
        "同类排名": "同类排名",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    return df


def standardize_holdings(df):
    """标准化持仓数据列名"""
    col_map = {
        "股票代码": "股票代码",
        "股票名称": "股票名称",
        "占净值比例": "占净值比例",
        "持股数（万股）": "持股数",
        "持仓市值（万元）": "持仓市值",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    return df
