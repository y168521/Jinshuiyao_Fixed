# -*- coding: utf-8 -*-
"""【道衍推导·JS-20260727-24】
  阴阳：阳=严格前向回测(主动证伪)；阴=命中判定复用引擎(守底，杜绝任中1码即算命中)。
  天地人：天=规划诚实基准；地=隔离(独立进程不扰server)；人=复盘(随机基准钉死噪音)。
  知止：彩票无预测力是定论，只优化诚实度+风控，禁再造选号"规律"。

诚实 walk-forward 回测（修复后干净数据）

用真实 PredictionService 做严格前向回测：
  - 对每期 i，仅用 history[:i]（不含目标期）喂给预测引擎；
  - 通过临时覆盖 Data 的 load/latest/has_period，让引擎“以为”当前数据就是训练集，
    从而预测第 i 期；再与真实开奖 i 比对。
  - 命中判定复用 backtesting.engine.BacktestEngine._evaluate_hit
    （3D 直选/组选精确匹配；双色球等按红球数分奖级），杜绝“任中1码即算命中”失真。

与运行中的 server 是独立进程，互不干扰。
"""
import os
import sys
import json
import time
import random
import contextlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import LOT_ALL, LOTTERY_RULES  # noqa: E402
from models.lottery_data import Data  # noqa: E402
from backtesting.engine import BacktestEngine  # noqa: E402
from engines.prediction_service import PredictionService  # noqa: E402
from engines.killer import Killer  # noqa: E402
from engines.evolve import Evolve  # noqa: E402

ENGINE_STATES = {"hurst": True, "morph": True, "correlation": True,
                 "cold_tunnel": True, "antikill": True, "killcheck": False}

# 各彩种“小奖”红球阈值（用于多球种命中判定）
MIN_HIT = {"福彩3D": 3, "排列三": 3, "七星彩": 3, "双色球": 3, "大乐透": 3,
           "七乐彩": 3, "快乐8": 5}

# 回测数据新鲜的彩种（动态检测，替代旧硬编码白名单 FRESH_LOTS）
# 旧白名单只含 ["排列三","福彩3D","七乐彩","快乐8"]，误排七星彩/双色球/大乐透
# —— JS-20260724-03 修正：P0-3 已修复 time 字段，3彩种数据实际新鲜，应纳入回测
FRESH_THRESHOLD_MIN = 1440  # 24 小时内有更新视为新鲜
WINDOW = 60  # 回测最近 N 期
RAND_REPS = 100  # 每个预测槽的随机基准重复次数（求期望，降方差）


def _rand_ticket(lot, pred_str, eng):
    """生成与该预测“同规格”的随机注单字符串（可被 _evaluate_hit 解析）。

    - 数字型(3D/排列三/七星彩)：按预测位数生成同位数随机数字(允许重复，含组三形态)；
    - 球型(双色球/大乐透/七乐彩/快乐8)：按预测的红/蓝球个数从对应号池不重复抽样，
      格式 "r1,r2,..+b1,b2"（无蓝球则仅红球），与 _split_balls 解析口径一致。
    随机注单与真实预测结构完全一致→套同一 _evaluate_hit 得到 apples-to-apples 随机基准。
    """
    rule = LOTTERY_RULES.get(lot, {})
    if lot in ("福彩3D", "排列三", "七星彩"):
        red = rule.get("red") or (0, 9, 3)
        lo, hi = red[0], red[1]
        n = len(eng._parse_numbers(pred_str)) or red[2]
        return "".join(str(random.randint(lo, hi)) for _ in range(n))
    reds, blues = eng._split_balls(pred_str)
    red = rule.get("red") or (1, 33, 6)
    rlo, rhi = red[0], red[1]
    rn = min(len(reds) or red[2], rhi - rlo + 1)
    r = random.sample(range(rlo, rhi + 1), rn)
    blue = rule.get("blue")
    bn = len(blues) or (blue[2] if blue else 0)
    if blue and bn:
        blo, bhi = blue[0], blue[1]
        bn = min(bn, bhi - blo + 1)
        b = random.sample(range(blo, bhi + 1), bn)
        return ",".join(map(str, r)) + "+" + ",".join(map(str, b))
    return ",".join(map(str, r))


@contextlib.contextmanager
def override_lot(lot, records):
    """临时让 Data 对指定彩种只看到 records（walk-forward 训练集）。"""
    orig_load = Data.load
    orig_latest = Data.latest
    orig_has = Data.has_period
    try:
        Data.load = staticmethod(lambda name: records if name == lot else orig_load(name))
        Data.latest = staticmethod(
            lambda name: max((x.get("period", 0) for x in records), default=0) if name == lot else orig_latest(name))
        Data.has_period = staticmethod(
            lambda name, p: any(x.get("period") == p for x in records) if name == lot else orig_has(name, p))
        yield
    finally:
        Data.load = orig_load
        Data.latest = orig_latest
        Data.has_period = orig_has


