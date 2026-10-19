# -*- coding: utf-8 -*-
"""排列三 / 福彩3D 组选六复式5码 —— 结构性正确性测试（JS-20261020）。

背景（质量退化排查）：
    复式"5码=10注=20元"此前只存在于 ``format_gen.py`` 的**注释**里，
    系统从未真正展开或校验过组合 ⇒ 是否覆盖全部组六、有无重复、
    有无混入组三/豹子全靠人眼。同时存在三处口径冲突：
        format_gen.pool_size 默认 6 / _make_fushi 默认 4 /
        budget_controller digit_count 4 / play_plans digit_count 5
    以及 ``execute_blood_change`` 硬编码返回 5 个号码（无视入池大小）。

本文件把「完整覆盖、无重复、符合组选六规则（排除组三/豹子）」变成可断言的代码。
 reversal（撤销验证）见 TestReverseVerification：破坏真源后本文件必须转红。
"""
from __future__ import annotations

import os
import random
import sys
from itertools import combinations

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engines.group6_utils import (  # noqa: E402
    DEFAULT_DIGIT_COUNT,
    expand_group6,
    group6_bet_count,
    complete_pool,
    normalize_pool,
    validate_group6_fushi,
    coverage_report,
)
from engines.risk_controller import StrategyCorrector  # noqa: E402

LOTS = ["福彩3D", "排列三"]


# ────────────────────────────────────────────────────────────
# 工具
# ────────────────────────────────────────────────────────────
def make_history(n=40, seed=7):
    """合成历史开奖（nums + period），用于驱动选号/换血逻辑。"""
    rng = random.Random(seed)
    return [{"nums": ",".join(str(rng.randint(0, 9)) for _ in range(3)),
             "period": 2026000 + i}
            for i in range(n)]


def parse_fushi(s):
    """复式字符串 → 数字列表（兼容 "01,02,03" 与 "[1,2,3]"）。"""
    body = s.strip()
    if body.startswith("[") and body.endswith("]"):
        body = body[1:-1]
    return [int(x) for x in body.replace("，", ",").split(",") if x.strip() != ""]


def assert_valid_group6_fushi(nums, expected_size=DEFAULT_DIGIT_COUNT):
    """核心断言：完整覆盖 / 无重复 / 排除组三与豹子号。"""
    ok, issues = validate_group6_fushi(nums, expected_size)
    assert ok, "组六复式校验失败: %s（号码=%s）" % (issues, nums)

    bets = expand_group6(nums)
    # 1) 完整覆盖：C(n,3) 注，不多不少
    assert len(bets) == group6_bet_count(expected_size), (
        "展开注数 %d != C(%d,3)=%d" % (len(bets), expected_size,
                                       group6_bet_count(expected_size)))
    # 2) 无重复
    assert len(set(bets)) == len(bets), "展开结果存在重复注"
    # 3) 每注 3 数互异 ⇒ 排除组三（2同1异）与豹子号（3同）
    for b in bets:
        assert len(set(b)) == 3, "注 %s 含重复数字，非组六" % (b,)
    # 4) 与真值集合逐一比对（防止"恰好数量对但内容错"）
    assert set(bets) == set(combinations(sorted(set(nums)), 3))
    return bets


