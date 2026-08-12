# -*- coding: utf-8 -*-
"""预测服务 - 核心预测逻辑的服务化封装

从 jinshuiyao.py App.gen_one 提取的核心预测逻辑。
无GUI依赖，可被 LotteryDomain.generate()、回测引擎、测试等独立调用。

设计原则：
  1. 所有引擎通过构造函数注入，不持有任何GUI引用
  2. 日志通过回调函数传出（可选）
  3. 返回结果字典而非直接保存，让调用方决定如何持久化
  4. 与 App.gen_one 保持100%逻辑一致性
"""
import logging
import json
import traceback
from config import LOTTERY_RULES, EXCLUDED_LOTS
from models.lottery_data import Data
from utils.number_utils import parse_reds, fmt_period, sanitize_prediction
from utils.ticket_validator import is_valid_period

logger = logging.getLogger(__name__)

# 各玩法随机期望命中（hits=命中号码/位置数）——单一真源（债务-203，brain_daily.py 复用本常量）
_PLAY_EXPECTED = {
    ("福彩3D", "单注"): 0.9, ("排列三", "单注"): 0.9,
    ("福彩3D", "直选"): 0.3, ("排列三", "直选"): 0.3,
    ("福彩3D", "直选推荐"): 0.3, ("排列三", "直选推荐"): 0.3,
    ("福彩3D", "组三"): 0.9, ("排列三", "组三"): 0.9,
    ("福彩3D", "组六"): 0.9, ("排列三", "组六"): 0.9,
    ("福彩3D", "组六复式(5码)"): 1.5, ("排列三", "组六复式(5码)"): 1.5,
    ("福彩3D", "组六复式(6码)"): 1.8, ("排列三", "组六复式(6码)"): 1.8,
    ("福彩3D", "复式"): 1.4, ("排列三", "复式"): 1.4,
    ("双色球", "单注"): 1.15, ("双色球", "复式"): 1.40,
    ("双色球", "预测"): 1.15, ("双色球", "胆拖"): 1.17,
    ("大乐透", "单注"): 1.05, ("大乐透", "复式"): 1.36,
    ("大乐透", "预测"): 1.05, ("大乐透", "胆拖"): 1.17,
    ("七乐彩", "单注"): 1.63, ("七乐彩", "复式"): 2.10, ("七乐彩", "胆拖"): 1.90,
    ("快乐8", "单注"): 2.13, ("快乐8", "复式"): 2.25, ("快乐8", "胆拖"): 2.00,
    ("七星彩", "单注"): 2.97, ("七星彩", "复式"): 3.08, ("七星彩", "胆拖"): 3.00,
}