def honest_backtest(lot, window=WINDOW):
    full = Data.load(lot)
    if len(full) < 20:
        return {"lot": lot, "error": "历史不足", "total_tests": 0, "hits": 0, "hit_rate": 0.0}
    start = max(10, len(full) - window)
    killer = Killer()
    evolve = Evolve()
    svc = PredictionService(killer=killer, evolve=evolve, brain=None,
                            engine_states=ENGINE_STATES, hot_window=50)
    eng = BacktestEngine()
    min_hit = MIN_HIT.get(lot, 3)
    hits = 0
    total = 0
    tier_counter = {}
    rand_hit_expect = 0.0  # 各预测槽随机基准命中概率之和（期望命中注数）
    for i in range(start, len(full)):
        target = full[i]
        train = full[:i]
        with override_lot(lot, train):
            try:
                res = svc.generate(lot, per_value=target.get("period"))
            except Exception as e:
                continue
        if not res.get("success"):
            continue
        preds = res.get("all_nums", [])
        actual = target.get("nums", "")
        for p in preds:
            is_hit, tier = eng._evaluate_hit(lot, p, actual, min_hit)
            total += 1
            if is_hit:
                hits += 1
                tier_counter[tier] = tier_counter.get(tier, 0) + 1
            # 随机基准：同规格随机注单对同一开奖跑 RAND_REPS 次求命中期望
            rh = 0
            for _ in range(RAND_REPS):
                rt = _rand_ticket(lot, p, eng)
                r_hit, _ = eng._evaluate_hit(lot, rt, actual, min_hit)
                if r_hit:
                    rh += 1
            rand_hit_expect += rh / RAND_REPS
    hit_rate = round(hits / total, 4) if total else 0.0
    rand_rate = round(rand_hit_expect / total, 4) if total else 0.0
    gain = round(hit_rate - rand_rate, 4)
    return {
        "lot": lot,
        "total_tests": total,
        "hits": hits,
        "hit_rate": hit_rate,
        "random_baseline_rate": rand_rate,
        "gain": gain,
        "gain_verdict": _gain_verdict(gain, total),
        "tiers": tier_counter,
        "min_hit": min_hit,
        "window": window,
        "rand_reps": RAND_REPS,
    }


def _gain_verdict(gain, total):
    """把 gain 翻译成人类可读的诚实结论（含小样本噪声提示）。"""
    if not total:
        return "无有效样本"
    # 小样本(总注数<200)下 gain 的标准误较大，|gain|<0.02 视为噪声内
    if abs(gain) < 0.02:
        return "≈随机（无预测力，gain 落在噪声区间内）"
    if gain >= 0.02:
        return f"高于随机 {gain:+.2%}（需更大样本复核，谨防幸存者偏差）"
    return f"低于随机 {gain:+.2%}（跑输随机=选号规则起了反作用）"


def main():
    # 动态检测数据新鲜度（替代旧硬编码白名单）—— JS-20260724-03
    lots = [l for l in LOT_ALL if Data.is_fresh(l, threshold_min=FRESH_THRESHOLD_MIN)]
    stale = [l for l in LOT_ALL if l not in lots]
    print(f"诚实回测（walk-forward，最近 {WINDOW} 期）：{lots}")
    if stale:
        print(f"跳过 STALE 彩种（数据不新鲜）：{stale}")
    out = {}
    for lot in lots:
        t0 = time.time()
        r = honest_backtest(lot)
        out[lot] = r
        print(f"  {lot}: 命中率={r['hit_rate']:.2%} vs 随机={r['random_baseline_rate']:.2%} "
              f"gain={r['gain']:+.2%} [{r['gain_verdict']}] "
              f"({r['hits']}/{r['total_tests']}) 奖级={r.get('tiers')} "
              f"({time.time()-t0:.1f}s)")
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"backtest_honest_{ts}.json"
    path = os.path.join(ROOT, "金水谣数据", "backtest_results", fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已写出: {path}")
    _sync_health_report(out, fname)
    return out


def _sync_health_report(out, source_file):
    """把随机基准 gain 合并回 lottery_health_report.json 的 backtest_latest。

    仅更新本轮实际回测到的彩种，保留 freshness_gate/lot_data_health 等其他字段。
    """
    hp_path = os.path.join(ROOT, "金水谣数据", "lottery_health_report.json")
    try:
        with open(hp_path, "r", encoding="utf-8") as f:
            hp = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] 无法读取 health_report，跳过同步: {e}")
        return
    latest = hp.get("backtest_latest", {})
    for lot, r in out.items():
        if r.get("total_tests", 0) <= 0:
            continue
        node = latest.get(lot, {})
        node.update({
            "total_tests": r["total_tests"],
            "hits": r["hits"],
            "hit_rate": r["hit_rate"],
            "random_baseline_rate": r["random_baseline_rate"],
            "gain": r["gain"],
            "gain_verdict": r["gain_verdict"],
            "tiers": r.get("tiers", {}),
            "min_hit": r["min_hit"],
            "window": r["window"],
            "source_file": source_file,
            "honest": True,
        })
        latest[lot] = node
    hp["backtest_latest"] = latest
    hp["generated"] = time.strftime("%Y-%m-%d")
    cal = hp.setdefault("backtest_caliber", {})
    cal["honest_baseline_source"] = source_file
    cal["random_baseline_method"] = (
        f"随机基准：对每个预测生成同规格随机注单，套用相同 _evaluate_hit 判定，"
        f"每槽重复 {RAND_REPS} 次求命中期望；gain=命中率−随机命中率，应≈0（无预测力）。")
    if abs(hp.get("avg_coverage", 0)) >= 0:
        rates = [v.get("hit_rate", 0) for v in latest.values() if v.get("total_tests")]
        gains = [v.get("gain", 0) for v in latest.values() if v.get("total_tests")]
        if rates:
            hp["avg_coverage"] = round(sum(rates) / len(rates), 4)
        if gains:
            hp["avg_gain"] = round(sum(gains) / len(gains), 4)
    with open(hp_path, "w", encoding="utf-8") as f:
        json.dump(hp, f, ensure_ascii=False, indent=2)
    print(f"已同步随机基准 gain 到: {hp_path}")


if __name__ == "__main__":
    main()
