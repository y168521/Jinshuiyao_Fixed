# -*- coding: utf-8 -*-
"""金水谣足彩核心域单元测试

覆盖模块：
  - jinshuiyao.models.base_model.BaseModel (抽象基类 + 输出校验)
  - jinshuiyao.models.poisson_model.PoissonModel (泊松进球模型)
  - jinshuiyao.models.poisson_model.SimpleEnsemble (集成模型)
  - jinshuiyao.risk_controller.JinshuiyaoRiskController (风控层)
  - jinshuiyao.combo_optimizer.ComboOptimizer (2串1优化)
  - jinshuiyao.schemas (数据结构)

设计原则：
  - 每条用例必有与预期结果直接对应的硬断言
  - 绝不使用 try/except+pass 吞掉核心失败
  - 断言信息写清「期望 vs 实际」
  - 覆盖：正常值 / 边界值 / 异常值 / 空值
"""
import unittest
import sys
import os

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from jinshuiyao.models.base_model import BaseModel
from jinshuiyao.models.poisson_model import PoissonModel, SimpleEnsemble
from jinshuiyao.risk_controller import JinshuiyaoRiskController
from jinshuiyao.combo_optimizer import ComboOptimizer, ComboLeg, ComboTicket
from jinshuiyao.schemas import MatchInfo, OddsData, Recommendation, BacktestRecord, BacktestSummary
from jinshuiyao.config import (
    POISSON_MAX_GOALS, POISSON_MIN_LAMBDA,
    DAILY_LOSS_LIMIT, MAX_DAILY_BETS, KELLY_MULTIPLIER, MAX_STAKE_RATIO,
)


# ===================================================================
# 1. BaseModel 测试
# ===================================================================

class _ConcreteModel(BaseModel):
    """可实例化的最小具体模型（仅用于测试BaseModel具体方法）"""

    def predict_proba(self, features):
        return {'win': 0.45, 'draw': 0.30, 'lose': 0.25}


class TestBaseModel(unittest.TestCase):
    """BaseModel 抽象基类与输出校验测试"""

    def test_base_cannot_instantiate(self):
        """验证抽象基类不能直接实例化"""
        with self.assertRaises(TypeError):
            BaseModel()

    def test_validate_output_valid(self):
        """正常值：胜平负概率和为1时通过校验"""
        model = _ConcreteModel()
        prob = {'win': 0.45, 'draw': 0.30, 'lose': 0.25}
        self.assertTrue(
            model.validate_output(prob),
            f"期望概率和=1.0通过校验，实际返回False，概率={prob}"
        )

    def test_validate_output_missing_key(self):
        """异常值：缺少必要key时返回False"""
        model = _ConcreteModel()
        prob = {'win': 0.5, 'draw': 0.5}  # 缺 lose
        self.assertFalse(
            model.validate_output(prob),
            f"期望缺少key时返回False，实际返回True，概率={prob}"
        )

    def test_validate_output_non_numeric(self):
        """异常值：概率不是数字时返回False"""
        model = _ConcreteModel()
        prob = {'win': 'high', 'draw': 0.3, 'lose': 0.2}
        self.assertFalse(
            model.validate_output(prob),
            f"期望非数字时返回False，实际返回True，概率={prob}"
        )

    def test_validate_output_sum_too_far(self):
        """边界值：概率和偏离1太多时返回False"""
        model = _ConcreteModel()
        prob = {'win': 0.9, 'draw': 0.9, 'lose': 0.9}  # 和为2.7
        self.assertFalse(
            model.validate_output(prob),
            f"期望概率和偏差>0.15时返回False，实际返回True，和={sum(prob.values())}"
        )

    def test_validate_output_sum_near_one(self):
        """边界值：概率和在容差范围内时通过"""
        model = _ConcreteModel()
        prob = {'win': 0.34, 'draw': 0.33, 'lose': 0.33}  # 和为1.0
        self.assertTrue(
            model.validate_output(prob),
            f"期望概率和接近1时通过，实际返回False，和={sum(prob.values())}"
        )

    def test_concrete_model_name(self):
        """验证模型名称属性"""
        model = _ConcreteModel(name="test_model")
        self.assertEqual(
            model.name, "test_model",
            f"期望name='test_model'，实际='{model.name}'"
        )


