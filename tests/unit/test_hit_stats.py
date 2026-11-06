# -*- coding: utf-8 -*-
"""gui.main_window.build_hit_stats_text 单测（JS-20261106-01）。

纯函数可测：无需 tkinter 环境即可验证命中率面板文本的生成，
重点是「全部彩种都显示、不再因 [:4] 截断漏掉大乐透等」。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from gui.main_window import build_hit_stats_text, determine_hit_type  # noqa: E402


def test_empty_reviewed_shows_placeholder():
    text = build_hit_stats_text([])
    assert "暂无复盘数据" in text


def test_all_seven_lots_shown_not_truncated():
    """构造覆盖全部 7 个彩种、各含命中/未命中的已复盘记录，验证均无遗漏。"""
    lots = ["福彩3D", "排列三", "快乐8", "双色球", "七乐彩", "大乐透", "七星彩"]
    reviewed = []
    for lot in lots:
        reviewed.append({"lot": lot, "hits": 1})  # 命中
        reviewed.append({"lot": lot, "hits": 0})  # 未命中
    text = build_hit_stats_text(reviewed)
    for lot in lots:
        assert f"{lot} 50%" in text, f"{lot} 应出现在命中率面板（各 1 中 1 未中 = 50%）"
    # 大乐透这一条正是用户反馈缺失的，重点回归
    assert "大乐透 50%" in text


def test_truncation_regression_ten_lots():
    """回归：即便某彩种复盘数很少，也必须出现（不再被旧 [:4] 截掉）。"""
    reviewed = [{"lot": f"彩种{i}", "hits": 1} for i in range(10)]
    text = build_hit_stats_text(reviewed)
    for i in range(10):
        assert f"彩种{i} 100%" in text, f"彩种{i} 不应被截断"


def test_rate_matches_data():
    """命中率数值应与输入一致（大乐透 2 中 1 未中 = 约 66%）。"""
    reviewed = [
        {"lot": "大乐透", "hits": 1},
        {"lot": "大乐透", "hits": 1},
        {"lot": "大乐透", "hits": 0},
    ]
    text = build_hit_stats_text(reviewed)
    assert "大乐透 67%" in text  # 2/3 = 66.6% -> 四舍五入 67%


def test_direct_rate_scoped_to_direct_type():
    """JS-20261106-02 回归：直选命中率只统计直选类预测，组选类预测不污染分母。

    构造：福彩3D 直选类 2 条（1 中直选 / 1 未中）+ 福彩3D 组选类 2 条（均中组选）
    + 排列三 直选类 1 条（未中）。直选类已评 = 3（2 福彩3D + 1 排列三），中直选 1，
    直选命中率 = 1/3 = 33.3%；若组选类被错误计入分母，则 1/5 = 20%，据此判定排除生效。
    """
    reviewed = [
        {"lot": "福彩3D", "type": "直选", "hit_type": "直选", "hits": 3},
        {"lot": "福彩3D", "type": "直选", "hit_type": "未中", "hits": 0},
        {"lot": "福彩3D", "type": "组六", "hit_type": "组选", "hits": 3},
        {"lot": "福彩3D", "type": "组三", "hit_type": "组选", "hits": 3},
        {"lot": "排列三", "type": "直选", "hit_type": "未中", "hits": 0},
    ]
    text = build_hit_stats_text(reviewed)
    assert "直选命中率 33.3%" in text


def test_direct_rate_empty_when_no_direct_type():
    """没有直选类预测时显示"暂无直选数据"，而非虚 0（JS-20261106-02）。"""
    reviewed = [
        {"lot": "福彩3D", "type": "组六", "hit_type": "组选", "hits": 3},
        {"lot": "双色球", "hits": 1},
    ]
    text = build_hit_stats_text(reviewed)
    assert "直选命中率 暂无直选数据" in text


# ==================== determine_hit_type（JS-20261106-03 按预测类型分判） ====================
def test_determine_hit_type_direct_exact_match():
    """直选类 + 位置精确匹配(pn==ac) => 直选。"""
    assert determine_hit_type("福彩3D", "直选", "0,5,4", "0,5,4", 3) == "直选"
    assert determine_hit_type("排列三", "直选推荐", "1,2,3", "1,2,3", 3) == "直选"


def test_determine_hit_type_direct_wrong_order_is_not_group():
    """JS-20261106-03 关键回归：直选类 + 三码全中但顺序错(pn!=ac, hits>=3) => 未中，绝不标组选。"""
    # 这是此前被误标为"组选"的隐患：直选注顺序错即未中。
    assert determine_hit_type("福彩3D", "直选", "0,5,4", "4,5,0", 3) == "未中"
    assert determine_hit_type("排列三", "直选推荐", "1,2,3", "3,2,1", 3) == "未中"


def test_determine_hit_type_direct_no_match():
    """直选类 + 三码未全中 => 未中。"""
    assert determine_hit_type("福彩3D", "直选", "0,5,4", "0,5,9", 2) == "未中"


def test_determine_hit_type_group_hit():
    """组选类（组六/组三/组六复式等）+ 三码多重集全中(hits>=3) => 组选（即便位置错）。"""
    assert determine_hit_type("福彩3D", "组六", "0,5,4", "4,5,0", 3) == "组选"
    assert determine_hit_type("排列三", "组三", "1,2,2", "2,2,1", 3) == "组选"
    # 精确位置匹配对组选类同样是组选命中
    assert determine_hit_type("福彩3D", "组六复式(5码)", "0,5,4", "0,5,4", 3) == "组选"


def test_determine_hit_type_group_miss():
    """组选类 + 三码未全中 => 未中。"""
    assert determine_hit_type("福彩3D", "组六", "0,5,4", "0,5,9", 2) == "未中"


def test_determine_hit_type_other_lottery_by_hits():
    """其他彩种（多球种）：任意奖级命中(hits>0)近似组选，否则未中。"""
    assert determine_hit_type("双色球", "复式", "01,02,03", "01,02,09", 2) == "组选"
    assert determine_hit_type("大乐透", "单注", "01,02,03,04,05", "09,08,07,06,05", 1) == "组选"
    assert determine_hit_type("快乐8", "选五", "01,02,03,04,05", "11,12,13,14,15", 0) == "未中"
