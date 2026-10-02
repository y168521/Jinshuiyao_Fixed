# -*- coding: utf-8 -*-
"""项⑭ 彩票奖级规则【内容级】校验：先红后绿

证明 check_prize_rules_content 能真实捕获「规则内容滞后但日期新鲜」的假绿 ——
即大乐透 9→7 级回归、奖级缺失、match/prize 字段丢失等，而非只会查 updated_at。
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tools.check_consistency import check_prize_rules_content


def _base_rules():
    """一份结构正确的规则（双色球 6 级 + 大乐透 7 级），应全部通过"""
    return {
        "rules": {
            "双色球": {"judge": "red_blue", "tiers": [
                {"tier": "一等奖", "match": [[6, 1]], "prize": None},
                {"tier": "二等奖", "match": [[6, 0]], "prize": None},
                {"tier": "三等奖", "match": [[5, 1]], "prize": 3000},
                {"tier": "四等奖", "match": [[5, 0]], "prize": 200},
                {"tier": "五等奖", "match": [[4, 1]], "prize": 10},
                {"tier": "六等奖", "match": [[0, 1]], "prize": 5},
            ]},
            "大乐透": {"judge": "red_blue", "tiers": [
                {"tier": "一等奖", "match": [[5, 2]], "prize": None},
                {"tier": "二等奖", "match": [[5, 1]], "prize": None},
                {"tier": "三等奖", "match": [[5, 0], [4, 2]], "prize": 10000},
                {"tier": "四等奖", "match": [[4, 1]], "prize": 300},
                {"tier": "五等奖", "match": [[4, 0], [3, 2]], "prize": 100},
                {"tier": "六等奖", "match": [[3, 1], [2, 2]], "prize": 15},
                {"tier": "七等奖", "match": [[3, 0], [2, 1], [1, 2], [0, 2]], "prize": 5},
            ]},
        }
    }


def test_valid_rules_pass():
    """正确 7 级大乐透必须无报错（绿）"""
    errs = check_prize_rules_content(_base_rules())
    assert errs == [], "正确规则应无报错，实际：%s" % errs


def test_dlt_ninth_prize_is_flagged_red():
    """还原本次真实回归：大乐透含九等奖（旧 9 级遗留）→ 必须能红"""
    rules = _base_rules()
    rules["rules"]["大乐透"]["tiers"].append(
        {"tier": "九等奖", "match": [[2, 0], [1, 1], [0, 1]], "prize": 5})
    errs = check_prize_rules_content(rules)
    assert any("九等奖" in e or "大乐透奖级集合异常" in e for e in errs), \
        "大乐透九等奖回归未被捕获：%s" % errs


def test_dlt_eighth_prize_is_flagged_red():
    """八等奖同样属旧 9 级遗留 → 必须能红"""
    rules = _base_rules()
    rules["rules"]["大乐透"]["tiers"].insert(
        6, {"tier": "八等奖", "match": [[1, 1]], "prize": 5})
    errs = check_prize_rules_content(rules)
    assert any("八等奖" in e for e in errs), "八等奖回归未被捕获：%s" % errs


def test_dlt_tier_count_wrong_flagged_red():
    """大乐透只有 6 级（少一级）→ 集合不等必须能红"""
    rules = _base_rules()
    rules["rules"]["大乐透"]["tiers"].pop()  # 删掉七等奖
    errs = check_prize_rules_content(rules)
    assert any("大乐透奖级集合异常" in e for e in errs), \
        "大乐透 6 级异常未被捕获：%s" % errs


def test_missing_match_field_flagged():
    """red_blue 奖级缺 match 字段 → 结构完整性必须能红"""
    rules = _base_rules()
    del rules["rules"]["双色球"]["tiers"][3]["match"]
    errs = check_prize_rules_content(rules)
    assert any("match" in e for e in errs), "缺 match 未被捕获：%s" % errs


def test_missing_prize_field_flagged():
    """奖级缺 prize 字段 → 必须能红"""
    rules = _base_rules()
    del rules["rules"]["双色球"]["tiers"][3]["prize"]
    errs = check_prize_rules_content(rules)
    assert any("prize" in e for e in errs), "缺 prize 未被捕获：%s" % errs


def test_duplicate_tier_name_flagged():
    """奖级名重复 → 必须能红"""
    rules = _base_rules()
    rules["rules"]["大乐透"]["tiers"][6]["tier"] = "六等奖"
    errs = check_prize_rules_content(rules)
    assert any("重复" in e for e in errs), "奖级重名未被捕获：%s" % errs
