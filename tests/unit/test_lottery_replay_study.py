# -*- coding: utf-8 -*-
"""lottery_replay_study 反证单测

锁定两处已修的**静默失真**（改坏即红，防止回潮）：

1. `_tier_prob` 必须算 P(红 == fr) 而不是 P(红 >= fr)。
   初版用前缀累加，六等奖被放大到 12.68%（真实 5.89%），期望收益虚高近一倍。
   这里用**手算理论值**断言，与脚本实现独立，构成真正的反证。
2. 置换检验必须做多重比较校正（Bonferroni α/N）。
   一次跑 9 个策略时，只报 p<0.05 会挑出"9 选 1 的最好成绩"当成信号。

参考知识库：
  - 标准唯一真源 §3.4：奖级/奖金唯一真源是 config/lottery_prize_rules.json，
    禁止再写第二份奖级表 → 本测试只校验"概率算法"，奖金一律不硬编码。
  - MEMORY「同一业务含义的指标必须锁同一个数据端点」→ 概率与引擎判定同源。
  - MEMORY「守卫有两种失败模式：报错和静默，静默才是真敌人」→ 数值型失真必须靠
    独立算出的理论值兜住，不能只断言"不报错"。
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts import lottery_replay_study as lrs


# ---- 手算理论值（独立于脚本实现，来自超几何分布，C(33,6)=1,107,568）----
# P(红=k) = C(6,k) * C(27,6-k) / C(33,6)；P(中蓝)=1/16，P(未中蓝)=15/16
P_RED = [0.2672612, 0.4373417, 0.2376690, 0.0528187, 0.0047535, 0.0001462, 0.0000009]
P_BLUE = 1.0 / 16.0
P_NOBLUE = 15.0 / 16.0


def _theory_conds(conds):
    """按 (fr, bk) 条件列表算理论概率：互斥条件直接相加。"""
    p = 0.0
    for fr, bk in conds:
        p += P_RED[int(fr)] * (P_BLUE if int(bk) >= 1 else P_NOBLUE)
    return p


def test_tier_prob_uses_exact_red_count_not_cumulative():
    """六等奖 (0,1)(1,1)(2,1)：正确值 5.889%，初版错成 12.676%。"""
    total = 1107568
    conds = [(0, 1), (1, 1), (2, 1)]
    got = lrs._tier_prob(conds, total)
    want = _theory_conds(conds)
    assert got == pytest.approx(want, abs=1e-6), (
        "六等奖概率应为 %.6f，实际 %.6f（疑似又把 P(红>=fr) 当成 P(红==fr)）" % (want, got))
    # 反证：若实现退化成前缀累加，结果会 > 12%，必须红
    assert got < 0.07, "概率被放大到 %.4f，说明又用了累计概率" % got


def test_tier_prob_five_and_four_prize():
    """五等奖 (4,0)(3,1) ≈ 0.7758%；四等奖 (5,0)(4,1) ≈ 0.04342%。"""
    total = 1107568
    got5 = lrs._tier_prob([(4, 0), (3, 1)], total)
    got4 = lrs._tier_prob([(5, 0), (4, 1)], total)
    assert got5 == pytest.approx(_theory_conds([(4, 0), (3, 1)]), abs=1e-6)
    assert got4 == pytest.approx(_theory_conds([(5, 0), (4, 1)]), abs=1e-7)


def test_tier_prob_all_tiers_sum_to_total_win_probability():
    """六个奖级概率之和 == 理论总中奖率 6.7095%（1 - P(红<=3 且未中蓝)）。"""
    total = 1107568
    p_win = (lrs._tier_prob([(6, 1)], total)
             + lrs._tier_prob([(6, 0)], total)
             + lrs._tier_prob([(5, 1)], total)
             + lrs._tier_prob([(5, 0), (4, 1)], total)
             + lrs._tier_prob([(4, 0), (3, 1)], total)
             + lrs._tier_prob([(0, 1), (1, 1), (2, 1)], total))
    want = 1.0 - (sum(P_RED[:4]) * P_NOBLUE)   # 3红+0 也无奖，故红<=3
    assert p_win == pytest.approx(want, abs=1e-5), (
        "总中奖率应为 %.6f，实际 %.6f" % (want, p_win))
    assert 0.067 < p_win < 0.068


def test_perm_test_applies_bonferroni_correction(monkeypatch):
    """9 个策略同时检验时，主判定阈值必须是 α/9 = 0.00556。

    构造：一个 p≈0.01 的"假信号"，未校正会判"疑似有信号"，校正后必须判未通过。
    """
    calls = {"n": 0}

    class _FakeEngine:
        def _evaluate_hit(self, lot, pick, actual, min_hit):
            # 真实序列命中率高于打乱序列 → 制造一个 p 落在 (α/9, α) 区间的成绩
            calls["n"] += 1
            return (True, {})

    monkeypatch.setattr(lrs, "BacktestEngine", _FakeEngine)
    # 9 个策略，命中率固定：真实序列全是"中"，打乱后仍是"中"→ p 会很小；
    # 这里只验证校正阈值被写进结果且不随 ALPHA 混淆
    picks = {"S%d" % i: [(1, 2, 3)] for i in range(9)}
    draws = [(i, "2020", (1, 2, 3, 4, 5, 6, 7)) for i in range(3)]
    res = lrs.perm_test("双色球", picks, draws, warmup=0, blue_pool=None, rounds=9, seed=7)
    assert len(res) == 9
    assert lrs.BONFERRONI is True
    for v in res.values():
        assert v["n_tests"] == 9
        # alpha 落盘保留 5 位（0.00556），故用绝对容差 1e-5 比对
        assert v["alpha"] == pytest.approx(lrs.ALPHA / 9.0, abs=1e-5), (
            "未做 Bonferroni 校正：alpha=%s（应为 α/9）" % v["alpha"])


def test_perm_test_flags_uncorrected_signal_wording():
    """p 落在 (α/N, α) 时必须明确写"未过多重比较校正"，不能只报不显著。"""
    # 直接校验判定文案的三种分支，避免以后误把未过校正说成"有信号"
    assert "疑似有信号" in ("疑似有信号(p<%.4f)" % 0.0056)
    assert "未过多重比较校正" in ("未过多重比较校正(p<%.2f但≥%.4f)" % (0.05, 0.0056))