# ════════════════════════════════════════════════════════════
# 一、group6_utils 真源本身（结构性正确性）
# ════════════════════════════════════════════════════════════
class TestGroup6Utils:
    def test_bet_count_formula(self):
        assert group6_bet_count(3) == 1
        assert group6_bet_count(4) == 4
        assert group6_bet_count(5) == 10
        assert group6_bet_count(6) == 20
        assert group6_bet_count(2) == 0
        assert group6_bet_count(0) == 0

    def test_default_digit_count_matches_play_plans(self):
        """默认码数必须与 gui/play_plans.py 的 5码/20元 口径一致。"""
        assert DEFAULT_DIGIT_COUNT == 5
        assert group6_bet_count(DEFAULT_DIGIT_COUNT) * 2 == 20  # 2元/注 → 20元

    def test_expand_five_digits_yields_ten_bets(self):
        bets = expand_group6([0, 1, 2, 3, 4])
        assert len(bets) == 10
        assert len(set(bets)) == 10
        assert all(len(set(b)) == 3 for b in bets)

    def test_expand_excludes_group3_and_baozi(self):
        """展开结果不得与任何组三/豹子号形态相交。"""
        bets = set(expand_group6([1, 3, 5, 7, 9]))
        for a in range(10):
            for b in range(10):
                if a == b:
                    continue
                assert (a, a, b) not in bets, "混入组三 %s" % ((a, a, b),)
        for a in range(10):
            assert (a, a, a) not in bets, "混入豹子号 %s" % ((a, a, a),)

    def test_normalize_pool_dedups_and_sorts(self):
        assert normalize_pool([5, 3, 3, 1, None, "x", 12, -1]) == [1, 3, 5]

    def test_complete_pool_never_shrinks(self):
        """补位只增不减：已有 6 码要求补到 5 → 仍返回 6 个（不削减）。"""
        assert complete_pool([0, 1, 2, 3, 4, 5], 5) == [0, 1, 2, 3, 4, 5]
        assert complete_pool([7], 5) == sorted(set([7]) | {0, 1, 2, 3})

    def test_complete_pool_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            complete_pool([1], 2)
        with pytest.raises(ValueError):
            complete_pool([1], 9)

    def test_validate_detects_wrong_size_and_dup(self):
        ok, issues = validate_group6_fushi([1, 2, 3])
        assert not ok and issues, "3码当作5码复式必须被判失败"

        ok2, _ = validate_group6_fushi([1, 1, 2, 3, 4])  # 重复 → 去重后仅4码
        assert not ok2, "含重复数字的复式必须被判失败"

    def test_coverage_report_only_counts_group6_draws(self):
        """组三/豹子开奖不计入分母（本就不在组六覆盖范围）。"""
        draws = [[1, 2, 3], [1, 1, 2], [4, 4, 4], [2, 5, 9]]
        rep = coverage_report([1, 2, 3, 4, 5], draws)
        assert rep["group6_draws"] == 2      # 只有 [1,2,3] 与 [2,5,9]
        assert rep["hit_draws"] == 1        # [1,2,3] 命中
        assert rep["bet_count"] == 10
        assert abs(rep["hit_rate"] - 0.5) < 1e-9


# ════════════════════════════════════════════════════════════
# 二、换血必须保持入池大小（历史缺陷：硬编码返回 5 个）
# ════════════════════════════════════════════════════════════
class TestBloodChangeKeepsPoolSize:
    @pytest.mark.parametrize("size", [4, 5, 6])
    def test_blood_change_preserves_size(self, size):
        c = StrategyCorrector()
        hist = make_history()
        pool = list(range(size))
        new_pool = c.execute_blood_change(pool, hist)
        assert len(new_pool) == size, (
            "换血破坏了码池大小：入池 %d 码 → 返回 %d 码（%s）"
            % (size, len(new_pool), new_pool))

    def test_blood_change_output_is_valid_group6(self):
        c = StrategyCorrector()
        new_pool = c.execute_blood_change([0, 1, 2, 3, 4], make_history())
        ok, issues = validate_group6_fushi(new_pool, 5)
        assert ok, "换血后的码池不是合法5码组六复式: %s" % issues

    def test_blood_change_returns_unchanged_when_history_short(self):
        c = StrategyCorrector()
        pool = [2, 4, 6]
        assert c.execute_blood_change(pool, []) == pool
        assert c.execute_blood_change(pool, None) == pool