# ===================================================================
# 2. PoissonModel 测试
# ===================================================================

class TestPoissonModel(unittest.TestCase):
    """泊松进球模型测试"""

    def test_model_instantiates(self):
        """验证模型可以正常实例化"""
        model = PoissonModel()
        self.assertEqual(
            model.name, "poisson",
            f"期望name='poisson'，实际='{model.name}'"
        )
        self.assertEqual(
            model.max_goals, POISSON_MAX_GOALS,
            f"期望max_goals={POISSON_MAX_GOALS}，实际={model.max_goals}"
        )

    def test_custom_max_goals(self):
        """验证可以自定义max_goals"""
        model = PoissonModel(max_goals=5)
        self.assertEqual(
            model.max_goals, 5,
            f"期望max_goals=5，实际={model.max_goals}"
        )

    def test_predict_returns_all_keys(self):
        """验证predict_proba返回胜平负三个key"""
        model = PoissonModel()
        features = {'home_goals_avg': 1.5, 'away_goals_avg': 1.2}
        result = model.predict_proba(features)
        for key in ['win', 'draw', 'lose']:
            self.assertIn(
                key, result,
                f"期望结果包含key='{key}'，实际keys={list(result.keys())}"
            )

    def test_predict_probability_sum(self):
        """验证概率和约等于1"""
        model = PoissonModel()
        features = {'home_goals_avg': 1.5, 'away_goals_avg': 1.2}
        result = model.predict_proba(features)
        total = sum(result.values())
        self.assertAlmostEqual(
            total, 1.0, places=5,
            msg=f"期望概率和=1.0，实际={total}"
        )

    def test_predict_validates_output(self):
        """验证预测结果能通过BaseModel.validate_output"""
        model = PoissonModel()
        features = {'home_goals_avg': 1.5, 'away_goals_avg': 1.2}
        result = model.predict_proba(features)
        self.assertTrue(
            model.validate_output(result),
            f"预测结果未通过输出校验，结果={result}"
        )

    def test_home_advantage(self):
        """验证主队进球率更高时主胜概率>客胜概率"""
        model = PoissonModel()
        features = {'home_goals_avg': 2.5, 'away_goals_avg': 0.8}
        result = model.predict_proba(features)
        self.assertGreater(
            result['win'], result['lose'],
            f"期望主胜({result['win']}) > 客胜({result['lose']})，当主队进球率远高时"
        )

    def test_lambda_floor_applied(self):
        """验证lambda下限生效（防止log(0)）"""
        model = PoissonModel()
        features = {'home_goals_avg': 0.0, 'away_goals_avg': 0.0}
        try:
            result = model.predict_proba(features)
        except Exception as e:
            self.fail(f"lambda为0时不应报错，实际抛出: {type(e).__name__}: {e}")
        self.assertIsInstance(result, dict, f"期望返回dict，实际={type(result)}")

    def test_even_teams(self):
        """验证实力接近时平局概率合理"""
        model = PoissonModel()
        features = {'home_goals_avg': 1.3, 'away_goals_avg': 1.3}
        result = model.predict_proba(features)
        self.assertGreater(
            result['draw'], 0.2,
            f"实力接近时期望平局概率>0.2，实际={result['draw']}"
        )

    def test_missing_features_uses_defaults(self):
        """验证缺少特征时使用默认值不崩溃"""
        model = PoissonModel()
        features = {}
        try:
            result = model.predict_proba(features)
        except Exception as e:
            self.fail(f"缺少特征时不应崩溃，实际抛出: {type(e).__name__}: {e}")
        self.assertIn('win', result, f"期望返回含'win'，实际={result}")


# ===================================================================
# 3. SimpleEnsemble 测试
# ===================================================================

