# -*- coding: utf-8 -*-
"""足彩子系统 - 金水谣内核适配层

将现有 jinshuiyao/ 目录中的足彩预测系统封装为 DomainBase 标准接口。
所有实际计算复用 jinshuiyao/ 中的ML Pipeline。
"""
import os
import csv
import json
import logging
from datetime import datetime
from domains.base import DomainBase
from core.context import run_in_subsystem

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'jinshuiyao', 'data')
MATCHES_CSV = os.path.join(DATA_DIR, "matches_supplemented.csv")
MATCHES_FALLBACK_CSV = os.path.join(DATA_DIR, "matches.csv")
REAL_CSV = os.path.join(DATA_DIR, "matches_real.csv")


def _load_csv(csv_path):
    try:
        if not os.path.exists(csv_path):
            return []
        with open(csv_path, 'r', encoding='utf-8') as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _lookup_match(home, away, matches):
    for m in matches:
        if m.get('home', '').strip() == home.strip() and m.get('away', '').strip() == away.strip():
            return m
    return None


def _build_default_features(home_rank=10, away_rank=10, home_form="", away_form=""):
    league_avg_goals = 1.35
    rank_factor = 1.0 - (int(home_rank) - int(away_rank)) * 0.02 if home_rank and away_rank else 1.0
    form_factor_home = 1.0 + home_form.count('W') * 0.04 - home_form.count('L') * 0.04 if home_form else 0.0
    form_factor_away = 1.0 + away_form.count('W') * 0.04 - away_form.count('L') * 0.04 if away_form else 0.0
    return {
        'home_goals_avg': round(max(0.2, league_avg_goals * rank_factor * form_factor_home), 2),
        'home_conceded_avg': round(max(0.2, league_avg_goals * (2 - rank_factor) * (2 - form_factor_home)), 2),
        'home_xg_avg': round(max(0.2, league_avg_goals * rank_factor * form_factor_home), 2),
        'home_xga_avg': round(max(0.2, league_avg_goals * (2 - rank_factor) * (2 - form_factor_home)), 2),
        'away_goals_avg': round(max(0.2, league_avg_goals / rank_factor * form_factor_away), 2),
        'away_conceded_avg': round(max(0.2, league_avg_goals / (2 - rank_factor) * (2 - form_factor_away)), 2),
        'away_xg_avg': round(max(0.2, league_avg_goals / rank_factor * form_factor_away), 2),
        'away_xga_avg': round(max(0.2, league_avg_goals / (2 - rank_factor) * (2 - form_factor_away)), 2),
        'home_injury_factor': 1.0,
        'away_injury_factor': 1.0,
        'h2h_home_wins': 0.0,
        'h2h_draws': 0.0,
        'h2h_away_wins': 0.0,
    }