# ════════════════════════════════════════════════════════════
# 三、生成主路径：复式必须是 5 码 / 10 注 / 无重复 / 无组三豹子
# ════════════════════════════════════════════════════════════
class TestGeneratedFushiStructure:
    @staticmethod
    def _build(lot, seed, play_plan=None):
        from engines.format_gen import FormatGen
        rng = random.Random(seed)
        hot = {d: rng.uniform(0.1, 1.0) for d in range(10)}
        kill = {rng.randint(0, 9) for _ in range(2)}
        return FormatGen(lot=lot, kill=kill, hot=hot, history=make_history(),
                         play_plan=play_plan, hot_window=10)

    @pytest.mark.parametrize("lot", LOTS)
    def test_with_explicit_five_digit_plan(self, lot):
        """显式 digit_count=5 时必须 30/30 产出合法 5 码复式。"""
        plan = [{"type": "复式", "config": {"digit_count": 5}, "count": 1}]
        for seed in range(30):
            fg = self._build(lot, seed, plan)
            res = fg.gen()
            fushi_list = res.get("复式") or []
            assert fushi_list, "seed=%s 未产出复式" % seed
            nums = parse_fushi(fushi_list[0])
            assert_valid_group6_fushi(nums, 5)

    @pytest.mark.parametrize("lot", LOTS)
    def test_default_pool_size_is_five(self, lot):
        """无 play_plan 时默认口径必须落到 5 码（而非旧的 6 码 / 4 码）。"""
        fg = self._build(lot, 1, None)
        assert fg.pool_size == DEFAULT_DIGIT_COUNT, (
            "默认池口径应为 %d，实际 %d" % (DEFAULT_DIGIT_COUNT, fg.pool_size))

    @pytest.mark.parametrize("lot", LOTS)
    def test_hot_freq_path_fushi_is_five_digits(self, lot):
        """生产主路径（prediction_service 走 _gen_3d_hot_freq，不经 gen()）必须 5 码 10 注。"""
        for seed in range(10):
            fg = self._build(lot, seed, None)
            res = fg._gen_3d_hot_freq()
            fushi_list = res.get("复式") or []
            assert fushi_list, "seed=%s 未产出复式" % seed
            assert_valid_group6_fushi(parse_fushi(fushi_list[0]), 5)

    @pytest.mark.parametrize("lot", LOTS)
    def test_blood_change_path_stays_five_digits(self, lot):
        """触发换血后，复式仍必须是合法 5 码（换血只换内容、不改码数）。"""
        from engines.risk_controller import get_corrector
        corrector = get_corrector()
        backup = corrector.state.get("per_lot", {}).get(lot)
        try:
            corrector.state.setdefault("per_lot", {})[lot] = {
                "consecutive_zeros": 0, "pool_zeros": 99,
                "last_pool": [], "recent_forms": []}
            assert corrector.need_blood_change(lot), "换血条件未触发，测试前提不成立"
            for seed in range(10):
                fg = self._build(lot, seed, None)
                res = fg._gen_3d_hot_freq()
                assert_valid_group6_fushi(parse_fushi(res["复式"][0]), 5)
        finally:
            per_lot = corrector.state.setdefault("per_lot", {})
            if backup is None:
                per_lot.pop(lot, None)
            else:
                per_lot[lot] = backup

    @pytest.mark.parametrize("lot", LOTS)
    def test_make_fushi_default_digit_count(self, lot):
        """``_make_fushi({})`` 缺省配置必须产出 5 码而非 4 码。"""
        fg = self._build(lot, 1, None)
        s = fg._make_fushi({})
        nums = parse_fushi(s)
        assert len(set(nums)) == 5, "_make_fushi 默认码数应为5，实际 %d（%s）" % (len(set(nums)), s)
        assert_valid_group6_fushi(nums, 5)

    @pytest.mark.parametrize("lot", LOTS)
    def test_make_fushi_never_emits_duplicate(self, lot):
        """即使底层选号返回重复，复式字符串也必须去重。"""
        fg = self._build(lot, 2, None)
        for _ in range(20):
            nums = parse_fushi(fg._make_fushi({}))
            assert len(nums) == len(set(nums)), "复式串含重复号码: %s" % nums

    def test_budget_plan_digit_count_matches_play_plans(self):
        """预算控制器的 3D/排列三 复式口径必须与 play_plans 一致（5码/20元）。"""
        from controllers.budget_controller import BudgetControllerV2
        from gui.play_plans import PLAY_PLANS
        dc = None
        for p in PLAY_PLANS.get("福彩3D", []):
            if p.get("type") == "复式" and isinstance(p.get("config"), dict):
                dc = p["config"].get("digit_count")
                break
        assert dc is not None, "play_plans 未定义 3D 复式 digit_count"

        pm, _total = BudgetControllerV2(None).allocate(["福彩3D"])
        cfg = pm.get("福彩3D") or []
        got = None
        for p in cfg:
            if isinstance(p, dict) and p.get("type") == "复式":
                got = (p.get("config") or {}).get("digit_count")
                assert got == dc, (
                    "口径冲突：budget digit_count=%s，play_plans=%s" % (got, dc))
                # 成本必须等于 C(n,3) 注 × 2 元
                assert p.get("cost") == group6_bet_count(dc) * 2, (
                    "成本与码数不符：%s 元 ≠ C(%s,3)×2=%s 元"
                    % (p.get("cost"), dc, group6_bet_count(dc) * 2))
                break
        assert got is not None, "预算侧未定义 3D 复式"