class TestSimpleEnsemble(unittest.TestCase):
    """简单加权集成模型测试"""

    def test_default_uses_poisson(self):
        """验证默认配置下集成模型退化到纯泊松"""
        ensemble = SimpleEnsemble()
        self.assertEqual(
            len(ensemble.models), 1,
            f"期望默认有1个模型，实际={len(ensemble.models)}"
        )
        self.assertEqual(
            ensemble.models[0].name, "poisson",
            f"期望默认模型是poisson，实际={ensemble.models[0].name}"
        )

    def test_predict_consistent_with_single_model(self):
        """验证单模型集成时输出与原模型一致"""
        ensemble = SimpleEnsemble()
        features = {'home_goals_avg': 1.5, 'away_goals_avg': 1.2}
        result = ensemble.predict_proba(features)
        poisson = PoissonModel()
        expected = poisson.predict_proba(features)
        for key in ['win', 'draw', 'lose']:
            self.assertAlmostEqual(
                result[key], expected[key], places=5,
                msg=f"单模型集成时期望{key}={expected[key]}，实际={result[key]}"
            )

    def test_zero_weight_models_ignored(self):
        """验证权重为0的模型被忽略"""
        model1 = PoissonModel()
        ensemble = SimpleEnsemble(
            models=[model1],
            weights={"poisson": 0.0}  # 权重为0
        )
        features = {'home_goals_avg': 1.5, 'away_goals_avg': 1.2}
        result = ensemble.predict_proba(features)
        # 权重为0时应返回默认值
        self.assertEqual(
            result, {'win': 0.40, 'draw': 0.30, 'lose': 0.30},
            f"权重为0时期望返回默认值，实际={result}"
        )

    def test_ensemble_name(self):
        """验证集成模型名称"""
        ensemble = SimpleEnsemble()
        self.assertEqual(
            ensemble.name, "ensemble",
            f"期望name='ensemble'，实际='{ensemble.name}'"
        )


# ===================================================================
# 4. RiskController 测试
# ===================================================================

