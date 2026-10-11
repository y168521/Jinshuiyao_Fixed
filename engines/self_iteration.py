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
import sys
import json
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


def _lag_baseline_path(pred_file):
    """学习滞后基线文件路径（与 pred_file 同级的 log/ 目录下）。

    与 code_health_baseline.json / archive_baseline.json 同等惯例：
    基线类持久化放在 log/ 下，便于入仓与跨会话共享。
    """
    return os.path.join(os.path.dirname(pred_file) or ".", "log",
                        "learning_lag_baseline.json")


def _load_lag_baseline(pred_file):
    """读已锁定的存量欠账基线；不存在/损坏返回 None。

    **基线必须显式创建，绝不自动锁定**（JS-20261012-04）：
    自动锁定会把「首次出现的真故障」当成存量基线吃掉——第一次见到 lag=50
    时无法判断它是历史欠账还是刚断的链路，自动锁就等于永久放过它。
    只有人工取证确认「这是存量欠账」后才写入基线文件。
    返回 None 时 probe_linkage 行为与改造前完全一致（lag>0 即失配）。
    """
    path = _lag_baseline_path(pred_file)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        v = data.get("baseline") if isinstance(data, dict) else None
        return int(v) if isinstance(v, (int, float)) else None
    except Exception as e:
        # 读不出来按「无基线」处理 —— 退化方向是继续报警，不是静默放行
        logger.warning("学习滞后基线读取失败，按无基线处理（继续报警）: %s (%s)", path, e)
        return None


def _save_lag_baseline(pred_file, value):
    """落盘基线（仅在欠账被消化、水位下降时调用）。失败只告警，不影响探测。"""
    path = _lag_baseline_path(pred_file)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"baseline": int(value),
                       "updated_at": datetime.now().isoformat(timespec="seconds")},
                      f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning("学习滞后基线落盘失败（不影响探测）: %s (%s)", path, e)
        return False


def _count_reviewed(pred_file):
    """统计 predictions.json 中已复盘的记录数（兼容 list / dict 两种格式）。"""
    try:
        from utils.safe_json import safe_load_json
        data = safe_load_json(pred_file, default=None)
    except Exception as e:
        # JS-20261012-04：这里的 except 曾**完全静默**——CLI 直跑本模块时
        # sys.path[0] 是 engines/，`utils` 包导入失败被吞成 return 0，
        # 于是「学习滞后」被算成 0（假健康）。若拿这个 0 去 lock-baseline，
        # 基线会被锁成 0，之后任何滞后都变成「新增」，告警反而天天响。
        # 静默才是真敌人：读不出来必须留痕，让假健康信号无处藏身。
        logger.warning("统计已复盘记录失败，按 0 处理（学习滞后会被低估）: %s (%s: %s)",
                       pred_file, type(e).__name__, e)
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

    # ── 存量欠账基线（JS-20261012-04）──
    # learning_lag 是「已复盘 − 已学习」的**差值**。若分子分母同步增长，
    # 差值恒定不变却仍被判「失配 + 空转风险」，于是每天喊狼来了。
    # 实测该值自 2026-10-03 起恒为 3369（2026-09-24 批量回填 3202 条留下的
    # 历史欠账），同期 learned 每轮都在涨 —— 学习链路正常，是告警口径错了。
    # 故：失配/空转只由**相对基线的增量**判定；存量部分照常披露但不计失配。
    baseline = _load_lag_baseline(pred_file)
    if baseline is None:
        lag_delta = learning_lag        # 无基线：行为与改造前一致
    else:
        lag_delta = learning_lag - baseline
        if lag_delta < 0:
            # 欠账被消化（水位下降）→ 认下这个新低水位，避免用旧的高基线虚报
            _save_lag_baseline(pred_file, learning_lag)
            lag_delta = 0

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
    if lag_delta > 0:
        if baseline is None:
            notes.append("学习滞后 %d 条（有复盘记录未进入大脑）" % learning_lag)
        else:
            notes.append("学习滞后新增 %d 条（存量基线 %d → 当前 %d）："
                         "新增的复盘未进入大脑" % (lag_delta, baseline, learning_lag))
    elif learning_lag > 0:
        # 存量欠账：如实披露数字，但明确标注不计失配（避免常驻假警）
        notes.append("学习滞后 %d 条（均属已锁定的存量基线，本轮无新增，"
                     "不计失配）" % learning_lag)
    if decision_stale:
        notes.append("决策陈旧（数据文件比大脑状态新）")
    if knowledge_stale_days is not None and knowledge_stale_days > KNOWLEDGE_STALE_DAYS:
        notes.append("知识陈旧（%d 天未更新）" % knowledge_stale_days)

    # 失配/空转只看**增量**：存量欠账不构成失配，否则告警永远变不了绿
    mismatch_detected = bool(lag_delta > 0 or decision_stale
                             or (knowledge_stale_days is not None
                                 and knowledge_stale_days > KNOWLEDGE_STALE_DAYS))
    spin_risk = bool(lag_delta > LEARNING_LAG_SPIN_THRESHOLD)

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


