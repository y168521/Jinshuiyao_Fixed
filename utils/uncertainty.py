# -*- coding: utf-8 -*-
"""金水谣系统 - 不确定性量化模块 v1.0 (Conformal Uncertainty)

一句话定位
----------
金水谣现有引擎只输出"点预测 + 一个经验置信度"(smart_brain.confidence_history)，
那只是经验值，没有**校准保证**，也不知道区间有多宽。
本模块提供模型无关的**共形预测(Conformal Prediction)**工具，
在不假设数据分布的前提下，为任意基础预测器套上一层
"带理论覆盖保证的预测区间 / 预测集合"。

为什么需要它（对比全网优秀模型的关键缺口）
------------------------------------------
2026 年生产级预测系统（如 Moirai 2.0、Chronos-2、以及各类风险敏感系统）
都把"校准后的预测区间"作为一等公民：金融风控、供应链、能源调度
都依赖分布无关的覆盖保证，而不是一个拍脑袋的置信度。
金水谣此前缺失这一能力。

提供的能力
----------
1. SplitConformal        —— 同方差场景，分位数调整法（最简单、可证 1-α 覆盖）
2. NormalizedConformal  —— 异方差场景，用尺度模型把残差归一化后再共形
3. AdaptiveConformal    —— 在线/滚动场景，分布漂移时自动调整区间维持长期覆盖
4. ConformalClassifier  —— 分类任务，输出"预测集合"而非单点（含兜底不确定）
5. 指标                  —— empirical_coverage / MPIW / winkler_score / reliability

全部为纯标准库实现（不依赖 numpy/scipy），可在系统 Python 与 venv 双环境运行。

数学速览
--------
Split Conformal：
  校准集上算非一致性分数 s_i = |y_i - ŷ_i|
  取分位数 q = quantile(s, (⌈(n+1)(1-α)⌉)/n)
  新样本区间 C(x) = [ŷ(x) - q, ŷ(x) + q]
  → 在可交换性假设下，边际覆盖率 P(y∈C) ≥ 1-α（有限样本保证）。

Adaptive Conformal (Gibbs & Candès, 2021)：
  维护一个随分布漂移滚动更新的目标误覆盖率 α_t，
  长期误覆盖率以**无任何分布假设**的方式收敛到 α*。
"""
import math
import bisect
import logging
import random
from typing import Callable, List, Optional, Sequence, Tuple

logger = logging.getLogger("jinshuiyao.uncertainty")


