# -*- coding: utf-8 -*-
"""智能大脑「自迭代核心逻辑」——感知→推理→决策 闭环守卫

设计目标（对应用户诉求：链路失配检测 / 知识陈旧检测 / 不空转 / 越用越聪明）

一、为什么需要这个模块
    智能大脑的学习链路是分阶段落盘的：
        感知(采集开奖结果 → 复盘回写 predictions.json)
          → 推理(brain.learn_from_review 更新 brain_state.json)
            → 决策(生成预测时读取 digit_bias / strategy_weights)
    这三个阶段由**不同进程/不同实例**完成（调度器定时任务、GUI 手动复盘、
    prediction_service 长生命周期单例）。只要任一环节没跟上，后面的环节就会
    拿着旧状态继续跑 —— 表现为「系统每天照常出预测，但从不进步」，
    且日志一切正常、没有任何报错。这是最难发现的故障：它不报错，只是静默地
    停止进化。本模块把这种「静默停摆」变成**可观测、可告警**的状态。

二、三项能力
    1. probe_linkage()   —— 检测链路失配与知识/数据陈旧（只读探测，不改数据）
    2. run_self_iteration() —— 编排「采集→学习→刷新→知识更新→闭环验证」
    3. LEARNING_LAG_SPIN_THRESHOLD —— 「反复空转」判定阈值（模块级常量）

三、诚实约束
    本模块只做**记账式**的链路检测（有没有学到最新的数据），
    不对「预测准不准」作任何判断。彩票本质是随机事件，
    系统能承诺的只有「学全了、没停摆」，不能承诺「学了就更准」。
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── 阈值（模块级常量，便于闸门/单测校验，与标准真源 §三 对齐） ──
# 学习滞后超过该条数 → 判定系统正在「反复用旧数据空转」
LEARNING_LAG_SPIN_THRESHOLD = 10
# 知识卡超过该天数未更新 → 判定知识陈旧
KNOWLEDGE_STALE_DAYS = 30


class LinkageStatus:
    """感知→推理→决策 链路健康快照（纯数据，可序列化）。"""

    def __init__(self, total_reviewed, learning_lag, decision_stale,
                 knowledge_stale_days, mismatch_detected, spin_risk, notes):
        self.total_reviewed = total_reviewed
        self.learning_lag = learning_lag
        self.decision_stale = decision_stale
        self.knowledge_stale_days = knowledge_stale_days
        self.mismatch_detected = mismatch_detected
        self.spin_risk = spin_risk
        self.notes = notes or []

    def to_dict(self):
        return {
            "total_reviewed": self.total_reviewed,
            "learning_lag": self.learning_lag,
            "decision_stale": self.decision_stale,
            "knowledge_stale_days": self.knowledge_stale_days,
            "mismatch_detected": self.mismatch_detected,
            "spin_risk": self.spin_risk,
            "notes": list(self.notes),
        }

    def __repr__(self):
        return ("LinkageStatus(学习滞后=%d, 决策陈旧=%s, 知识陈旧天数=%s, "
                "失配=%s, 空转风险=%s)" % (
                    self.learning_lag, self.decision_stale,
                    self.knowledge_stale_days, self.mismatch_detected,
                    self.spin_risk))


def _count_reviewed(pred_file):
    """统计 predictions.json 中已复盘的记录数（兼容 list / dict 两种格式）。"""
    try:
        from utils.safe_json import safe_load_json
        data = safe_load_json(pred_file, default=None)
    except Exception:
        return 0
    if not data:
        return 0
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if "predictions" in data and isinstance(data["predictions"], dict):
            for _lot, group in data["predictions"].items():
                if isinstance(group, list):
                    items.extend(group)
        elif isinstance(data.get("records"), list):
            items = data["records"]
    return sum(1 for p in items
               if isinstance(p, dict) and p.get("reviewed"))


def _mtime(path):
    try:
        return os.path.getmtime(path) if os.path.isfile(path) else 0.0
    except OSError:
        return 0.0


def probe_linkage(brain, data_dir=None, knowledge_cards=None):
    """检测链路失配与知识/数据陈旧（只读探测，绝不修改任何数据）。

    判定口径：
      - 学习滞后 learning_lag = 已复盘记录数 − 大脑已学习记录数
        >0 说明「感知到了新数据，推理没跟上」→ 链路失配
      - 决策陈旧 decision_stale = predictions.json 比 brain_state.json 新
        说明「推理还没追上最新数据，决策就会用旧状态」→ 链路失配
      - 空转风险 spin_risk = 学习滞后超过阈值
        （不是偶发一两条落后，而是持续落后 → 系统已停止进化）

    Args:
        brain: SmartBrain 实例
        data_dir: 数据目录（默认取 brain.pred_file 所在目录）
        knowledge_cards: 可选，知识卡列表（含 last_updated 字段）用于陈旧检测

    Returns:
        LinkageStatus
    """
    pred_file = brain.pred_file
    if data_dir:
        pred_file = os.path.join(data_dir, "predictions.json")
    state_file = os.path.join(os.path.dirname(pred_file), "brain_state.json")

    total_reviewed = _count_reviewed(pred_file)
    learned = brain.state.get("learned_review_count")
    if learned is None:
        learned = brain.state.get("total_reviews", 0)
    learning_lag = max(0, total_reviewed - int(learned))

    pred_mt = _mtime(pred_file)
    state_mt = _mtime(state_file)
    decision_stale = bool(pred_mt and state_mt and pred_mt > state_mt)
    if state_mt == 0.0 and pred_mt > 0:
        decision_stale = True

    knowledge_stale_days = None
    if knowledge_cards:
        ages = []
        for c in knowledge_cards:
            ts = c.get("last_updated") if isinstance(c, dict) else None
            if not ts:
                continue
            try:
                ages.append((datetime.now() - datetime.fromisoformat(str(ts))).days)
            except Exception:
                continue
        if ages:
            knowledge_stale_days = max(ages)

    notes = []
    if learning_lag > 0:
        notes.append("学习滞后 %d 条（有复盘记录未进入大脑）" % learning_lag)
    if decision_stale:
        notes.append("决策陈旧（数据文件比大脑状态新）")
    if knowledge_stale_days is not None and knowledge_stale_days > KNOWLEDGE_STALE_DAYS:
        notes.append("知识陈旧（%d 天未更新）" % knowledge_stale_days)

    mismatch_detected = bool(learning_lag > 0 or decision_stale
                             or (knowledge_stale_days is not None
                                 and knowledge_stale_days > KNOWLEDGE_STALE_DAYS))
    spin_risk = bool(learning_lag > LEARNING_LAG_SPIN_THRESHOLD)

    if not notes:
        notes.append("链路同步（已复盘 %d 条全部纳入大脑）" % total_reviewed)

    return LinkageStatus(
        total_reviewed=total_reviewed,
        learning_lag=learning_lag,
        decision_stale=decision_stale,
        knowledge_stale_days=knowledge_stale_days,
        mismatch_detected=mismatch_detected,
        spin_risk=spin_risk,
        notes=notes,
    )


def run_self_iteration(data_dir, review_fn=None, knowledge_refresh_fn=None):
    """编排一次完整的自我迭代：采集 → 学习 → 刷新 → 知识更新 → 闭环验证。

    四个阶段对应「感知 → 推理 → 知识 → 决策闭环验证」：
      1. review_fn            感知/采集：复盘回写（由调用方注入，复用调度器
                              或 domain 的复盘口径，本模块不重复实现）
      2. SmartBrain 重建+刷新  推理：载入最新学习成果
      3. knowledge_refresh_fn  知识：提炼/更新知识卡
      4. probe_linkage         验证：重新探测，确认闭环已闭合

    Args:
        data_dir: 数据目录
        review_fn: 可选，执行复盘回写的函数（返回 dict，含 reviews 数量）
        knowledge_refresh_fn: 可选，执行知识卡更新的函数

    Returns:
        dict: 迭代报告（含 before/after 链路状态，用于判断是否已闭合）
    """
    report = {
        "data_dir": data_dir,
        # None = 未知（复盘阶段未同步等待/未提供条数）。
        # 绝不用 -1 之类的哨兵数字占位——那会被日志打成「复盘-1条」，
        # 读日志的人要么以为复盘失败，要么以为真复盘了负一条。
        # JS-20261002-20。
        "reviews": None,
        "learned": False,
        "knowledge_updated": False,
        "review_error": None,
        "knowledge_error": None,
        "before": None,
        "after": None,
    }

    from engines.smart_brain import SmartBrain

    # ── 1. 感知：采集新数据并复盘回写 ──
    if review_fn is not None:
        try:
            res = review_fn() or {}
            # None = 调用方未提供条数（未知），保持 None 而不填 0，
            # 避免把「没数」伪装成「复盤了 0 条」
            report["reviews"] = res.get("reviews")
        except Exception as e:
            report["review_error"] = str(e)
            logger.warning("[自迭代] 复盘阶段失败(降级继续): %s", e)

    # ── 2. 推理：重建大脑并刷新历史（跨实例拿到最新学习成果） ──
    try:
        brain = SmartBrain(data_dir)
        brain.refresh_history()
        report["before"] = probe_linkage(brain, data_dir).to_dict()
        report["learned"] = True
    except Exception as e:
        logger.warning("[自迭代] 大脑刷新失败: %s", e)
        brain = None

    # ── 3. 知识：更新/提炼知识卡 ──
    if knowledge_refresh_fn is not None:
        try:
            knowledge_refresh_fn()
            report["knowledge_updated"] = True
        except Exception as e:
            report["knowledge_error"] = str(e)
            logger.warning("[自迭代] 知识更新失败(降级继续): %s", e)

    # ── 4. 决策闭环验证：重新探测 ──
    try:
        verify_brain = brain if brain is not None else SmartBrain(data_dir)
        report["after"] = probe_linkage(verify_brain, data_dir).to_dict()
    except Exception as e:
        logger.warning("[自迭代] 闭环验证失败: %s", e)

    after = report.get("after") or {}
    reviews = report["reviews"]
    # 未知就写「未知」，绝不写 -1 之类的魔数（JS-20261002-20）
    reviews_txt = "未知" if reviews is None else str(reviews)
    logger.info("[自迭代] 完成: 复盘%s条 / 学习=%s / 知识更新=%s / "
                "失配=%s / 学习滞后=%s",
                reviews_txt, report["learned"], report["knowledge_updated"],
                after.get("mismatch_detected"), after.get("learning_lag"))
    return report
