# -*- coding: utf-8 -*-
"""蓝球（后区）深度复盘工具的单元测试 —— JS-20261012-08

三块验证：
  1) hit_prob 基线数学正确（双色球 / 大乐透）。
  2) 反向验证（最关键）：喂入纯随机数据，74 项检验必须 0 显著——
     证明 Bonferroni 校正不过松、随机基线没算错（否则会假阳性报「有规律」）。
  3) 锁定真实数据结论：双色球 + 大乐透 真实开奖跑出 0 显著（诚实铁律：后区无预测力）。
"""
import io
import json
import os
import random
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
import tools.lottery_backzone_review as m  # noqa: E402


def _write_random(tmp, name, NB, KB, n, seed):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        b = rng.sample(range(1, NB + 1), KB)
        f = rng.sample(range(1, 34), 6)
        nums = ",".join("%02d" % x for x in f) + "+" + ",".join("%02d" % x for x in b)
        rows.append({"period": i + 1, "time": "2020-01-%02d" % (i % 28 + 1), "nums": nums})
    with io.open(os.path.join(tmp, name + ".json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False)


def test_hit_prob_math():
    from math import comb
    assert abs(m.hit_prob(3, 16, 1) - 3 / 16) < 1e-9
    # 大乐透 3 候选：命中至少 1 of 2 = 1 - C(9,2)/C(12,2)
    exp = 1 - comb(9, 2) / comb(12, 2)
    assert abs(m.hit_prob(3, 12, 2) - exp) < 1e-9
    assert m.hit_prob(0, 16, 1) == 0.0
    assert m.hit_prob(12, 12, 2) == 1.0  # 全选必中


def test_random_data_no_false_positive():
    """纯随机数据 → 必须 0 显著（否则校正过松/基线错，会假阳性报规律）"""
    tmp = tempfile.mkdtemp()
    _write_random(tmp, "双色球", 16, 1, 869, 111)
    _write_random(tmp, "大乐透", 12, 2, 867, 222)
    old = m.LOT_DATA
    m.LOT_DATA = tmp
    try:
        log = []
        m.run_one("双色球", log)
        m.run_one("大乐透", log)
    finally:
        m.LOT_DATA = old
    M = len(log)
    thr = 0.05 / M
    sig = [t for t in log if t[2] < thr]
    assert not sig, "随机数据出现显著项，Bonferroni 过松或基线算错: %r" % sig


def test_real_data_no_significant():
    """锁定当前诚实结论：真实开奖（双色球 869 + 大乐透 867 期）跑出 0 显著"""
    log = []
    m.run_one("双色球", log)
    m.run_one("大乐透", log)
    M = len(log)
    thr = 0.05 / M
    sig = [t for t in log if t[2] < thr]
    assert not sig, "真实数据出现显著项，需复核是否为真规律: %r" % sig