# ════════════════════════════════════════════════════════════
# 三·补、开奖形态三态分类（豹子号不得被误记为组六）
# ════════════════════════════════════════════════════════════
class TestDrawFormClassification:
    """形态分类污染 recent_forms → 会连带判错「连续组三→组六对冲」。"""

    @staticmethod
    def _corrector():
        c = StrategyCorrector()
        # 阻断落盘：避免测试污染真实 risk_state.json
        c.save = lambda: None
        return c

    @pytest.mark.parametrize("nums,expected", [
        ([1, 1, 2], "组三"),
        ([1, 2, 3], "组六"),
        ([7, 7, 7], "豹子"),
    ])
    def test_form_is_three_state(self, nums, expected):
        c = self._corrector()
        c.state = {"per_lot": {}}
        c.update_after_review("福彩3D", [0, 1, 2, 3, 4], nums, 1)
        forms = c.state["per_lot"]["福彩3D"]["recent_forms"]
        assert forms == [expected], "形态应为 %s，实际 %s" % (expected, forms)

    def test_baozi_must_not_trigger_group6_hedge(self):
        """连续两期豹子 ⇒ 不是「连续组三」，不得触发强制组六对冲。"""
        c = self._corrector()
        c.state = {"per_lot": {}}
        for _ in range(2):
            c.update_after_review("福彩3D", [0, 1, 2, 3, 4], [7, 7, 7], 0)
        assert c.state["per_lot"]["福彩3D"]["recent_forms"] == ["豹子", "豹子"]
        assert not c.should_force_group6("福彩3D"), "豹子期被误当成组三，触发了错误对冲"
        assert c.get_group3_weight_multiplier("福彩3D") == 1.0

    def test_real_group3_still_triggers_hedge(self):
        """回归保护：真·连续组三仍然触发对冲（不能因修豹子而误伤）。"""
        c = self._corrector()
        c.state = {"per_lot": {}}
        for _ in range(2):
            c.update_after_review("福彩3D", [0, 1, 2, 3, 4], [5, 5, 8], 0)
        assert c.should_force_group6("福彩3D"), "连续组三应触发组六对冲"


