# -*- coding: utf-8 -*-
"""lottery_cooccurrence_review.py 单测 —— JS-20261012-09

双向验证：
  1) 纯随机数据必须几乎不出现显著（反向验证 Bonferroni 不过松、口径无误）。
  2) 真实全彩种数据有效家族显著数 = 0（锁死诚实结论）。
  3) pair_prob 数学正确（set 型 C(k,2)/C(N,2)；repl 型两公式）。
  4) 边际均匀性门限能识别非均匀数据源（数据异常闸门）。
"""
from __future__ import annotations

import math
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))
import lottery_cooccurrence_review as M  # noqa: E402


def gen_rows(N, k, kind, n, seed):
    """生成合成开奖数据（纯随机，作为共现检验的零分布基线）"""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        if kind == "set":
            nums = rng.sample(range(1, N + 1), k)
        else:  # repl：位置独立放回，数字 0..9
            nums = [rng.randint(0, 9) for _ in range(k)]
        rows.append((f"{i:05d}", f"2026-{i:03d}", nums, []))
    return rows


def sig_count(pairs):
    """按 Bonferroni(0.05 / 总对数) 统计显著对"""
    T = len(pairs)
    bonf = 0.05 / T if T else 0.05
    return sum(1 for x in pairs if x["p"] < bonf)


def test_pair_prob_math():
    # set 型：双色球前区 6/33，两号共现 = C(6,2)/C(33,2) = 15/528
    assert abs(M.pair_prob(33, 6, "set", 1, 2) - 15 / 528) < 1e-12
    # set 型不可能重复
    assert M.pair_prob(33, 6, "set", 5, 5) == 0.0
    # set 型单号无共现
    assert M.pair_prob(16, 1, "set", 1, 2) == 0.0
    # repl 型异号（3D 3 位置）：1 - 2·0.9^3 + 0.8^3 = 0.054
    assert abs(M.pair_prob(10, 3, "repl", 1, 2) - (1 - 2 * 0.9 ** 3 + 0.8 ** 3)) < 1e-12
    # repl 型同号重复（3D）：1 - 0.9^3 - 3·0.1·0.9^2 = 0.028
    assert abs(M.pair_prob(10, 3, "repl", 1, 1) - (1 - 0.9 ** 3 - 3 * 0.1 * 0.9 ** 2)) < 1e-12
    # repl 型异号（七星彩 7 位置）：1 - 2·0.9^7 + 0.8^7 ≈ 0.2531
    assert abs(M.pair_prob(10, 7, "repl", 1, 2) - (1 - 2 * 0.9 ** 7 + 0.8 ** 7)) < 1e-12


def test_random_data_no_false_positive():
    # 反向验证：纯随机数据不应出现系统性假阳性（Bonferroni 不过松）。
    # 注：Bonferroni 校准使零分布下期望假阳性≈0.05，故允许 ≤1 个偶发波动；
    # 若口径/公式错误会出现几十条显著对，测试会 loudly 失败。
    set_rows = gen_rows(33, 6, "set", 600, seed=20261012)
    set_pairs = M.cooccurrence_for_field(set_rows, "front", 33, 6, "set")
    assert sig_count(set_pairs) <= 1, f"set 型随机数据出现 {sig_count(set_pairs)} 显著对（应≤1）"

    repl_rows = gen_rows(10, 3, "repl", 600, seed=20261013)
    repl_pairs = M.cooccurrence_for_field(repl_rows, "front", 10, 3, "repl")
    assert sig_count(repl_pairs) <= 1, f"repl 型随机数据出现 {sig_count(repl_pairs)} 显著对（应≤1）"


def test_uniformity_detects_anomaly():
    # 构造「数字 1 显著偏多」的非均匀数据（仿七星彩异常），边际均匀性闸门须判不均
    rng = random.Random(7)
    rows = []
    for i in range(400):
        nums = []
        for _ in range(7):  # 7 位置，数字 1 权重 0.2，其余 0.0889
            if rng.random() < 0.2:
                nums.append(1)
            else:
                nums.append(rng.randint(2, 9))
        rows.append((f"{i:05d}", "x", nums, []))
    uni = M.field_uniformity(rows, "front", 10, "repl")
    assert uni["ok"] is False, f"非均匀数据未被识别（chi/df={uni['chi_per_df']:.2f}）"


def test_real_data_no_significant():
    # 锁死诚实结论：真实全彩种有效家族显著数 = 0（七星彩 已因数据异常排除）
    all_valid = []
    for name in M.SPEC.keys():
        r = M.run_one(name)
        assert r is not None, f"{name} 无数据"
        for x in r["pairs"]:
            if x["uniformity_ok"]:
                all_valid.append(x)
    T = len(all_valid)
    bonf = 0.05 / T
    sig = [x for x in all_valid if x["p"] < bonf]
    assert len(sig) == 0, f"真实数据出现 {len(sig)} 对显著共现（应=0）"
    # 同时确认七星彩被排除（数据异常）
    qxc = M.run_one("七星彩")
    assert all(not s["uniformity"]["ok"] for s in qxc["summary"].values()), "七星彩 未被标记数据异常"