class FootballDomain(DomainBase):
    """足球比赛预测子系统
    
    复用 jinshuiyao/ 目录中的ML Pipeline：
    数据 → FeatureEngine → PoissonModel → Calibrator → DecisionEngine → RiskController
    """
    DOMAIN_ID = "football"
    DESCRIPTION = "足球比赛预测（泊松模型 + ML集成 + 风控）"

    def __init__(self, config=None):
        super().__init__(config)
        self.data_dir = self.config.get("data_dir", DATA_DIR)
        self._feature_engine = None
        self._model = None
        self._calibrator = None
        self._decision_engine = None
        self._risk_controller = None
        self._last_result = None

    def setup(self):
        """加载足彩ML Pipeline"""
        try:
            from jinshuiyao.feature_engine import JinshuiyaoFeatureEngine
            from jinshuiyao.models.poisson_model import PoissonModel
            from jinshuiyao.calibrator import ProbabilityCalibrator
            from jinshuiyao.decision_engine import JinshuiyaoDecisionEngine
            from jinshuiyao.risk_controller import JinshuiyaoRiskController
                
            self._feature_engine = JinshuiyaoFeatureEngine()
            self._model = PoissonModel()
            self._calibrator = ProbabilityCalibrator()
            self._decision_engine = JinshuiyaoDecisionEngine()
            self._risk_controller = JinshuiyaoRiskController()
            self._initialized = True
            logger.info("足彩子系统初始化完成，引擎就绪")
            return True
        except ImportError as e:
            logger.warning("足彩引擎模块未就绪 (%s)，以降级模式运行", e)
            self._feature_engine = None
            self._model = None
            self._calibrator = None
            self._decision_engine = None
            self._risk_controller = None
            self._initialized = True
            return True
        except Exception as e:
            logger.error("足彩子系统初始化失败: %s", e)
            self._initialized = True
            return True

    def teardown(self):
        """清理资源"""
        self._initialized = False
        logger.info("足彩子系统已关闭")
        return True

    def fetch(self, **kwargs):
        """抓取比赛数据（从CSV）"""
        try:
            matches = _load_csv(MATCHES_CSV) or _load_csv(MATCHES_FALLBACK_CSV) or []
            return {"success": True, "count": len(matches), "data": matches,
                    "message": f"加载 {len(matches)} 条比赛记录"}
        except Exception as e:
            return {"success": False, "data": [], "message": str(e)}

    def analyze(self, data=None, **kwargs):
        """特征工程 + 模型预测
        
        data 可包含: home, away, odds (dict of home_win/draw/away_win), league
        返回完整ML Pipeline输出: 特征 → 模型概率 → 校准 → 比分路径
        """
        def _run():
            if not data or not isinstance(data, dict):
                return {"status": "error", "message": "需要 home/away 参数"}
            home = data.get('home', '').strip()
            away = data.get('away', '').strip()
            if not home or not away:
                return {"status": "error", "message": "需要 home 和 away"}

            # 1. 加载CSV匹配数据
            matches = _load_csv(MATCHES_CSV) or _load_csv(MATCHES_FALLBACK_CSV) or []
            match_row = _lookup_match(home, away, matches)
            odds_input = data.get('odds', {})
            if not odds_input and match_row:
                odds_input = {
                    'home_win': float(match_row.get('odds_win', 1.0)),
                    'draw': float(match_row.get('odds_draw', 1.0)),
                    'away_win': float(match_row.get('odds_lose', 1.0)),
                }

            # 2. 构建特征
            features = _build_default_features(
                home_rank=match_row.get('home_rank') if match_row else None,
                away_rank=match_row.get('away_rank') if match_row else None,
                home_form=match_row.get('home_form', '') if match_row else '',
                away_form=match_row.get('away_form', '') if match_row else '',
            )

            # 3. 泊松模型预测
            if self._model:
                model_prob = self._model.predict_proba(features)
            else:
                from jinshuiyao.models.poisson_model import PoissonModel
                model_prob = PoissonModel().predict_proba(features)

            # 4. 市场隐含概率
            from jinshuiyao.odds_utils import OddsUtils
            market_prob = OddsUtils.implied_probs_1x2(odds_input) if odds_input else {'win': 1/3, 'draw': 1/3, 'lose': 1/3}
            margin = OddsUtils.bookmaker_margin(odds_input) if odds_input else 0.0

            # 5. 概率校准
            if self._calibrator:
                calibrated = self._calibrator.shrink_to_market(model_prob, market_prob)
            else:
                from jinshuiyao.calibrator import ProbabilityCalibrator
                calibrated = ProbabilityCalibrator.shrink_to_market(model_prob, market_prob)

            # 6. 预期进球
            from jinshuiyao.score_path import compute_expected_goals, generate_score_paths
            lambda_home, lambda_away = compute_expected_goals(
                home_goals_avg=features['home_goals_avg'],
                away_goals_avg=features['away_goals_avg'],
                home_conceded_avg=features['home_conceded_avg'],
                away_conceded_avg=features['away_conceded_avg'],
            )
            score_paths = generate_score_paths(lambda_home, lambda_away, top_n=5)

            self._last_result = {
                "status": "completed",
                "home": home,
                "away": away,
                "features": features,
                "model_prob": {k: round(float(v), 4) for k, v in model_prob.items()},
                "market_prob": {k: round(float(v), 4) for k, v in market_prob.items()},
                "calibrated": {k: round(float(v), 4) for k, v in calibrated.items()},
                "expected_goals": {"home": lambda_home, "away": lambda_away},
                "score_paths": [{"score": p.full_score, "prob": round(p.probability * 100, 2),
                                 "result": p.result} for p in score_paths],
                "market_margin": round(margin, 4),
                "odds": odds_input,
                "pipeline": ["FeatureEngine", "PoissonModel", "Calibrator", "ScorePath"],
            }
            return self._last_result

        return run_in_subsystem("football", _run)

    def generate(self, params=None, **kwargs):
        """生成推荐方案（凯利准则 + 风控）
        
        params 可包含: home, away, bankroll (资金)
        返回决策引擎推荐 + 比分路径
        """
        _params = params if params else {}
        def _run():
            home = _params.get('home', '').strip()
            away = _params.get('away', '').strip()

            # 先跑分析管线
            analysis = self.analyze(_params)
            if not analysis or analysis.get('status') == 'error':
                return {"status": "error", "predictions": [], "message": analysis.get('message', '分析失败')}

            calibrated = analysis.get('calibrated', {})
            odds = analysis.get('odds', {})
            score_paths = analysis.get('score_paths', [])
            bankroll = float(_params.get('bankroll', 1000.0))

            predictions = []

            # 决策引擎推荐
            if self._decision_engine and odds:
                match_id = f"{home}-vs-{away}"
                try:
                    rec = self._decision_engine.recommend(
                        match_id=match_id,
                        odds=odds,
                        prob=calibrated,
                        bankroll=bankroll,
                    )
                    if rec:
                        # 风控审批
                        if self._risk_controller:
                            from jinshuiyao.schemas import MatchInfo
                            mi = MatchInfo(
                                match_id=match_id,
                                home_team_id=home,
                                away_team_id=away,
                                home_team_name=home,
                                away_team_name=away,
                            )
                            approved, reason, stake = self._risk_controller.approve_recommendation(
                                rec, mi, bankroll
                            )
                            if approved:
                                rec.suggested_stake = stake

                        predictions.append({
                            "match_id": match_id,
                            "recommendation": rec.recommendation,
                            "probability": round(rec.probability, 4),
                            "odds": rec.odds,
                            "ev": round(rec.ev, 4),
                            "kelly": round(rec.kelly, 4),
                            "suggested_stake": round(rec.suggested_stake, 2),
                            "tier": rec.tier,
                            "confidence": rec.confidence,
                            "value_gap": round(rec.value_gap, 4),
                            "candidates": rec.candidates,
                        })
                except Exception as e:
                    logger.warning("决策引擎推荐失败: %s", e)

            # 无推荐时从校准概率生成简版
            if not predictions:
                direction_map = {'win': '主胜', 'draw': '平局', 'lose': '客胜'}
                best_ev = -999
                best_dir = None
                for k, label in direction_map.items():
                    p = calibrated.get(k, 0)
                    o = odds.get('home_win' if k == 'win' else 'draw' if k == 'draw' else 'away_win', 1.0)
                    ev = p * o - 1
                    if ev > best_ev:
                        best_ev = ev
                        best_dir = k
                if best_dir and best_ev > 0:
                    predictions.append({
                        "match_id": f"{home}-vs-{away}",
                        "recommendation": direction_map[best_dir],
                        "probability": round(calibrated.get(best_dir, 0), 4),
                        "odds": odds.get('home_win' if best_dir == 'win' else 'draw' if best_dir == 'draw' else 'away_win', 0),
                        "ev": round(best_ev, 4),
                        "tier": "medium",
                        "confidence": "中",
                    })

            result = {
                "status": "completed",
                "home": home,
                "away": away,
                "model_prob": calibrated,
                "predictions": predictions,
                "score_paths": score_paths[:3],
                "expected_goals": analysis.get('expected_goals', {}),
                "market_margin": analysis.get('market_margin', 0),
                "summary": f"{home} vs {away}: 分析完成，{len(predictions)} 条推荐",
                "domain_id": self.DOMAIN_ID,
            }
            self._last_result = result
            return result

        return run_in_subsystem("football", _run)

    def review(self, predictions=None, actual=None, **kwargs):
        """复盘（ROI/命中率/回撤）

        predictions: domain.generate() 输出的预测列表
        actual: 可用 matches_real.csv 中的实际结果对比
        """
        if actual is None:
            real_matches = _load_csv(REAL_CSV) or []
        else:
            real_matches = actual if isinstance(actual, list) else []

        if predictions:
            comps = []
            hits = 0
            total_roi = 0.0
            pred_map = {}
            for p in predictions:
                if isinstance(p, dict) and 'recommendation' in p:
                    pred_map[p.get('match_id', '')] = p

            for rm in real_matches:
                result_raw = rm.get('result', '').strip()
                result_map = {'主胜': 'win', '平': 'draw', '客胜': 'lose'}
                actual_result = result_map.get(result_raw, '')
                if not actual_result:
                    continue
                mid = rm.get('match_id', '')
                pred = pred_map.get(mid) or pred_map.get(f"{rm.get('home','')}-vs-{rm.get('away','')}")
                if pred:
                    pred_dir = pred.get('recommendation', '')
                    hit = pred_dir == (result_raw if result_raw in ['主胜', '平局', '客胜'] else '')
                    if hit:
                        hits += 1
                    comps.append({
                        'match_id': mid,
                        'home': rm.get('home', ''),
                        'away': rm.get('away', ''),
                        'prediction': pred_dir,
                        'actual': result_raw,
                        'hit': hit,
                    })

            total = len(comps)
            return {
                "reviews": total,
                "hits": hits,
                "hit_rate": round(hits / total, 4) if total > 0 else 0,
                "updated": total > 0,
                "comparisons": comps,
                "status": "completed",
            }

        return {"reviews": 0, "hits": 0, "updated": False, "status": "completed",
                "message": "无预测数据提供，可从 matches_real.csv 加载实际结果"}

    def status(self):
        """健康状态"""
        matches = _load_csv(MATCHES_CSV) or _load_csv(MATCHES_FALLBACK_CSV) or []
        real_matches = _load_csv(REAL_CSV) or []
        return {
            "ready": self._initialized,
            "domain_id": self.DOMAIN_ID,
            "engines": {
                "feature_engine": self._feature_engine is not None,
                "poisson_model": self._model is not None,
                "calibrator": self._calibrator is not None,
                "decision_engine": self._decision_engine is not None,
                "risk_controller": self._risk_controller is not None,
            },
            "csv_data": {
                "upcoming": len(matches),
                "real_results": len(real_matches),
            },
            "last_run": self._last_result.get('status') if self._last_result else None,
            "errors": [],
        }