class PredictionService:
    """彩票预测服务

    封装完整的预测流水线：
    杀号 → 热号 → 赫斯特 → 遗漏 → 形态 → 关联 → FormatGen → 输出
    """

    def __init__(self, killer=None, evolve=None, brain=None, corr_matrix=None,
                 engine_states=None, hot_window=50, on_log=None):
        """
        Args:
            killer: Killer 引擎实例
            evolve: EvolutionManager 实例
            brain: SmartBrain 实例（可选）
            corr_matrix: CorrelationMatrix 实例（可选，懒初始化）
            engine_states: dict 引擎开关 {"hurst": True, "morph": True, ...}
            hot_window: 热号计算窗口
            on_log: 日志回调 func(message, level="INFO")
        """
        self.killer = killer
        self.evolve = evolve
        self.brain = brain
        self.corr_matrix = corr_matrix
        self.engine_states = engine_states or {}
        self.hot_window = hot_window
        self._on_log = on_log

        # 延迟导入的引擎引用
        self._preds_cache = []

    def log(self, msg, level="INFO"):
        """统一日志输出"""
        logger.log(getattr(logging, level.upper(), logging.INFO), msg)
        if self._on_log:
            self._on_log(msg, level)

    def _play_recent_health(self, lot, play_type, window=30):
        """读取复盘数据，统计该彩种+玩法近 N 期平均命中"""
        try:
            if self.brain is None:
                return None
            with open(self.brain.pred_file, encoding="utf-8") as f:
                rows = json.load(f)
            rows = [r for r in rows if r.get("lot") == lot and r.get("type") == play_type][-window:]
            if len(rows) < 5:
                return None
            return {"n": len(rows), "avg": sum(r.get("hits", 0) for r in rows) / len(rows)}
        except Exception:
            return None

    def _brain_play_health(self, lot, play_plan):
        """🧠 大脑玩法健康度调整：低于随机基准60% → 自动停用；高于140% → 自动加注"""
        if not play_plan:
            return play_plan
        changes = []
        new_plan = []
        for p in play_plan:
            t = p.get("type", "")
            if t == "胆拖":
                changes.append("胆拖已自动停用(7彩种实测命中率均低于随机基准)")
                continue
            exp = _PLAY_EXPECTED.get((lot, t))
            if exp:
                st = self._play_recent_health(lot, t, 30)
                if st:
                    ratio = st["avg"] / exp
                    if ratio < 0.6:
                        changes.append(f"{t}自动停用(近{st['n']}期命中{st['avg']:.2f}/随机期望{exp:.2f}, 仅{ratio*100:.0f}%)")
                        continue
                    if ratio > 1.4:
                        p2 = dict(p)
                        p2["count"] = p.get("count", 1) * 2
                        new_plan.append(p2)
                        changes.append(f"{t}自动加注(近{st['n']}期命中{st['avg']:.2f}/随机期望{exp:.2f}, {ratio*100:.0f}%)")
                        continue
            new_plan.append(p)
        for ch in changes:
            self.log(f"🧠 {lot} 大脑自动调整: {ch}")
        return new_plan

    def _brain_consensus_order(self, lot, arr, kill, morph_data):
        """🧠 朋友方法(维度共识)注入选号：共识度降序号码表，供漏斗引擎补位优先"""
        try:
            from engines.dimension_consensus import DimensionConsensus
            morph_suggest = (morph_data or {}).get("suggest", "")
            dc = DimensionConsensus(lot).analyze(arr, kill=kill, morph_suggest=morph_suggest)
            con = dc.get("consensus") or []
            if not con:
                return None
            order = [(c["digit"], c["score"]) for c in con]
            # 融合大脑号码偏差学习（digit_adjustments 0.5-1.5，漏斗补位同时吃到两路信号）
            adj = {}
            if self.brain is not None:
                try:
                    adj = self.brain.get_digit_adjustments(lot)
                except Exception:
                    pass
            if adj:
                order = [(d, s * adj.get(d, 1.0)) for d, s in order]
            top = ", ".join("%02d(%d)" % (d, s) for d, s in order[:5])
            self.log(f"🧠 {lot} 维度共识注入选号(朋友方法+大脑偏差): {top}")
            return order
        except Exception as e:
            logger.debug("维度共识注入失败: %s", e)
            return None

    def generate(self, lot, play_plan=None, scheme="默认方案",
                 hot_window=None, per_value=None, play_value=None,
                 vote_value=None, preds_snapshot=None):
        """生成预测（服务化版本）

        完整复刻 App.gen_one 的核心逻辑，去除所有GUI依赖。

        Args:
            lot: 彩种名称
            play_plan: 玩法计划列表
            scheme: 方案名
            hot_window: 热号窗口
            per_value: 指定期号
            play_value: 玩法
            vote_value: 投票模式
            preds_snapshot: 预测快照（避免锁）

        Returns:
            dict: {
                "success": bool,
                "lot": str,
                "period": int,
                "tickets": {"单注": [...], "复式": [...], "胆拖": [...], "直选推荐": [...], "位置分析": {...}},
                "all_nums": [str],
                "messages": [str],  # 日志消息列表
                "error": str or None
            }
        """
        if lot in EXCLUDED_LOTS:
            return {"success": False, "lot": lot, "error": "排除彩种", "tickets": {}, "all_nums": [], "messages": []}

        messages = []

        # 期号
        if per_value:
            try:
                per = int(per_value)
            except Exception:
                per = Data.latest(lot) + 1
        else:
            per = Data.latest(lot) + 1

        if not is_valid_period(lot, per):
            msg = f"⚠️ {lot} 期号{per}无效，跳过生成"
            messages.append(msg)
            self.log(msg, "WARNING")
            return {"success": False, "lot": lot, "period": per, "error": "期号无效", "tickets": {}, "all_nums": [], "messages": messages}

        if Data.has_period(lot, per):
            msg = f"⚠️ {lot} 第{fmt_period(lot, per)}期已开奖，跳过生成"
            messages.append(msg)
            self.log(msg, "WARNING")
            return {"success": False, "lot": lot, "period": per, "error": "已开奖", "tickets": {}, "all_nums": [], "messages": messages}

        arr = Data.load(lot)
        if not arr:
            msg = f"⚠️ {lot} 无历史数据，无法生成预测"
            messages.append(msg)
            self.log(msg, "WARNING")
            return {"success": False, "lot": lot, "period": per, "error": "无数据", "tickets": {}, "all_nums": [], "messages": messages}

        try:
            # 过滤超范围号码
            rule = LOTTERY_RULES.get(lot, {})
            red_rule = rule.get("red", (0, 99))
            if isinstance(red_rule[0], tuple):
                rmin, rmax = 0, max(r[1] for r in red_rule)
            else:
                rmin, rmax = red_rule[0], red_rule[1]
            nums = [n for d in arr for n in parse_reds(d["nums"].split("+")[0]) if rmin <= n <= rmax]

            # 杀号
            kill = None
            if self.killer:
                self.killer.calc(nums, history=arr, lot=lot)
                kill = self.killer.smart_kill(arr, lot, pool=list(range(rmin, rmax + 1)))
                if kill:
                    kill_str = ",".join(f"{k:02d}" for k in sorted(kill)[:8])
                    self.log(f"🔪 {lot} 杀号({len(kill)}个): {kill_str}{'...' if len(kill) > 8 else ''}")

            # 赫斯特指数
            hurst = 0.5
            if self.engine_states.get("hurst", True) and len(arr) >= 50:
                try:
                    from engines.hurst import HurstCalculator
                    seq = [sum(parse_reds(d["nums"].split("+")[0])) for d in arr[-100:]]
                    hurst = HurstCalculator.compute(seq)
                    trend = "趋势延续" if hurst > 0.55 else ("均值回归" if hurst < 0.45 else "随机震荡")
                    self.log(f"📊 {lot} 赫斯特={hurst:.2f}({trend})")
                except Exception:
                    pass

            # 热号
            hot = {}
            if self.evolve:
                preds = preds_snapshot or []
                hot = self.evolve.train(lot, predictions=preds, hurst=hurst, hot_window=self.hot_window)
                # train() 返回 dict{号码: 权重}
                if hot:
                    # 打印日志：按权重排序取前6个
                    if isinstance(hot, dict):
                        top6 = sorted(hot.keys(), key=lambda x: hot[x], reverse=True)[:6]
                    else:
                        top6 = list(hot)[:6]
                    hot_str = ",".join(f"{h:02d}" for h in top6)
                    self.log(f"🔥 {lot} 热号Top6: {hot_str}")

            # 玩法
            play = play_value if play_value is not None else ("选10" if lot == "快乐8" else "选10")

            # 形态分析
            recent_stats = {}
            morph_data = None
            if lot in ["福彩3D", "排列三"]:
                forms = [[x for x in parse_reds(d["nums"].split("+")[0]) if 0 <= x <= 9] for d in arr[-20:]]
                recent_stats["3d_forms"] = forms
                if self.engine_states.get("morph", True):
                    try:
                        from engines.morph import MorphPredictor
                        morph_data = MorphPredictor(lot).analyze(arr)
                        if morph_data:
                            suggest = morph_data.get("suggest", "")
                            self.log(f"🧬 {lot} 形态分析: {suggest}" if suggest else f"🧬 {lot} 形态分析完成")
                    except Exception:
                        pass

            # 智能杀号评分
            smart_killer = None
            if self.engine_states.get("antikill", True):
                try:
                    from engines.validators import SmartKillScorer
                    smart_killer = SmartKillScorer(arr)
                except Exception:
                    pass

            # 关联矩阵
            corr = None
            if self.engine_states.get("correlation", True) and lot in ["双色球", "大乐透"]:
                try:
                    if not self.corr_matrix or self.corr_matrix.lot != lot:
                        from engines.correlation import CorrelationMatrix
                        self.corr_matrix = CorrelationMatrix(lot)
                        self.corr_matrix.build(arr)
                        self.corr_matrix.build_transition(arr)
                    corr = self.corr_matrix
                    self.log(f"🔗 {lot} 关联相斥矩阵已加载")
                except Exception:
                    pass

            cold_tunnel = self.engine_states.get("cold_tunnel", True)
            if cold_tunnel:
                self.log(f"❄️ {lot} 冷号突破已启用")

            # 遗漏分析
            miss_data = None
            try:
                from engines.miss_analyzer import MissAnalyzer
                miss_analyzer = MissAnalyzer(lot)
                # 注意：MissAnalyzer.analyze 期望 history 按时间从近到远（index 0 = 最新），
                # 而 Data.load 返回的是旧→新，这里需反转，否则 current_miss/breakthrough_score 全部失真
                miss_data = miss_analyzer.analyze(list(reversed(arr)))
                alerts = miss_analyzer.get_cold_alerts(1.5)
                if alerts:
                    alert_nums = [f"{n:02d}" for n, _ in alerts[:3]]
                    self.log(f"📈 {lot} 遗漏预警：{','.join(alert_nums)} 即将回补", "DEBUG")
            except Exception:
                pass

            # 多维参考特征（福彩3D/排列三）：遗漏/冷热/振幅/奇偶/大小/区间/和值/跨度
            ref_features = None
            if lot in ["福彩3D", "排列三"]:
                try:
                    from engines.feature_engine import analyze as feat_analyze
                    ref_features = feat_analyze(lot, arr)
                except Exception:
                    pass

            # ===== 知识库咨询：让经验卡片影响选号决策 =====
            kb_adjustments = self._consult_knowledge(lot)

            # 投票模式
            vote = vote_value if vote_value is not None else False
            hw = hot_window if hot_window is not None else self.hot_window

            # FormatGen 生成
            from engines.format_gen import FormatGen

            # ===== 知识库调整：影响杀号置信度和热号权重 =====
            if kb_adjustments["cards_used"] > 0:
                # kill_factor < 1.0 → 保守（减少杀号），> 1.0 → 激进（保留全部杀号）
                kf = kb_adjustments["kill_factor"]
                if kill and kf < 1.0:
                    # 保守模式：只保留前N个最确定的杀号（kill是set，需转list再截断）
                    original_len = len(kill)
                    keep = max(1, int(original_len * kf))
                    kill = set(sorted(kill)[:keep])
                    self.log(f"📚 知识库建议保守杀号: 保留{keep}/{original_len}个")
                # hot_factor > 1.0 → 热号权重增强
                hf = kb_adjustments["hot_factor"]
                if hot and hf > 1.05:
                    boost_count = min(3, int((hf - 1.0) * 10))
                    if isinstance(hot, dict):
                        # dict模式：提升top-N热号的权重值
                        top_keys = sorted(hot, key=hot.get, reverse=True)[:boost_count]
                        for k in top_keys:
                            hot[k] = hot.get(k, 1) * 1.5
                    else:
                        # list模式：重复top热号增加被选中概率
                        hot = list(hot) + list(hot)[:boost_count]
                    self.log(f"📚 知识库增强热号权重(+{boost_count})")
                # cold_factor > 1.05 → 增强冷号突破权重（联动遗漏预警）
                cf = kb_adjustments["cold_factor"]
                if cf > 1.05 and cold_tunnel and isinstance(hot, dict) and hot:
                    try:
                        alerts = []
                        if isinstance(miss_data, dict):
                            alerts = miss_data.get("cold_alerts") or []
                        if alerts:
                            boosted = 0
                            for num, _ in alerts[:3]:
                                if isinstance(num, int) and num in hot:
                                    hot[num] = max(1, int(hot[num] * (1 + (cf - 1.0) * 1.5)))
                                    boosted += 1
                            if boosted:
                                alert_nums = [f"{n:02d}" for n, _ in alerts[:3]]
                                self.log(f"📚 知识库增强冷号突破(+{boosted}个: {','.join(alert_nums)})")
                    except Exception:
                        pass

            # ===== 智能大脑: 置信度 + 策略权重（学习成果反哺预测） =====
            if self.brain is not None:
                try:
                    brain_confidence = self.brain.assess_confidence(lot, hot_weights=hot, final_hot=hot)
                    conf_pct = brain_confidence * 100
                    self.log(f"🧠 {lot} 大脑置信度: {conf_pct:.1f}%")
                    # 低置信度 → 热号权重收敛（保守，防过度追热）
                    if brain_confidence < 0.5 and isinstance(hot, dict) and hot:
                        for k in hot:
                            hot[k] = max(1, int(hot[k] * 0.8))
                        self.log(f"🧠 {lot} 低置信度: 热号权重收敛至80% (保守)")
                    # 置信度记录落盘（学习成果持久化，重启不丢）
                    try:
                        self.brain._save_state()
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    brain_weights = self.brain.get_strategy_weights(lot)
                    if brain_weights:
                        w_str = ", ".join(f"{k}={v:.2f}" for k, v in
                                          sorted(brain_weights.items(), key=lambda x: -x[1]))
                        self.log(f"🧠 {lot} 大脑策略权重: {w_str}")
                        budget = self.brain.recommend_budget_split(lot)
                        if budget:
                            b_str = ", ".join(f"{k} {v}元" for k, v in budget.items())
                            self.log(f"🧠 {lot} 预算建议: {b_str}")
                except Exception:
                    pass

            # ===== 🧠 大脑玩法健康度自动调整（低于随机基准60%→停用，高于140%→加注） =====
            if play_plan:
                play_plan = self._brain_play_health(lot, play_plan)

            # ===== 🧠 实测追热无益彩种：热号权重均匀化（防追热负贡献） =====
            if isinstance(hot, dict) and hot and lot in ("快乐8", "大乐透"):
                hot = {k: 1.0 for k in hot}
                self.log(f"🧠 {lot} 实测命中率低于随机基准, 大脑热号权重均匀化(回归随机采样)")

            # ===== 🧠 AI简报注入（第2步·长脑子）：当天AI建议号码加权（每天每彩种≤1次） =====
            ai_extra = {}
            try:
                from engines.brain_daily import ensure_daily_brief
                brief = ensure_daily_brief(lot, arr)
                if brief and brief.get("hot"):
                    for d in brief["hot"]:
                        ai_extra[d] = 0.5
                    self.log(f"🧠 {lot} AI简报注入: hot={brief['hot']}"
                             + (f" 理由:{brief['reason']}" if brief.get("reason") else ""))
            except Exception:
                pass

            if lot in ["福彩3D", "排列三"] and play_plan and sum(p['count'] for p in play_plan if p['type'] == '单注') >= 2:
                consensus_order = self._brain_consensus_order(lot, arr, kill, morph_data)
                fg = FormatGen(lot, kill, hot, play=play, recent_stats=recent_stats, morph_data=morph_data,
                               kill_check=self.engine_states.get("killcheck", False), history=arr,
                               smart_kill_scorer=smart_killer, play_plan=play_plan,
                               corr_matrix=corr, cold_tunnel_enabled=cold_tunnel, vote_mode=vote,
                               hot_window=hw, miss_data=miss_data, position_aware=True,
                               consensus_order=consensus_order, extra_hot=ai_extra)
                # 智能大脑修正
                self._apply_brain_adjustments(lot, fg)
                tickets = fg._gen_3d_hot_freq()
                dan_tuo = None
                for _p in play_plan:
                    if _p.get('type') == '胆拖':
                        dan_tuo = fg._make_dantuo(_p.get('config', {}))
                        break
                if dan_tuo:
                    tickets["胆拖"] = [dan_tuo]
                # 智能补位：确保至少1注组三 + 2注组六
                def _is_zu3(t):
                    digits = [int(x) for x in str(t).split(",") if x.strip().isdigit()]
                    return len(digits) == 3 and len(set(digits)) == 2

                zu3_count = sum(1 for t in tickets["单注"] if _is_zu3(t))
                zu6_count = len(tickets["单注"]) - zu3_count
                # 先补组三（至少1注）
                attempts = 0
                while zu3_count < 1 and attempts < 10:
                    extra = fg._generate_single()
                    cleaned = sanitize_prediction(lot, extra, "单注")
                    attempts += 1
                    if cleaned and _is_zu3(cleaned):
                        tickets["单注"].append(cleaned)
                        zu3_count += 1
                # 再补组六到总共3注
                attempts = 0
                while len(tickets["单注"]) < 3 and attempts < 15:
                    extra = fg._generate_single()
                    cleaned = sanitize_prediction(lot, extra, "单注")
                    attempts += 1
                    if cleaned and cleaned not in tickets["单注"]:
                        tickets["单注"].append(cleaned)
            else:
                fg = FormatGen(lot, kill, hot, play=play, recent_stats=recent_stats, morph_data=morph_data,
                               kill_check=self.engine_states.get("killcheck", False), history=arr,
                               smart_kill_scorer=smart_killer, play_plan=play_plan,
                               corr_matrix=corr, cold_tunnel_enabled=cold_tunnel, vote_mode=vote,
                               hot_window=hw, miss_data=miss_data, extra_hot=ai_extra)
                self._apply_brain_adjustments(lot, fg)
                tickets = fg.gen()

            # ===== 维度共识分析（吸收朋友三路系统/位置热码覆盖率/逐号码共识度） =====
            dim_consensus = None
            six_ref = None
            if lot in ["福彩3D", "排列三"] and tickets:
                try:
                    from engines.dimension_consensus import DimensionConsensus
                    five = None
                    for t in tickets.get("复式", []):
                        digits = [int(x) for x in str(t).replace(" ", "").split(",") if x.strip().isdigit()]
                        if len(digits) >= 3:
                            five = digits[:5]
                            break
                    if five is None and isinstance(hot, dict) and hot:
                        five = sorted(hot, key=hot.get, reverse=True)[:5]
                    morph_suggest = (morph_data or {}).get("suggest", "")
                    dim_consensus = DimensionConsensus(lot).analyze(
                        arr, five=five, kill=kill, morph_suggest=morph_suggest)
                    if dim_consensus.get("summary"):
                        self.log(f"🧮 {lot} 维度共识: {dim_consensus['summary']}")
                    # 六码参考池：实际五码 + 共识度最高的第6码（纯数据参考，不生成40元票）
                    if five:
                        pool_set = set(five)
                        rest = [c["digit"] for c in (dim_consensus.get("consensus") or [])
                                if c["digit"] not in pool_set]
                        if rest:
                            add_digit = rest[0]
                            six_ref = {
                                "pool": sorted(pool_set | {add_digit}),
                                "add_digit": add_digit,
                                "note": "六码参考池：若资金允许加码，优先加共识度第6名的%d；若开奖在六码不在五码=五码池选质问题" % add_digit,
                            }
                            self.log(f"🧮 {lot} 六码参考池: {','.join('%02d' % x for x in six_ref['pool'])}"
                                     f" (+第6码{add_digit:02d}, 非推荐投40元, 仅数据参考)")
                except Exception as e:
                    logger.debug("维度共识分析失败(降级跳过): %s", e)
                    dim_consensus = None

            # 输出
            self.log(f"===== {lot} 期{fmt_period(lot, per)} =====")
            all_nums = []
            for t in tickets.get("单注", []):
                cleaned = sanitize_prediction(lot, t, "单注")
                if cleaned and cleaned not in all_nums:
                    self.log(f"单注: {cleaned}")
                    all_nums.append(cleaned)
            for t in tickets.get("复式", []):
                cleaned = sanitize_prediction(lot, t, "复式")
                if cleaned and cleaned not in all_nums:
                    self.log(f"复式: {cleaned}")
                    all_nums.append(cleaned)
            for t in tickets.get("胆拖", []):
                if t and t not in all_nums:
                    self.log(f"胆拖: {t}")
                    all_nums.append(t)
            for t in tickets.get("直选推荐", []):
                if t and t not in all_nums:
                    self.log(f"🎯 直选: {t}")
                    all_nums.append(t)

            # 位置分析
            pos_info = tickets.get("位置分析")
            if pos_info:
                self.log(f"📊 位置感知: 百位Top3={pos_info.get('百位Top3')} "
                         f"十位Top3={pos_info.get('十位Top3')} "
                         f"个位Top3={pos_info.get('个位Top3')} "
                         f"大中小={pos_info.get('热门大中小')}")

            # 写入审计日志
            try:
                from core.audit_log import log_predict
                log_predict("lottery", lot, scheme or "默认方案", len(all_nums))
            except Exception:
                pass

            # 信号质量指数 SQI（诚实：仅反映信号清晰度+数据质量，非中奖概率）
            try:
                confidence = self._compute_signal_quality(
                    lot, arr, hurst, hot, kill, miss_data, corr,
                    kb_adjustments, vote, self.engine_states, ref_features)
            except Exception:
                confidence = {"score": None, "level": "unknown",
                              "signals": {}, "note": "信号质量指数暂不可用"}

            return {
                "success": True,
                "lot": lot,
                "period": per,
                "tickets": tickets,
                "all_nums": all_nums,
                "messages": messages,
                "error": None,
                "confidence": confidence,
                "ref_features": ref_features,
                "dimension_consensus": dim_consensus,
                "six_ref": six_ref,
            }

        except Exception as e:
            msg = f"❌ {lot} 生成预测失败: {e}"
            messages.append(msg)
            self.log(msg, "ERROR")
            self.log(traceback.format_exc(), "ERROR")
            return {
                "success": False,
                "lot": lot,
                "period": per,
                "error": str(e),
                "tickets": {},
                "all_nums": [],
                "messages": messages,
            }

    def _compute_signal_quality(self, lot, arr, hurst, hot, kill, miss_data, corr,
                                 kb_adjustments, vote, engine_states, ref_features=None):
        """计算信号质量指数 SQI（Signal Quality Index）。

        诚实约束：SQI 仅反映「模型当前信号清晰度 + 数据质量」，绝不表示中奖概率。
        彩票本质近随机（诚实基准见 JS-20260723-37），任何 SQI 都不可解读为命中率。
        整体 fail-safe：任一子信号异常记中性 50，整体异常返回 unknown，绝不抛异常影响主流程。
        """
        NEUTRAL = 50

        def _clamp(v, lo=0, hi=100):
            try:
                return max(lo, min(hi, int(round(v))))
            except Exception:
                return NEUTRAL

        try:
            # 1. 赫斯特趋势明确度：|hurst-0.5|/0.5，越大越非随机
            try:
                if hurst is None or not isinstance(hurst, (int, float)):
                    hurst_clarity = NEUTRAL
                else:
                    hurst_clarity = _clamp(abs(hurst - 0.5) / 0.5 * 100)
            except Exception:
                hurst_clarity = NEUTRAL

            # 2. 热号权重集中度：top6 权重和 / 总权重
            try:
                if isinstance(hot, dict) and hot:
                    total = sum(hot.values())
                    top6 = sorted(hot.values(), reverse=True)[:6]
                    hot_concentration = _clamp((sum(top6) / total) * 100) if total else NEUTRAL
                elif isinstance(hot, (list, tuple)) and hot:
                    from collections import Counter
                    cnt = Counter(hot)
                    total = sum(cnt.values())
                    top6 = sorted(cnt.values(), reverse=True)[:6]
                    hot_concentration = _clamp((sum(top6) / total) * 100) if total else NEUTRAL
                else:
                    hot_concentration = NEUTRAL
            except Exception:
                hot_concentration = NEUTRAL

            # 3. 杀号确定性：杀号数合理度（5-30 个为宜），偏离降分
            try:
                if isinstance(kill, (set, list, tuple)) and kill:
                    n = len(kill)
                    if 5 <= n <= 30:
                        kill_certainty = 80
                    elif n < 5:
                        kill_certainty = _clamp(40 + n * 8)
                    else:
                        kill_certainty = _clamp(80 - (n - 30) * 1.5)
                else:
                    kill_certainty = NEUTRAL
            except Exception:
                kill_certainty = NEUTRAL

            # 4. 多引擎共识：vote_mode 多方案一致度；无 vote 则按启用引擎数归一
            try:
                enabled = [k for k, v in (engine_states or {}).items() if v]
                if vote:
                    engine_consensus = 75
                elif enabled:
                    engine_consensus = _clamp(40 + len(enabled) * 6)
                else:
                    engine_consensus = NEUTRAL
            except Exception:
                engine_consensus = NEUTRAL

            # 5. 数据质量门槛：新鲜度 + 历史期数
            try:
                fm = Data.freshness_minutes(lot)
                if fm is None:
                    fresh_score = 60
                elif fm <= 1440:
                    fresh_score = 100
                elif fm <= 2880:
                    fresh_score = 70
                elif fm <= 4320:
                    fresh_score = 40
                else:
                    fresh_score = 20
                n_hist = len(arr) if arr else 0
                if n_hist >= 100:
                    hist_score = 100
                elif n_hist >= 50:
                    hist_score = _clamp(50 + (n_hist - 50) * 1.0)
                else:
                    hist_score = _clamp(n_hist * 1.0)
                data_quality = _clamp(0.6 * fresh_score + 0.4 * hist_score)
            except Exception:
                data_quality = NEUTRAL

            # 6. 多维参考特征覆盖度（来自 feature_engine，福彩3D/排列三）
            try:
                if isinstance(ref_features, dict) and ref_features.get("supported"):
                    feature_coverage = _clamp(ref_features.get("feature_coverage", NEUTRAL))
                else:
                    feature_coverage = NEUTRAL
            except Exception:
                feature_coverage = NEUTRAL

            # 7. 遗漏回补信号（启用之前传入但未使用的 miss_data）
            try:
                miss_signal = NEUTRAL
                if miss_data:
                    if isinstance(miss_data, dict):
                        al = miss_data.get("cold_alerts") or []
                        miss_signal = _clamp(50 + min(len(al), 5) * 10) if al else 55
                    else:
                        miss_signal = 55
            except Exception:
                miss_signal = NEUTRAL

            # 合成 SQI（多指标加权，权重和=1.0，诚实：仅信号清晰度+数据质量+多维覆盖）
            sqi = (0.18 * hurst_clarity + 0.15 * hot_concentration
                   + 0.12 * kill_certainty + 0.15 * engine_consensus
                   + 0.15 * data_quality + 0.13 * feature_coverage
                   + 0.12 * miss_signal)
            sqi = _clamp(sqi)
            # 数据质量门槛：差则强制降档
            if data_quality < 60:
                sqi = min(sqi, 40)

            if sqi >= 70:
                level = "strong"
            elif sqi >= 40:
                level = "medium"
            else:
                level = "weak"

            return {
                "score": sqi,
                "level": level,
                "signals": {
                    "hurst_clarity": hurst_clarity,
                    "hot_concentration": hot_concentration,
                    "kill_certainty": kill_certainty,
                    "engine_consensus": engine_consensus,
                    "data_quality": data_quality,
                    "feature_coverage": feature_coverage,
                    "miss_signal": miss_signal,
                },
                "note": "信号质量指数(SQI)：反映信号清晰度+数据质量+多维参考覆盖度，非中奖概率。已纳入遗漏/冷热/振幅等参考维度。彩票本质近随机。",
            }
        except Exception as e:
            self.log(f"⚠️ {lot} SQI 计算异常，降级为 unknown: {e}", "WARNING")
            return {
                "score": None,
                "level": "unknown",
                "signals": {},
                "note": "信号质量指数暂不可用（计算异常），不代表预测不可用。",
            }

    def _consult_knowledge(self, lot):
        """咨询知识库：按engine_hook查询经验卡片，生成选号调整系数

        Returns:
            dict: {"kill_factor": float, "hot_factor": float, "cold_factor": float, "cards_used": int}
        """
        adjustments = {"kill_factor": 1.0, "hot_factor": 1.0, "cold_factor": 1.0, "cards_used": 0}
        try:
            from knowledge.mirofish_db import MiroFishDB
            db = MiroFishDB()
            # 注意: MiroFishDB 无 cards 属性, 必须走 _data["cards"] (历史 bug: 用 db.cards 抛异常被吞, 导致知识库从未生效)
            if not db._data.get("cards"):
                return adjustments

            # 映射彩种到知识库domain
            domain_map = {"福彩3D": "3d", "排列三": "3d", "双色球": "lottery",
                          "大乐透": "lottery", "七乐彩": "lottery", "七星彩": "lottery", "快乐8": "lottery"}
            domain = domain_map.get(lot, "lottery")

            # 查询三类引擎钩子的卡片
            hook_map = {
                "kill_strategy": "kill_factor",
                "weight_calibration": "hot_factor",
                "miss_breakthrough": "cold_factor",
            }
            consulted = []
            for hook, factor_key in hook_map.items():
                cards = db.get_for_engine(hook, domain=domain, limit=3)
                if not cards:
                    cards = db.get_for_engine(hook, limit=3)  # 降级：不限domain
                if cards:
                    avg_eff = sum(c.get("effectiveness", 50) for c in cards) / len(cards)
                    # effectiveness 50=中性, >50=增强, <50=保守
                    # 范围映射到 0.8~1.2 的调整系数
                    factor = 0.8 + (avg_eff / 100) * 0.4
                    adjustments[factor_key] = round(factor, 3)
                    consulted.append(f"{hook}({len(cards)}张,eff={avg_eff:.0f})")
                    adjustments["cards_used"] += len(cards)
                    # 更新use_count
                    for c in cards:
                        c["use_count"] = c.get("use_count", 0) + 1

            if consulted:
                self.log(f"📚 {lot} 知识库咨询: {' | '.join(consulted)}")
                # 保存更新后的use_count
                try:
                    db.save()
                except Exception:
                    pass
        except Exception as e:
            logger.debug("知识库咨询失败(降级跳过): %s", e)
        return adjustments

    def _apply_brain_adjustments(self, lot, fg):
        """应用智能大脑号码修正"""
        if self.brain is not None:
            try:
                adj = self.brain.get_digit_adjustments(lot)
                if fg.final_hot:
                    for d, factor in adj.items():
                        if d in fg.final_hot:
                            fg.final_hot[d] *= factor
            except Exception:
                pass