class TestRiskController(unittest.TestCase):
    """风控控制器测试（这是足彩系统的核心安全网）"""

    def _make_match(self, match_id="M001", home="T1", away="T2"):
        return MatchInfo(
            match_id=match_id,
            home_team_id=home, away_team_id=away,
            home_team_name=f"队{home}", away_team_name=f"队{away}",
        )

    def _make_rec(self, match_id="M001", stake=100.0):
        return Recommendation(
            match_id=match_id,
            recommendation="主胜",
            probability=0.55, odds=2.0, ev=0.10,
            kelly=0.05, suggested_stake=stake,
            tier="high", confidence="高",
        )

    def test_controller_instantiates(self):
        """验证风控器可以正常实例化"""
        rc = JinshuiyaoRiskController()
        self.assertEqual(
            rc.max_daily_bets, MAX_DAILY_BETS,
            f"期望max_daily_bets={MAX_DAILY_BETS}，实际={rc.max_daily_bets}"
        )
        self.assertEqual(
            rc.daily_loss_limit, DAILY_LOSS_LIMIT,
            f"期望daily_loss_limit={DAILY_LOSS_LIMIT}，实际={rc.daily_loss_limit}"
        )

    def test_custom_params(self):
        """验证自定义参数覆盖默认值"""
        rc = JinshuiyaoRiskController(
            daily_loss_limit=0.05,
            max_daily_bets=3,
            consecutive_errors_threshold=5,
        )
        self.assertEqual(rc.daily_loss_limit, 0.05)
        self.assertEqual(rc.max_daily_bets, 3)
        self.assertEqual(rc.consecutive_errors_threshold, 5)

    # ---------- 单日场次限制 ----------
    def test_daily_bets_limit_enforced(self):
        """验证单日推荐场次上限生效"""
        rc = JinshuiyaoRiskController(max_daily_bets=2)
        match1 = self._make_match("M1", "A", "B")
        match2 = self._make_match("M2", "C", "D")
        match3 = self._make_match("M3", "E", "F")
        rec1 = self._make_rec("M1", 50)
        rec2 = self._make_rec("M2", 50)
        rec3 = self._make_rec("M3", 50)

        ok1, _, _ = rc.approve_recommendation(rec1, match1, 10000)
        ok2, _, _ = rc.approve_recommendation(rec2, match2, 10000)
        ok3, reason3, _ = rc.approve_recommendation(rec3, match3, 10000)

        self.assertTrue(ok1, "第1单应通过")
        self.assertTrue(ok2, "第2单应通过")
        self.assertFalse(ok3, f"第3单应被拦截，实际通过，原因={reason3}")
        self.assertEqual(
            reason3, "单日推荐已达上限",
            f"期望原因='单日推荐已达上限'，实际='{reason3}'"
        )

    # ---------- 连错暂停 ----------
    def test_consecutive_errors_auto_pause(self):
        """验证连错达到阈值后自动暂停"""
        rc = JinshuiyaoRiskController(consecutive_errors_threshold=3)
        match = self._make_match("M1", "A", "B")
        rec = self._make_rec("M1", 100)

        rc.record_result("M1", -50)   # 第1场输
        rc.record_result("M2", -30)   # 第2场输
        self.assertFalse(rc.auto_paused, "连错2场不应暂停")

        rc.record_result("M3", -20)   # 第3场输 → 达到阈值
        self.assertTrue(rc.auto_paused, "连错3场应自动暂停")

        ok, reason, _ = rc.approve_recommendation(rec, match, 10000)
        self.assertFalse(ok, f"暂停后应拒绝新单，实际通过，原因={reason}")
        self.assertIn("连错", reason, f"原因应包含'连错'，实际='{reason}'")

    def test_consecutive_wins_resume(self):
        """验证连赢2场后自动恢复"""
        rc = JinshuiyaoRiskController(consecutive_errors_threshold=2)
        rc.record_result("M1", -50)
        rc.record_result("M2", -50)
        self.assertTrue(rc.auto_paused, "连错2场应暂停")

        rc.record_result("M3", 50)    # 第1场赢
        self.assertTrue(rc.auto_paused, "仅1场赢不应恢复")

        rc.record_result("M4", 30)    # 第2场赢 → 恢复
        self.assertFalse(rc.auto_paused, "连赢2场应自动恢复")

    def test_manual_resume(self):
        """验证手动恢复功能"""
        rc = JinshuiyaoRiskController(consecutive_errors_threshold=2)
        rc.record_result("M1", -50)
        rc.record_result("M2", -50)
        self.assertTrue(rc.auto_paused)

        rc.resume_manual()
        self.assertFalse(rc.auto_paused, "手动恢复后应解除暂停")
        self.assertEqual(rc.consecutive_errors, 0, "手动恢复后连错应清零")

    # ---------- 单日止损 ----------
    def test_daily_loss_limit(self):
        """验证单日亏损比例限制"""
        rc = JinshuiyaoRiskController(daily_loss_limit=0.05)  # 5%止损
        match = self._make_match("M1", "A", "B")
        rec = self._make_rec("M1", 100)
        bankroll = 10000

        rc.record_result("M1", -600)   # 亏600 = 6% → 超限
        ok, reason, _ = rc.approve_recommendation(rec, match, bankroll)
        self.assertFalse(ok, f"亏损超限时应拒绝，实际通过，原因={reason}")
        self.assertEqual(reason, "触发单日止损", f"原因不匹配，实际='{reason}'")

    def test_daily_loss_within_limit(self):
        """验证亏损在限额内时正常通过"""
        rc = JinshuiyaoRiskController(daily_loss_limit=0.05)
        match = self._make_match("M1", "A", "B")
        rec = self._make_rec("M1", 100)
        bankroll = 10000

        rc.record_result("M1", -100)   # 亏100 = 1% → 在限内
        ok, reason, _ = rc.approve_recommendation(rec, match, bankroll)
        self.assertTrue(ok, f"亏损在限额内应通过，实际被拒，原因={reason}")

    # ---------- 相关性风控 ----------
    def test_same_team_blocked(self):
        """验证同一球队当天不能重复推荐"""
        rc = JinshuiyaoRiskController(max_same_team=1)
        match1 = self._make_match("M1", "A", "B")
        match2 = self._make_match("M2", "A", "C")  # 球队A又出现
        rec1 = self._make_rec("M1", 50)
        rec2 = self._make_rec("M2", 50)

        ok1, _, _ = rc.approve_recommendation(rec1, match1, 10000)
        ok2, reason2, _ = rc.approve_recommendation(rec2, match2, 10000)

        self.assertTrue(ok1, "第1单应通过")
        self.assertFalse(ok2, f"同球队重复应被拦截，实际通过，原因={reason2}")

    def test_same_league_limit(self):
        """验证同一联赛推荐上限"""
        rc = JinshuiyaoRiskController(max_same_league=2, max_same_team=10)
        m1 = MatchInfo("M1", "A1", "B1", "队A1", "队B1")
        m2 = MatchInfo("M2", "A2", "B2", "队A2", "队B2")
        m3 = MatchInfo("M3", "A3", "B3", "队A3", "队B3")
        r1 = self._make_rec("M1", 50)
        r2 = self._make_rec("M2", 50)
        r3 = self._make_rec("M3", 50)

        ok1, _, _ = rc.approve_recommendation(r1, m1, 10000, league="英超")
        ok2, _, _ = rc.approve_recommendation(r2, m2, 10000, league="英超")
        ok3, reason3, _ = rc.approve_recommendation(r3, m3, 10000, league="英超")

        self.assertTrue(ok1, "英超第1单应通过")
        self.assertTrue(ok2, "英超第2单应通过")
        self.assertFalse(ok3, f"英超第3单应被拦截，实际通过，原因={reason3}")

    # ---------- 凯利仓位 ----------
    def test_kelly_stake_adjustment(self):
        """验证折扣凯利仓位计算"""
        rc = JinshuiyaoRiskController(kelly_multiplier=0.25, max_stake_ratio=0.05)
        suggested = 200.0
        bankroll = 10000

        adjusted = rc.adjust_stake(suggested, bankroll)
        expected_max = bankroll * 0.05  # 500

        self.assertGreater(
            adjusted, 0,
            f"调整后投注额应>0，实际={adjusted}"
        )
        self.assertLessEqual(
            adjusted, expected_max,
            f"调整后投注额应≤上限{expected_max}，实际={adjusted}"
        )
        self.assertLessEqual(
            adjusted, suggested * 0.25 + 0.01,  # 加0.01容差
            f"调整后投注额应≤折扣凯利({suggested * 0.25})，实际={adjusted}"
        )

    def test_zero_stake_rejected(self):
        """验证投注额为0时拒绝"""
        rc = JinshuiyaoRiskController()
        match = self._make_match("M1", "A", "B")
        rec = self._make_rec("M1", 0.0)
        ok, reason, _ = rc.approve_recommendation(rec, match, 10000)
        self.assertFalse(ok, f"投注额为0应被拒，实际通过，原因={reason}")

    # ---------- 统计属性 ----------
    def test_hit_rate_calculation(self):
        """验证胜率计算"""
        rc = JinshuiyaoRiskController()
        rc.record_result("M1", 100)   # 赢
        rc.record_result("M2", -50)    # 输
        rc.record_result("M3", 30)     # 赢

        self.assertEqual(rc._total_bets, 3, f"期望总投注=3，实际={rc._total_bets}")
        self.assertEqual(rc._total_wins, 2, f"期望总胜场=2，实际={rc._total_wins}")
        self.assertAlmostEqual(
            rc.hit_rate, 2/3, places=5,
            msg=f"期望胜率=0.6667，实际={rc.hit_rate}"
        )

    def test_hit_rate_zero_bets(self):
        """验证无投注时胜率为0"""
        rc = JinshuiyaoRiskController()
        self.assertEqual(rc.hit_rate, 0.0, f"无投注时期望胜率=0，实际={rc.hit_rate}")

    def test_status_summary(self):
        """验证状态摘要包含所有必要字段"""
        rc = JinshuiyaoRiskController()
        rc.record_result("M1", 100)
        status = rc.status_summary
        required = ['consecutive_errors', 'consecutive_wins', 'auto_paused',
                    'hit_rate', 'total_bets', 'total_wins',
                    'today_bets', 'today_loss']
        for key in required:
            self.assertIn(
                key, status,
                f"状态摘要应包含key='{key}'，实际keys={list(status.keys())}"
            )

    # ---------- reset_daily ----------
    def test_reset_daily(self):
        """验证每日重置功能"""
        rc = JinshuiyaoRiskController()
        match = self._make_match("M1", "A", "B")
        rec = self._make_rec("M1", 100)
        rc.approve_recommendation(rec, match, 10000)
        rc.record_result("M1", -50)

        self.assertEqual(len(rc._today_bets), 1)
        self.assertGreater(rc._today_loss_amount, 0)

        rc.reset_daily()
        self.assertEqual(len(rc._today_bets), 0, "重置后当日投注应清空")
        self.assertEqual(rc._today_loss_amount, 0.0, "重置后当日亏损应清零")