# ══════════════════════════════════════════════════════════════════
# 存量欠账基线的显式锁定入口（JS-20261012-04）
#
# 为什么必须是显式命令：基线若由探测过程自动创建，第一次出现的真故障
# （比如学习链路刚断、lag 从 0 跳到 50）会被当成「存量基线」吃掉，
# 从此再也不报警。所以只有人工取证确认「这笔欠账是历史存量」后才落基线。
#
# 用法：
#   python engines/self_iteration.py lock-baseline [数据目录]
#   python engines/self_iteration.py show-baseline [数据目录]
# ══════════════════════════════════════════════════════════════════
def current_lag(pred_file):
    """只读算出当前学习滞后条数；读不出状态按 0 处理（保守：不夸大欠账）。"""
    total = _count_reviewed(pred_file)
    state_file = os.path.join(os.path.dirname(pred_file) or ".", "brain_state.json")
    learned = 0
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            st = json.load(f)
        v = st.get("learned_review_count")
        if v is None:
            v = st.get("total_reviews", 0)
        learned = int(v)
    except Exception as e:
        logger.warning("读取大脑状态失败，按已学习 0 条处理: %s (%s)", state_file, e)
    return max(0, total - learned)


def lock_lag_baseline(pred_file):
    """把「当前 lag」显式锁定为存量基线。返回 (ok, value)。"""
    lag = current_lag(pred_file)
    return _save_lag_baseline(pred_file, lag), lag


def _default_pred_file():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "金水谣数据", "predictions.json")


def _cli(argv):
    cmd = argv[0] if argv else "help"
    data_dir = argv[1] if len(argv) > 1 else None
    pred_file = (os.path.join(data_dir, "predictions.json") if data_dir
                 else _default_pred_file())
    if cmd == "lock-baseline":
        ok, lag = lock_lag_baseline(pred_file)
        print("[lag-baseline] %s 锁定存量基线 = %d 条（路径 %s）" % (
            "已" if ok else "未能", lag, _lag_baseline_path(pred_file)))
        return 0 if ok else 1
    if cmd == "show-baseline":
        b = _load_lag_baseline(pred_file)
        print("[lag-baseline] 当前滞后=%d 已锁基线=%s" % (
            current_lag(pred_file), "无" if b is None else b))
        return 0
    print(__doc__ or "用法: lock-baseline | show-baseline [数据目录]")
    return 1


if __name__ == "__main__":
    # 直跑本模块时 sys.path[0] 是 engines/，会导致 `utils` 等包导入失败，
    # 进而让 _count_reviewed 静默返回 0（假健康）。先把项目根补进 sys.path。
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.exit(_cli(sys.argv[1:]))