# ---------------------------------------------------------------------------
# 纯标准库分位数（避免依赖 numpy）
# ---------------------------------------------------------------------------
def _quantile(sorted_vals: Sequence[float], level: float) -> float:
    """在已排序序列上做线性插值分位数。

    Args:
        sorted_vals: 升序排列的数值序列。
        level: 分位水平，0~1。
    Returns:
        分位数值；序列为空返回 0.0。
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    level = max(0.0, min(1.0, level))
    pos = level * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo]) * (1 - frac) + float(sorted_vals[hi]) * frac


def _sorted_scores(scores: Sequence[float]) -> List[float]:
    return sorted(float(s) for s in scores)


# ===========================================================================
# 1) Split Conformal（同方差）
# ===========================================================================
class SplitConformal:
    """分位数调整共形预测（同方差，最简单可用）。

    适用于预测误差方差大致恒定的场景（如多数彩票启发式、平稳序列）。
    """

    def __init__(self, alpha: float = 0.1):
        """
        Args:
            alpha: 误覆盖水平，区间目标覆盖率 = 1 - alpha（默认 0.9）。
        """
        if not (0.0 < alpha < 1.0):
            raise ValueError("alpha 必须介于 0 与 1 之间")
        self.alpha = float(alpha)
        self._q: float = 0.0
        self._cal_scores: List[float] = []
        self._fitted = False

    def calibrate(self, residuals: Sequence[float]) -> "SplitConformal":
        """用校准集残差（|y - ŷ|）拟合分位数。

        Args:
            residuals: 校准样本的绝对残差列表。
        Returns:
            self，便于链式调用。
        """
        scores = _sorted_scores(residuals)
        n = len(scores)
        if n == 0:
            raise ValueError("校准集不能为空")
        # 经典 split conformal 的分位位置：⌈(n+1)(1-α)⌉ / n
        level = (math.ceil((n + 1) * (1 - self.alpha))) / n
        self._q = _quantile(scores, level)
        self._cal_scores = scores
        self._fitted = True
        logger.info("SplitConformal 校准完成: n=%d, q=%.4f, 目标覆盖=%.2f",
                    n, self._q, 1 - self.alpha)
        return self

    def predict_interval(self, point: float) -> Tuple[float, float]:
        """返回点预测对应的预测区间 [lo, hi]。"""
        if not self._fitted:
            raise RuntimeError("请先调用 calibrate()")
        return (point - self._q, point + self._q)

    @property
    def quantile(self) -> float:
        return self._q


# ===========================================================================
# 2) Normalized Conformal（异方差）
# ===========================================================================
class NormalizedConformal:
    """归一化共形预测（异方差）。

    当误差方差随输入变化（如高销量商品波动更大）时，
    先用尺度模型 σ(x) 把残差归一化 s_i = |y_i - ŷ_i| / σ(x_i)，
    再在归一化分数上做共形，得到输入相关的区间宽度。

    若未提供 scale_fn，自动用 `EmpiricalScale` 按预测幅值分箱估计尺度。
    """

    def __init__(self, alpha: float = 0.1, scale_fn: Optional[Callable[[float], float]] = None):
        self.alpha = float(alpha)
        self.scale_fn = scale_fn
        self._q: float = 0.0
        self._fitted = False
        self._scale_model: Optional["EmpiricalScale"] = None

    def calibrate(self, points: Sequence[float], residuals: Sequence[float]) -> "NormalizedConformal":
        """用 (点预测, 绝对残差) 拟合。

        为保证共形覆盖的有效性，未提供 scale_fn 时采用**交叉拟合**：
        把校准集按奇偶拆两半，一半训尺度模型、另一半算归一化分数，
        再交换，合并分数用于分位校准；预测阶段使用全量训练的尺度模型。

        Args:
            points: 校准样本的点预测值（用于尺度估计）。
            residuals: 校准样本的绝对残差。
        """
        if len(points) != len(residuals) or len(points) == 0:
            raise ValueError("points 与 residuals 需等长且非空")
        pts = list(points)
        res = [abs(r) for r in residuals]

        if self.scale_fn is None:
            idx_a = list(range(0, len(pts), 2))
            idx_b = list(range(1, len(pts), 2))
            sc_a = EmpiricalScale(); sc_a.fit([pts[i] for i in idx_a], [res[i] for i in idx_a])
            sc_b = EmpiricalScale(); sc_b.fit([pts[i] for i in idx_b], [res[i] for i in idx_b])
            norm: List[float] = []
            for i in idx_a:
                norm.append(res[i] / max(sc_a.scale(pts[i]), 1e-9))
            for i in idx_b:
                norm.append(res[i] / max(sc_b.scale(pts[i]), 1e-9))
            # 预测用尺度模型：全量训练
            full = EmpiricalScale(); full.fit(pts, res)
            self._scale_model = full
            self.scale_fn = full.scale
        else:
            norm = [abs(r) / max(self.scale_fn(p), 1e-9) for p, r in zip(pts, res)]

        norm_sorted = _sorted_scores(norm)
        n = len(norm_sorted)
        level = (math.ceil((n + 1) * (1 - self.alpha))) / n
        self._q = _quantile(norm_sorted, level)
        self._fitted = True
        logger.info("NormalizedConformal 校准完成: n=%d, q=%.4f", n, self._q)
        return self

    def predict_interval(self, point: float) -> Tuple[float, float]:
        if not self._fitted:
            raise RuntimeError("请先调用 calibrate()")
        sigma = max(self.scale_fn(point), 1e-9)
        half = self._q * sigma
        return (point - half, point + half)


class EmpiricalScale:
    """极简经验尺度模型：按点预测幅值分箱，估计该区间的典型残差尺度。

    纯标准库、无需训练框架，足以让 NormalizedConformal 工作。
    若数据不足以分箱，则回退为全局中位数残差。
    """

    def __init__(self, n_bins: int = 5):
        self.n_bins = max(2, int(n_bins))
        self._edges: List[float] = []
        self._bin_scales: List[float] = []
        self._global: float = 1.0

    def fit(self, points: Sequence[float], residuals: Sequence[float]) -> "EmpiricalScale":
        pts = list(points)
        res = [abs(r) for r in residuals]
        if res:
            self._global = _quantile(sorted(res), 0.5) or 1.0
        if not pts:
            return self
        lo, hi = min(pts), max(pts)
        span = (hi - lo) or 1.0
        # 等宽分箱边界
        self._edges = [lo + span * i / self.n_bins for i in range(self.n_bins + 1)]
        buckets: List[List[float]] = [[] for _ in range(self.n_bins)]
        for p, r in zip(pts, res):
            idx = min(self.n_bins - 1, max(0, int((p - lo) / span * self.n_bins)))
            buckets[idx].append(r)
        self._bin_scales = []
        for b in buckets:
            if b:
                self._bin_scales.append(_quantile(sorted(b), 0.5) or self._global)
            else:
                self._bin_scales.append(self._global)
        return self

    def scale(self, point: float) -> float:
        """返回该点落入箱的经验残差尺度（随输入变化，支持异方差）。"""
        if not self._bin_scales:
            return max(self._global, 1e-9)
        i = bisect.bisect_left(self._edges, float(point))
        if i <= 0:
            idx = 0
        elif i >= len(self._edges):
            idx = len(self._bin_scales) - 1
        else:
            idx = i - 1
        return max(float(self._bin_scales[idx]), 1e-9)


# ===========================================================================
# 3) Adaptive Conformal（在线 / 分布漂移）
# ===========================================================================
class AdaptiveConformal:
    """自适应在线共形预测 (Gibbs & Candès, 2021)。

    维护滚动目标误覆盖率 α_t，在每一步根据是否"漏覆盖"调整：
        α_{t+1} = α_t + γ · (α* - 1{miss at t})
    长期误覆盖率以**无任何分布假设**的方式收敛到 α*。
    代价：保证是"长期"的，而非"逐点"的。

    适用于金水谣这类数据分布会缓慢漂移的场景（彩票/股票/赛事）。
    """

    def __init__(self, alpha: float = 0.1, gamma: float = 0.01, window: int = 50):
        """
        Args:
            alpha: 目标误覆盖水平 α*。
            gamma: 步长（学习率），越小越平滑。
            window: 滚动窗口大小，用于估计当前分位与记录历史。
        """
        self.alpha_star = float(alpha)
        self.gamma = float(gamma)
        self.window = max(1, int(window))
        self.alpha_t = float(alpha)
        self._scores: List[float] = []
        self._miss_history: List[int] = []

    def update(self, point: float, actual: float) -> Tuple[float, float]:
        """逐步更新并返回当前区间 [lo, hi]。

        调用顺序：每天拿到新真实值后调用一次（在线学习）。
        """
        # 1) 用当前窗口分数算区间（分数需排序后送 _quantile）
        if len(self._scores) >= max(2, self.window // 2):
            level = (math.ceil((len(self._scores) + 1) * (1 - self.alpha_t))) / len(self._scores)
            q = _quantile(sorted(self._scores), level)
        else:
            q = 0.0
        lo, hi = point - q, point + q

        # 2) 若已校准过，判断漏覆盖并调整 α_t
        miss = 0
        if len(self._scores) >= max(2, self.window // 2):
            miss = 1 if not (lo <= actual <= hi) else 0
            self.alpha_t = self.alpha_t + self.gamma * (self.alpha_star - miss)
            self.alpha_t = max(1e-3, min(0.9, self.alpha_t))
            self._miss_history.append(miss)

        # 3) 记录当前残差，维护滚动窗口
        self._scores.append(abs(actual - point))
        if len(self._scores) > self.window:
            self._scores.pop(0)
        return lo, hi

    @property
    def long_run_miscoverage(self) -> float:
        if not self._miss_history:
            return 0.0
        return sum(self._miss_history) / len(self._miss_history)


# ===========================================================================
# 4) Conformal Classifier（分类预测集合）
# ===========================================================================
class ConformalClassifier:
    """分类共形预测：输出"预测集合"而非单标签。

    用基础分类器的置信度（如 softmax 概率）作为非一致性分数，
    取分位阈值，保留所有分数 ≤ 阈值的类别，形成预测集合。
    集合很大 → 模型对自身不确定（可触发保守/人工兜底）。
    """

    def __init__(self, alpha: float = 0.1):
        self.alpha = float(alpha)
        self._threshold: float = 1.0
        self._fitted = False

    def calibrate(self, nonconf_scores: Sequence[float]) -> "ConformalClassifier":
        """nonconf_scores: 校准集上每个样本的非一致性分数（越大越不典型）。"""
        s = _sorted_scores(nonconf_scores)
        n = len(s)
        if n == 0:
            raise ValueError("校准集不能为空")
        level = (math.ceil((n + 1) * (1 - self.alpha))) / n
        self._threshold = _quantile(s, level)
        self._fitted = True
        return self

    def predict_set(self, class_scores: Sequence[float]) -> List[int]:
        """返回预测集合中的类别索引（分数 ≤ 阈值者入选）。"""
        if not self._fitted:
            raise RuntimeError("请先调用 calibrate()")
        return [i for i, sc in enumerate(class_scores) if sc <= self._threshold]


# ===========================================================================
# 5) 评估指标
# ===========================================================================
def empirical_coverage(intervals: Sequence[Tuple[float, float]], actuals: Sequence[float]) -> float:
    """经验覆盖率：真实值落在区间内的比例。"""
    n = len(actuals)
    if n == 0:
        return 0.0
    hit = sum(1 for (lo, hi), y in zip(intervals, actuals) if lo <= y <= hi)
    return hit / n


def mpiw(intervals: Sequence[Tuple[float, float]]) -> float:
    """平均预测区间宽度 (Mean Prediction Interval Width)。"""
    if not intervals:
        return 0.0
    return sum(hi - lo for lo, hi in intervals) / len(intervals)


def winkler_score(lo: float, hi: float, y: float, alpha: float = 0.1) -> float:
    """单点 Winkler 分数（区间越窄、漏覆盖惩罚越大越好）。"""
    if lo <= y <= hi:
        return (hi - lo)
    if y < lo:
        return (hi - lo) + 2.0 * (lo - y) / alpha
    return (hi - lo) + 2.0 * (y - hi) / alpha


def mean_winkler(intervals: Sequence[Tuple[float, float]], actuals: Sequence[float],
                 alpha: float = 0.1) -> float:
    if not intervals:
        return 0.0
    return sum(winkler_score(lo, hi, y, alpha) for (lo, hi), y in zip(intervals, actuals)) / len(intervals)


# ===========================================================================
# 自测
# ===========================================================================
def _self_test(seed: int = 42):
    import sys as _sys
    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))

    rng = random.Random(seed)

    # 造一组带噪声的回归数据：y = 2x + 噪声
    data = [(float(i), 2.0 * i + rng.gauss(0, 1.0)) for i in range(200)]
    calib, test = data[:100], data[100:]

    # --- Split Conformal ---
    sc = SplitConformal(alpha=0.1)
    sc.calibrate([abs(y - 2.0 * x) for x, y in calib])
    ivs, acts = [], []
    for x, y in test:
        lo, hi = sc.predict_interval(2.0 * x)
        ivs.append((lo, hi)); acts.append(y)
    cov = empirical_coverage(ivs, acts)
    logger.info("SplitConformal 经验覆盖=%.3f (目标0.90), MPIW=%.3f",
                cov, mpiw(ivs))
    assert 0.80 <= cov <= 1.0, f"覆盖率异常: {cov}"

    # --- Normalized Conformal（异方差：噪声随 x 增大，校准/测试同区间）---
    data2 = [(float(i), 2.0 * i + rng.gauss(0, 0.5 + i * 0.05)) for i in range(200)]
    c2 = [(x, y) for i, (x, y) in enumerate(data2) if i % 2 == 0]
    t2 = [(x, y) for i, (x, y) in enumerate(data2) if i % 2 == 1]
    nc = NormalizedConformal(alpha=0.1)
    nc.calibrate([x for x, _ in c2], [abs(y - 2.0 * x) for x, y in c2])
    ivs2, acts2 = [], []
    for x, y in t2:
        lo, hi = nc.predict_interval(2.0 * x)
        ivs2.append((lo, hi)); acts2.append(y)
    cov2 = empirical_coverage(ivs2, acts2)
    logger.info("NormalizedConformal 经验覆盖=%.3f", cov2)
    assert 0.80 <= cov2 <= 1.0

    # --- Adaptive Conformal ---
    ac = AdaptiveConformal(alpha=0.1, gamma=0.02, window=40)
    drift_acts = [2.0 * x + rng.gauss(0, 1.0 + 0.05 * (x - 100)) for x, _ in t2]
    ac_ivs = []
    for (x, _), y in zip(t2, drift_acts):
        lo, hi = ac.update(2.0 * x, y)
        ac_ivs.append((lo, hi))
    logger.info("AdaptiveConformal 长期误覆盖=%.3f (目标0.10)",
                ac.long_run_miscoverage)
    assert 0.0 <= ac.long_run_miscoverage <= 0.4

    # --- Classifier ---
    cc = ConformalClassifier(alpha=0.1)
    cc.calibrate([rng.random() for _ in range(100)])  # 分数越小越典型
    pred_set = cc.predict_set([0.02, 0.5, 0.9, 0.01])
    logger.info("ConformalClassifier 预测集合大小=%d", len(pred_set))
    assert len(pred_set) >= 1

    print("✅ uncertainty 自测通过：Split/Normalized/Adaptive/Classifier 全部 OK")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _self_test()