# ===================================================================
# 5. ComboOptimizer 测试
# ===================================================================

class TestComboOptimizer(unittest.TestCase):
    """2串1组合优化器测试"""

    def _make_matches(self):
        return [
            {
                'match_id': 'M1', 'home': '曼联', 'away': '利物浦',
                'odds_win': 2.1, 'odds_draw': 3.4, 'odds_lose': 3.2,
                'model_prob_win': 0.50, 'model_prob_draw': 0.25, 'model_prob_lose': 0.25,
            },
            {
                'match_id': 'M2', 'home': '曼城', 'away': '阿森纳',
                'odds_win': 1.8, 'odds_draw': 3.6, 'odds_lose': 4.2,
                'model_prob_win': 0.60, 'model_prob_draw': 0.22, 'model_prob_lose': 0.18,
            },
        ]

    def test_optimizer_instantiates(self):
        """验证优化器可以实例化"""
        opt = ComboOptimizer()
        self.assertEqual(opt.max_stake_ratio, 0.015)
        self.assertEqual(opt.kelly_mult, 0.25)

    def test_generate_candidates_basic(self):
        """验证候选生成功能"""
        opt = ComboOptimizer()
        matches = self._make_matches()
        legs = opt.generate_candidates(matches)
        self.assertGreater(
            len(legs), 0,
            f"期望生成至少1个候选，实际={len(legs)}"
        )
        for leg in legs:
            self.assertIsInstance(
                leg, ComboLeg,
                f"每个候选应是ComboLeg，实际={type(leg)}"
            )
            self.assertGreater(
                leg.odds, 1.0,
                f"赔率应>1.0，实际={leg.odds}"
            )
            self.assertGreater(
                leg.probability, 0,
                f"概率应>0，实际={leg.probability}"
            )

    def test_generate_candidates_negative_ev_filtered(self):
        """验证负EV的选项被过滤掉"""
        opt = ComboOptimizer()
        matches = [{
            'match_id': 'M1', 'home': 'A', 'away': 'B',
            'odds_win': 1.5, 'odds_draw': 4.0, 'odds_lose': 5.0,
            'model_prob_win': 0.40, 'model_prob_draw': 0.30, 'model_prob_lose': 0.30,
        }]
        legs = opt.generate_candidates(matches)
        for leg in legs:
            self.assertGreater(
                leg.ev, 0,
                f"所有候选EV应>0，实际发现EV={leg.ev}的选项"
            )

    def test_optimize_returns_tickets(self):
        """验证优化返回ComboTicket列表"""
        opt = ComboOptimizer()
        matches = self._make_matches()
        tickets = opt.optimize(matches, bankroll=10000)
        self.assertIsInstance(tickets, list, f"期望返回list，实际={type(tickets)}")
        for t in tickets:
            self.assertIsInstance(t, ComboTicket, f"每个应为ComboTicket，实际={type(t)}")
            self.assertNotEqual(
                t.leg1.match_id, t.leg2.match_id,
                f"2串1的两场比赛应不同，实际都是{t.leg1.match_id}"
            )

    def test_optimize_insufficient_matches(self):
        """验证只有1场比赛时返回空"""
        opt = ComboOptimizer()
        matches = [self._make_matches()[0]]  # 只有1场
        tickets = opt.optimize(matches, bankroll=10000)
        self.assertEqual(
            tickets, [],
            f"1场比赛时期望返回空，实际={tickets}"
        )

    def test_optimize_respects_max_combos(self):
        """验证max_combos参数生效"""
        opt = ComboOptimizer()
        matches = self._make_matches()
        tickets = opt.optimize(matches, bankroll=10000, max_combos=2)
        self.assertLessEqual(
            len(tickets), 2,
            f"期望最多返回2个组合，实际={len(tickets)}"
        )

    def test_format_tickets(self):
        """验证文本格式化功能"""
        opt = ComboOptimizer()
        matches = self._make_matches()
        tickets = opt.optimize(matches, bankroll=10000)
        text = opt.format_tickets(tickets)
        self.assertIsInstance(text, str, f"期望返回str，实际={type(text)}")
        if tickets:
            self.assertGreater(
                len(text), 0,
                f"有推荐时期望非空文本，实际='{text}'"
            )

    def test_format_empty_tickets(self):
        """验证无推荐时的友好提示"""
        opt = ComboOptimizer()
        text = opt.format_tickets([])
        self.assertIn(
            "暂无", text,
            f"空列表时期望返回'暂无'提示，实际='{text}'"
        )


