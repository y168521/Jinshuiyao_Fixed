# -*- coding: utf-8 -*-
"""金水谣系统 - 概念漂移检测器 v1.0 (Concept Drift Detector)

一句话定位
----------
金水谣已有 `core/data_truth_guard.py` 负责"数据来源真实性/新鲜度"守卫，
但它只检查**数据是不是真的、是不是过期**，并不检测
**模型面对的分布是否悄悄变了**（概念漂移）。
本模块补齐这一环：用经典统计方法监控特征分布与预测残流的漂移，
在模型性能退化前给出预警。

为什么需要它（对比全网优秀模型的关键缺口）
------------------------------------------
2026 年可靠的预测系统在"数据漂移 → 模型退化"链条上必有监控：
PSI（群体稳定性指数）、KS 检验、CUSUM 控制图是业界标配。
金水谣此前只有 freshness 检查，缺失分布层面的漂移侦测。

提供的能力
----------
1. population_stability_index(ref, cur) —— PSI，整体分布漂移强度
2. ks_test(ref, cur)                   —— 两样本 Kolmogorov-Smirnov 检验（含渐近 p 值）
3. CUSUMDetector                        —— 在线残流均值漂移检测（控制图）
4. DriftReport                          —— 汇总各项，给出 severity 评级与可读文本

全部为纯标准库实现（不依赖 numpy/scipy）。

评级约定
--------
PSI:  <0.10 无显著漂移 | 0.10~0.25 中度漂移 | >0.25 重度漂移
KS :  p < 0.05 视为分布显著不同
CUSUM: 累计和突破控制限 h 即告警
"""
import math
import logging
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger("jinshuiyao.drift")


# ---------------------------------------------------------------------------
# 工具：分箱与经验分位
# ---------------------------------------------------------------------------
def _empirical_quantile(sorted_vals: Sequence[float], level: float) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    pos = max(0.0, min(1.0, level)) * (n - 1)
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo]) * (1 - frac) + float(sorted_vals[hi]) * frac


def _bin_edges(ref: Sequence[float], n_bins: int = 10) -> List[float]:
    """用参考样本的分位边界作为等频分箱边界。"""
    s = sorted(ref)
    n = len(s)
    if n == 0:
        return []
    edges = [_empirical_quantile(s, i / n_bins) for i in range(n_bins + 1)]
    # 去重并保序
    out = []
    for e in edges:
        if not out or e > out[-1]:
            out.append(e)
    # 保证至少 2 个边界
    if len(out) < 2:
        out = [s[0], s[-1]] if n >= 2 else [s[0] - 1.0, s[0] + 1.0]
    return out


def _bin_counts(vals: Sequence[float], edges: Sequence[float]) -> List[int]:
    counts = [0] * (len(edges) - 1)
    for v in vals:
        # 用 bisect 精确定位 v 落入的箱（edges 升序、无重复）
        i = _bisect_left(edges, v)
        if i <= 0:
            counts[0] += 1
        elif i >= len(edges):
            counts[-1] += 1
        else:
            counts[i - 1] += 1
    return counts


def _bisect_left(a: Sequence[float], x: float) -> int:
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ===========================================================================
# 1) Population Stability Index
# ===========================================================================
def population_stability_index(ref: Sequence[float], cur: Sequence[float],
                                n_bins: int = 10) -> float:
    """计算 PSI。

    PSI = Σ (actual% - expected%) · ln(actual% / expected%)

    Args:
        ref: 参考（基线）样本。
        cur: 当前（待检）样本。
        n_bins: 分箱数。
    Returns:
        PSI 值（≥0，越大漂移越强）。
    """
    edges = _bin_edges(ref, n_bins)
    if len(edges) < 2:
        return 0.0
    ref_counts = _bin_counts(ref, edges)
    cur_counts = _bin_counts(cur, edges)
    rtot = max(1, sum(ref_counts)); ctot = max(1, sum(cur_counts))
    psi = 0.0
    for rc, cc in zip(ref_counts, cur_counts):
        exp = rc / rtot
        act = cc / ctot
        # 平滑，避免 log(0)
        exp = max(exp, 1e-4)
        act = max(act, 1e-4)
        psi += (act - exp) * math.log(act / exp)
    return float(psi)


# ===========================================================================
# 2) Two-sample Kolmogorov-Smirnov test
# ===========================================================================
def _kolmogorov_cdf(t: float) -> float:
    """Kolmogorov 分布 CDF：Q_KS(t) = 1 - 2 Σ_{j≥1} (-1)^{j-1} e^{-2 j² t²}。"""
    if t <= 0:
        return 0.0
    # j=1 主导，5 项已足够精确
    s = 0.0
    for j in range(1, 12):
        s += ((-1) ** (j - 1)) * math.exp(-2.0 * (j ** 2) * (t ** 2))
    return max(0.0, min(1.0, 1.0 - 2.0 * s))