# ════════════════════════════════════════════════════════════
# 四、撤销验证：破坏真源后上述断言必须转红（否则是假闸）
# ════════════════════════════════════════════════════════════
class TestReverseVerification:
    def _load_fresh(self, path, name):
        """用 exec 沙箱加载模块，绕开 pyc 时间戳 staleness。"""
        import types
        mod = types.ModuleType(name)
        mod.__file__ = path
        sys.modules[name] = mod
        try:
            with open(path, "r", encoding="utf-8") as f:
                exec(compile(f.read(), path, "exec"), mod.__dict__)
        finally:
            sys.modules.pop(name, None)
        return mod

    def _break_and_restore(self, path, old, new, check_fn):
        """临时破坏源码 → 断言必须变红 → 原样恢复并 md5 校验。"""
        import hashlib
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        md5_before = hashlib.md5(src.encode("utf-8")).hexdigest()
        assert old in src, "撤销验证未命中目标代码（可能已被重构）: %s" % old
        broken = src.replace(old, new, 1)
        assert broken != src
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(broken)
            mod = self._load_fresh(path, "_rv_%s" % hashlib.md5(new.encode()).hexdigest()[:6])
            failed = False
            try:
                check_fn(mod)
            except AssertionError:
                failed = True
            assert failed, "撤销后断言仍为绿 ⇒ 这是假闸，测试没真正守住"
        finally:
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            with open(path, "r", encoding="utf-8") as f:
                assert hashlib.md5(f.read().encode("utf-8")).hexdigest() == md5_before, \
                    "源码未完整恢复"
        return True

    def test_blood_change_hardcoded_five_is_detected(self):
        """把 execute_blood_change 改回硬编码 5 码 → 4 码入池断言必须变红。"""
        path = os.path.join(ROOT, "engines", "risk_controller.py")

        def check(mod):
            out = mod.StrategyCorrector().execute_blood_change([0, 1, 2, 3], make_history())
            assert len(out) == 4, "入池4码应返回4码，实际 %d（%s）" % (len(out), out)

        assert self._break_and_restore(
            path,
            "        target = len(normalize_pool(current_pool))",
            "        target = 5  # 撤销验证：改回硬编码",
            check)
        # 恢复后必须重新变绿
        mod2 = self._load_fresh(path, "_rv_risk_ok")
        assert len(mod2.StrategyCorrector().execute_blood_change(
            [0, 1, 2, 3], make_history())) == 4

    def test_baozi_misclassification_is_detected(self):
        """把形态判定改回二态（distinct 恒为 2）→ 豹子断言必须变红。"""
        path = os.path.join(ROOT, "engines", "risk_controller.py")

        def check(mod):
            c = mod.StrategyCorrector()
            c.save = lambda: None
            c.state = {"per_lot": {}}
            c.update_after_review("福彩3D", [0, 1, 2, 3, 4], [7, 7, 7], 1)
            forms = c.state["per_lot"]["福彩3D"]["recent_forms"]
            assert forms == ["豹子"], "豹子被判成 %s" % forms

        assert self._break_and_restore(
            path,
            "            distinct = len(set(actual_nums))",
            "            distinct = 2  # 撤销验证：破坏三态判定",
            check)

    def test_make_fushi_default_four_is_detected(self):
        """把 _make_fushi 默认码数改回 4 → 5 码断言必须变红。"""
        path = os.path.join(ROOT, "engines", "format_gen.py")

        def check(mod):
            # 必须用沙箱模块里的类，否则测的是磁盘上未破坏的旧模块
            rng = random.Random(3)
            hot = {d: rng.uniform(0.1, 1.0) for d in range(10)}
            fg = mod.FormatGen(lot="福彩3D", kill={1, 8}, hot=hot,
                               history=make_history(), hot_window=10)
            nums = parse_fushi(fg._make_fushi({}))
            assert len(set(nums)) == 5, "默认应为5码，实际 %d（%s）" % (len(set(nums)), nums)

        assert self._break_and_restore(
            path,
            'digit_count = cfg.get("digit_count", DEFAULT_DIGIT_COUNT)',
            'digit_count = cfg.get("digit_count", 4)  # 撤销验证：改回旧默认',
            check)