# ===================================================================
# 6. Schemas 数据结构测试
# ===================================================================

class TestSchemas(unittest.TestCase):
    """数据结构测试（确保dataclass字段完整）"""

    def test_match_info_fields(self):
        """验证MatchInfo包含所有必要字段"""
        m = MatchInfo(
            match_id="M001",
            home_team_id="T1", away_team_id="T2",
            home_team_name="主队", away_team_name="客队",
            league="英超", date="2026-07-24", kickoff_time="22:00",
        )
        self.assertEqual(m.match_id, "M001")
        self.assertEqual(m.home_team_id, "T1")
        self.assertEqual(m.away_team_id, "T2")
        self.assertEqual(m.league, "英超")

    def test_odds_data_fields(self):
        """验证OddsData包含所有必要字段"""
        o = OddsData(home_win=2.1, draw=3.4, away_win=3.2, source="竞彩")
        self.assertEqual(o.home_win, 2.1)
        self.assertEqual(o.draw, 3.4)
        self.assertEqual(o.away_win, 3.2)
        self.assertEqual(o.source, "竞彩")

    def test_recommendation_fields(self):
        """验证Recommendation包含所有必要字段"""
        r = Recommendation(
            match_id="M001", recommendation="主胜",
            probability=0.55, odds=2.0, ev=0.10,
            kelly=0.05, suggested_stake=100.0,
            tier="high", confidence="高",
        )
        self.assertEqual(r.recommendation, "主胜")
        self.assertEqual(r.tier, "high")
        self.assertEqual(r.confidence, "高")

    def test_backtest_summary_fields(self):
        """验证BacktestSummary包含所有必要字段"""
        s = BacktestSummary(
            initial_bankroll=10000, final_bankroll=11500,
            total_profit=1500, roi=0.15, max_drawdown=0.05,
            hit_rate=0.55, total_bets=100, won_bets=55,
        )
        self.assertEqual(s.roi, 0.15)
        self.assertEqual(s.hit_rate, 0.55)
        self.assertEqual(s.total_bets, 100)


# ===================================================================
# 入口
# ===================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