def ks_test(ref: Sequence[float], cur: Sequence[float]) -> Tuple[float, float]:
    """两样本 KS 检验。

    Returns:
        (D, p_value)：D 为经验分布最大距离；p 为渐近 p 值（大样本近似）。
    """
    a = sorted(float(x) for x in ref)
    b = sorted(float(x) for x in cur)
    na, nb = len(a), len(b)
    if na == 0 or nb == 0:
        return 0.0, 1.0
    i = j = 0
    D = 0.0
    while i < na and j < nb:
        d1 = a[i]; d2 = b[j]
        if d1 <= d2:
            i += 1
        else:
            j += 1
        fn1 = i / na
        fn2 = j / nb
        D = max(D, abs(fn1 - fn2))
    # 修正系数（提升小样本近似）
    en = math.sqrt((na * nb) / (na + nb))
    t = (en + 0.12 + 0.11 / en) * D
    p = 1.0 - _kolmogorov_cdf(t)
    return float(D), float(p)


# ===========================================================================
# 3) CUSUM online detector
# ===========================================================================
class CUSUMDetector:
    """累积和(CUSUM)在线漂移检测。

    监控一个数值流（如每日预测残差、命中率、特征均值）。
    当流均值相对基线发生持续偏移且累计和突破控制限 h 时告警。

    适用于金水谣这类"每天产生一批预测/回测分数"的节奏。
    """

    def __init__(self, baseline: Sequence[float], k: Optional[float] = None,
                 h: Optional[float] = None):
        """
        Args:
            baseline: 基线样本，用于估计均值/标准差。
            k: 允许偏移（allowance），默认 0.5·σ。
            h: 控制限（decision interval），默认 5·σ。
        """
        base = [float(x) for x in baseline]
        if not base:
            raise ValueError("baseline 不能为空")
        self.target = sum(base) / len(base)
        self.sd = math.sqrt(sum((x - self.target) ** 2 for x in base) / len(base)) or 1e-9
        self.k = float(k) if k is not None else 0.5 * self.sd
        self.h = float(h) if h is not None else 5.0 * self.sd
        self._c_plus = 0.0
        self._c_minus = 0.0

    def update(self, value: float) -> dict:
        """喂入一个新观测，返回状态字典。"""
        diff = float(value) - self.target
        self._c_plus = max(0.0, self._c_plus + (diff - self.k))
        self._c_minus = max(0.0, self._c_minus + (-diff - self.k))
        alert = self._c_plus > self.h or self._c_minus > self.h
        direction = "up" if self._c_plus > self.h else ("down" if self._c_minus > self.h else "none")
        return {
            "value": float(value),
            "c_plus": self._c_plus,
            "c_minus": self._c_minus,
            "alert": alert,
            "direction": direction,
        }

    def reset(self):
        self._c_plus = 0.0
        self._c_minus = 0.0


# ===========================================================================
# 4) Drift Report
# ===========================================================================
def evaluate_drift(ref: Sequence[float], cur: Sequence[float],
                   n_bins: int = 10) -> dict:
    """对一组特征/残流同时跑 PSI 与 KS，给出汇总报告。"""
    psi = population_stability_index(ref, cur, n_bins)
    D, p = ks_test(ref, cur)
    if psi > 0.25 or p < 0.01:
        severity = "high"
    elif psi > 0.10 or p < 0.05:
        severity = "medium"
    else:
        severity = "low"
    return {
        "psi": round(psi, 4),
        "ks_statistic": round(D, 4),
        "ks_pvalue": round(p, 4),
        "severity": severity,
        "text": f"PSI={psi:.3f}, KS D={D:.3f}(p={p:.3f}) → 漂移等级:{severity}",
    }


# ===========================================================================
# 自测
# ===========================================================================
def _self_test(seed: int = 7):
    import sys as _sys
    from pathlib import Path
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))

    rng = random.Random(seed)  # noqa: F821  (见下方 import)

    # 同一分布 → 应判定无/低漂移
    ref = [rng.gauss(0, 1) for _ in range(300)]
    cur_same = [rng.gauss(0, 1) for _ in range(300)]
    r1 = evaluate_drift(ref, cur_same)
    logger.info("同分布: %s", r1["text"])
    assert r1["severity"] in ("low", "medium")

    # 明显偏移分布 → 应判定高漂移
    cur_shift = [rng.gauss(3, 1) for _ in range(300)]
    r2 = evaluate_drift(ref, cur_shift)
    logger.info("偏移分布: %s", r2["text"])
    assert r2["severity"] == "high"

    # CUSUM：基线平稳，之后持续上移 → 应告警
    base = [rng.gauss(10, 1) for _ in range(50)]
    cusum = CUSUMDetector(base)
    alerts = 0
    for _ in range(30):
        st = cusum.update(rng.gauss(10, 1))
        alerts += 1 if st["alert"] else 0
    assert alerts == 0, f"平稳期不应告警: {alerts}"
    for _ in range(40):
        st = cusum.update(rng.gauss(16, 1))  # 均值 +6σ 持续偏移
        alerts += 1 if st["alert"] else 0
    logger.info("CUSUM 告警次数=%d", alerts)
    assert alerts > 0, "持续偏移应触发 CUSUM 告警"

    print("✅ drift_detector 自测通过：PSI/KS/CUSUM 全部 OK")
    return True


if __name__ == "__main__":
    import random  # 自测专用
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    _self_test()
