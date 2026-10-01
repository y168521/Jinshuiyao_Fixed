# -*- coding: utf-8 -*-
"""彩票历史数据「分类复盘」研究脚本（walk-forward + 置换检验）—— JS-20261002-01

【道衍推导】
  阴阳：阳=主动证伪（置换检验打乱期序，看策略是否真有信号）；
        阴=守底（命中判定复用引擎 `_evaluate_hit`，奖级复用 `judge_prize`，杜绝自造口径）。
  天地人：天=规划（结论先行：无预测力）；地=隔离（独立进程，不扰 server）；
        人=复盘（随机基准 + 打乱分布双对照，钉死幸存者偏差）。
  知止：彩票无预测力是定论（§3.4），本脚本只产出**诚实的分类描述与证伪证据**，
        **不产出任何选号建议**；输出首行强制带「候选集·非购买建议」。

为什么不新造轮子（全部复用现役单一真源）：
  - 数据加载：`models.lottery_data.Data.load()`（与 `backtest_lottery_honest.py` 同源）
  - 号池配置：`config.LOTTERY_RULES`（不硬编码 33/16）
  - 命中判定：`backtesting.engine.BacktestEngine._evaluate_hit()`（引擎唯一口径）
  - 官方奖级：`utils.lottery_prize.judge_prize()` + `config/lottery_prize_rules.json`
    （**本文件绝不写第二份奖级表**，奖金一律从真源 JSON 读；浮动奖读 `min` 并标注）
  - 噪声判据：`NOISE_GAIN = 0.02` 与 `backtest_lottery_honest._gain_verdict()` 同口径

与本仓库 `scripts/backtest_lottery_honest.py` 的分工：
  - 后者：预测引擎 `PredictionService` 的**整体**诚实回测（每期多注、对比随机期望）
  - 本脚本：**市面流传的九种复盘选号法**逐一 walk-forward + **置换检验**（后者没有的维度）
  - 二者共用同一套判定端点，结论可交叉验证

用法：
  E:\\Project_Env\\jinshuiyao_env\\Scripts\\python.exe scripts/lottery_replay_study.py --lot 双色球
  E:\\Project_Env\\jinshuiyao_env\\Scripts\\python.exe scripts/lottery_replay_study.py --lot 双色球 --perm 200 --json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import sys
from collections import Counter
from itertools import combinations
from math import comb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import LOTTERY_RULES                       # noqa: E402  号池真源
from models.lottery_data import Data                    # noqa: E402  数据真源
from backtesting.engine import BacktestEngine           # noqa: E402  命中判定真源
from utils.lottery_prize import judge_prize, load_rules  # noqa: E402 官方奖级真源

# ---------------------------------------------------------------------------
# 常量（模块级大写；凡改数值，须同步 `金水谣_标准唯一真源.md` §3.11 并过阈值 watch）
# ---------------------------------------------------------------------------
# 预热期数：此前只攒历史不选号，杜绝"用未来数据选号"的未来函数
WARMUP_DRAWS = 100
# 置换检验轮次：把开奖期序随机打乱重跑同一策略，看真实成绩是否落在随机分布内
PERM_ROUNDS = 200
# 随机基准重复次数：每槽生成同规格随机注单求命中期望（与 honest_backtest 的 RAND_REPS 同思路）
RAND_REPS = 100
# 噪声判据：|gain| < 该值视为噪声内（与 backtest_lottery_honest._gain_verdict 同口径）
NOISE_GAIN = 0.02
# 显著性水平：置换检验 p 值低于此值才判"疑似有信号"
ALPHA = 0.05
# 多重比较校正：同时检验 N 个策略时，"挑最好的那个"天然更容易碰巧显著。
# 本脚本一次跑 9 种选号法，若只看 α=0.05，9 个里冒出一个 p<0.05 的概率约 1-(0.95)^9≈37%，
# 属于典型的选择性报告陷阱。故同时给出 Bonferroni 校正后的阈值 α/N 作为**主判定**。
BONFERRONI = True
# 冷门组合码数：统计"从未一起出现过"的 k 码组合
COMBO_K = 4
# 各彩种"小奖"红球阈值（沿用 honest_backtest 的 MIN_HIT 口径，双色球=3）
MIN_HIT = {"福彩3D": 3, "排列三": 3, "七星彩": 3, "双色球": 3,
           "大乐透": 3, "七乐彩": 3, "快乐8": 5}
# 分区数量（三区轮动策略用）
ZONE_COUNT = 3

DISCLAIMER = "候选集·非购买建议：彩票每期独立随机，历史数据无预测力，本节仅为统计描述。"

# 模块级随机源：策略需要"每期抽不同的号"。
# 踩坑记录：初版在每个策略函数里 `random.Random(20261002)` 现场新建，
# 导致每期抽到的号完全相同（纯随机对照退化成"固定一注打 766 期"），
# 置换检验的打乱分布退化成一条直线（min=median=max）——静默失真，必须共用同一个 RNG。
_RNG = random.Random(20261002)


def _pool(lot):
    """取号池（来自 config.LOTTERY_RULES，不硬编码）

    Returns:
        tuple: (rlo, rhi, rn, blo, bhi, bn)；无蓝球玩法后三项为 (0, 0, 0)
    """
    rule = LOTTERY_RULES.get(lot) or {}
    red = rule.get("red") or (1, 33, 6)
    blue = rule.get("blue")
    if blue:
        return red[0], red[1], red[2], blue[0], blue[1], blue[2]
    return red[0], red[1], red[2], 0, 0, 0


def load_draws(lot):
    """加载历史开奖，解析成 (red_tuple, blue_tuple, nums_str, period) 列表

    Returns:
        list: 每项 (reds:tuple[int], blues:tuple[int], raw:str, period)
    """
    rows = Data.load(lot) or []
    out = []
    for r in rows:
        raw = str(r.get("nums") or "")
        if not raw:
            continue
        try:
            fb = raw.split("+")
            reds = tuple(sorted(int(x) for x in fb[0].split(",") if x.strip()))
            blues = tuple(sorted(int(x) for x in fb[1].split(",") if x.strip())) \
                if len(fb) > 1 and fb[1].strip() else ()
        except ValueError:
            continue
        if reds:
            out.append((reds, blues, raw, r.get("period")))
    out.sort(key=lambda d: d[3] or 0)
    return out


def _fmt(reds, blues):
    """号码元组 -> 引擎可解析的号码串（两位补零，与 Data 中 nums 格式一致）"""
    s = ",".join("%02d" % x for x in sorted(reds))
    if blues:
        s += "+" + ",".join("%02d" % x for x in sorted(blues))
    return s


def _hist_count(hist, win):
    """近 win 期红球频次 Counter"""
    c = Counter()
    for d in hist[-win:]:
        for x in d:
            c[x] += 1
    return c


def hot_numbers(hist, n, rlo, rhi, win=30):
    """A 追热号：近 win 期出现最多的 n 个号"""
    c = _hist_count(hist, win)
    pick = sorted(range(rlo, rhi + 1), key=lambda x: (-c.get(x, 0), x))
    return tuple(sorted(pick[:n]))


def cold_numbers(hist, n, rlo, rhi):
    """B 追冷号：遗漏值最大（最久没出）的 n 个号"""
    last = {}
    for i, d in enumerate(hist):
        for x in d:
            last[x] = i
    cur = len(hist)
    pick = sorted(range(rlo, rhi + 1), key=lambda x: (-(cur - last.get(x, -1)), x))
    return tuple(sorted(pick[:n]))


def neighbour_numbers(hist, n, rlo, rhi, win=40):
    """C 邻号法：上期号码 ±1 里近 win 期最热的 n 个"""
    if not hist:
        return pure_random(hist, n, rlo, rhi)
    nb = set()
    for x in hist[-1]:
        if x - 1 >= rlo:
            nb.add(x - 1)
        if x + 1 <= rhi:
            nb.add(x + 1)
    c = _hist_count(hist, win)
    pick = sorted(nb, key=lambda x: (-c.get(x, 0), x))
    if len(pick) < n:
        pick += [x for x in sorted(range(rlo, rhi + 1), key=lambda x: (-c.get(x, 0), x))
                 if x not in pick][:n - len(pick)]
    return tuple(sorted(pick[:n]))


def zone_rotate(hist, n, rlo, rhi, win=30):
    """D 三区轮动：上期出得最少的区优先补号"""
    span = rhi - rlo + 1
    def z(x):
        return min(int((x - rlo) * ZONE_COUNT / span), ZONE_COUNT - 1)
    cnt = [0] * ZONE_COUNT
    if hist:
        for x in hist[-1]:
            cnt[z(x)] += 1
    c = _hist_count(hist, win)
    order = sorted(range(ZONE_COUNT), key=lambda k: cnt[k])
    pick = []
    for k in order:
        pool = [x for x in range(rlo, rhi + 1) if z(x) == k]
        pool.sort(key=lambda x: (-c.get(x, 0), x))
        take = max(1, n // ZONE_COUNT)
        pick += pool[:take]
        if len(pick) >= n:
            break
    return tuple(sorted(pick[:n]))


def odd_even_balance(hist, n, rlo, rhi, win=30):
    """E 奇偶均衡：奇偶各半，各自取最热"""
    c = _hist_count(hist, win)
    odd = [x for x in range(rlo, rhi + 1) if x % 2 == 1]
    even = [x for x in range(rlo, rhi + 1) if x % 2 == 0]
    odd.sort(key=lambda x: (-c.get(x, 0), x))
    even.sort(key=lambda x: (-c.get(x, 0), x))
    half = n // 2
    return tuple(sorted(odd[:half] + even[:n - half]))


def sum_target(hist, n, rlo, rhi, win=30):
    """F 和值瞄准：在随机候选里挑「热度高且和值接近历史众数」的一注"""
    c = _hist_count(hist, win)
    sums = [sum(d) for d in hist] or [n * (rlo + rhi) / 2.0]
    target = sorted(sums)[len(sums) // 2]
    rnd = _RNG
    best, bs = None, None
    for _ in range(300):
        cand = tuple(sorted(rnd.sample(range(rlo, rhi + 1), n)))
        sc = sum(c.get(x, 0) for x in cand) - abs(sum(cand) - target) * 0.6
        if bs is None or sc > bs:
            best, bs = cand, sc
    return best


def repeat_pick(hist, n, rlo, rhi, win=10):
    """G 重号法：留上期最热的号 + 补非上期最热的号"""
    if not hist:
        return pure_random(hist, n, rlo, rhi)
    c = _hist_count(hist, win)
    prev = set(hist[-1])
    keep = sorted(prev, key=lambda x: -c.get(x, 0))[:n // 2]
    rest = [x for x in range(rlo, rhi + 1) if x not in prev]
    rest.sort(key=lambda x: -c.get(x, 0))
    return tuple(sorted(list(keep) + rest[:n - len(keep)]))


def cold_combo(hist, n, rlo, rhi, k=COMBO_K):
    """H 冷门组合：挑一组「史上从未同时出现过」的 k 码，随机补齐

    这是用户提出的「最不可能结合的数字」。注意：从未出现是**组合数学必然**
    （C(33,4)=40920 种格子 vs 866 期×15 次投放），不等于"更可能开出"。
    """
    seen = set()
    for d in hist:
        for c in combinations(d, k):
            seen.add(c)
    rnd = _RNG
    base = None
    for _ in range(400):
        cand = tuple(sorted(rnd.sample(range(rlo, rhi + 1), k)))
        if cand not in seen:
            base = cand
            break
    if base is None:
        base = tuple(sorted(rnd.sample(range(rlo, rhi + 1), k)))
    rest = []
    while len(rest) < n - k:
        x = rnd.randint(rlo, rhi)
        if x not in base and x not in rest:
            rest.append(x)
    return tuple(sorted(base + tuple(rest)))


def pure_random(hist, n, rlo, rhi):
    """I 纯随机对照组：判定"认真选"是否真比瞎猜强"""
    rnd = _RNG
    return tuple(sorted(rnd.sample(range(rlo, rhi + 1), n)))


# 九种市面流传的复盘选号法（含随机对照组）；签名统一 fn(hist, n, rlo, rhi)
STRATEGIES = [
    ("A 追热号", lambda h, n, lo, hi: hot_numbers(h, n, lo, hi)),
    ("B 追冷号", lambda h, n, lo, hi: cold_numbers(h, n, lo, hi)),
    ("C 邻号法", lambda h, n, lo, hi: neighbour_numbers(h, n, lo, hi)),
    ("D 三区轮动", lambda h, n, lo, hi: zone_rotate(h, n, lo, hi)),
    ("E 奇偶均衡", lambda h, n, lo, hi: odd_even_balance(h, n, lo, hi)),
    ("F 和值瞄准", lambda h, n, lo, hi: sum_target(h, n, lo, hi)),
    ("G 重号法", lambda h, n, lo, hi: repeat_pick(h, n, lo, hi)),
    ("H 冷门组合", lambda h, n, lo, hi: cold_combo(h, n, lo, hi)),
    ("I 纯随机对照", lambda h, n, lo, hi: pure_random(h, n, lo, hi)),
]


def build_picks(draws, warmup, rlo, rhi, rn):
    """walk-forward：对每期 i，只用 draws[:i] 的历史选一注

    Returns:
        dict: {策略名: [号码元组, ...]}，长度 = len(draws) - warmup
    """
    picks = {name: [] for name, _ in STRATEGIES}
    for i in range(warmup, len(draws)):
        hist = [d[0] for d in draws[:i]]
        for name, fn in STRATEGIES:
            picks[name].append(fn(hist, rn, rlo, rhi))
    return picks


def score_picks(lot, picks, draws, warmup, blue_pool):
    """逐期判定：引擎命中 + 官方奖级（两个端点都是唯一真源）

    Returns:
        dict: {name: {"engine_hit": int, "prize_win": int, "tiers": Counter-like dict, "total": int}}
    """
    eng = BacktestEngine()
    min_hit = MIN_HIT.get(lot, 3)
    out = {}
    for name, seq in picks.items():
        eh = pw = 0
        tiers = {}
        for j, p in enumerate(seq):
            actual = draws[warmup + j]
            pred = _fmt(p, blue_pool)
            is_hit, tier = eng._evaluate_hit(lot, pred, actual[2], min_hit)
            if is_hit:
                eh += 1
            r = judge_prize(lot, pred, actual[2])
            if r.get("status") == "no_rule":
                # 规则读不到：诚实铁律——记「暂缺」，绝不猜成未中奖
                tiers["暂缺(规则缺失)"] = tiers.get("暂缺(规则缺失)", 0) + 1
            elif r.get("is_win"):
                pw += 1
                t = r.get("tier") or "未知"
                tiers[t] = tiers.get(t, 0) + 1
        out[name] = {"engine_hit": eh, "prize_win": pw,
                     "tiers": tiers, "total": len(seq)}
    return out


def perm_test(lot, picks, draws, warmup, blue_pool, rounds=PERM_ROUNDS, seed=11):
    """置换检验：打乱开奖期序重跑同一策略，看真实成绩是否落在随机分布内

    这是判定"时间/顺序类规律"真伪的最强工具——比单纯对比随机基线更能排除
    多重比较挑出来的假显著。

    Returns:
        dict: {name: {"real": float, "min":, "median":, "max":, "p": float, "verdict": str}}
    """
    eng = BacktestEngine()
    min_hit = MIN_HIT.get(lot, 3)
    rnd = random.Random(seed)
    actuals = [d[2] for d in draws[warmup:]]
    res = {}
    n_tests = max(1, len(picks))
    alpha_eff = (ALPHA / float(n_tests)) if BONFERRONI else ALPHA
    for name, seq in picks.items():
        def run(acts):
            n = 0
            for j, p in enumerate(seq):
                h, _ = eng._evaluate_hit(lot, _fmt(p, blue_pool), acts[j], min_hit)
                if h:
                    n += 1
            return n / float(len(seq)) if seq else 0.0
        real = run(actuals)
        vals = []
        for _ in range(rounds):
            sh = actuals[:]
            rnd.shuffle(sh)
            vals.append(run(sh))
        vals.sort()
        ge = sum(1 for v in vals if v >= real)
        p = (ge + 1.0) / (rounds + 1)
        res[name] = {
            "real": round(real, 6),
            "min": round(vals[0], 6) if vals else None,
            "median": round(vals[len(vals) // 2], 6) if vals else None,
            "max": round(vals[-1], 6) if vals else None,
            "p": round(p, 4),
            # 主判定用校正后阈值；p<0.05 但过不了校正的，明确标"未过校正"，
            # 避免把 9 选 1 的最好成绩当成信号（选择性报告）。
            "verdict": ("疑似有信号(p<%.4f)" % alpha_eff) if p < alpha_eff
                       else ("未过多重比较校正(p<%.2f但≥%.4f)" % (ALPHA, alpha_eff)
                             if p < ALPHA else "不显著(等同随机)"),
            "alpha": round(alpha_eff, 5),
            "n_tests": n_tests,
        }
    return res


def economics(lot, draws_count):
    """经济账：奖金一律从官方奖级真源读，浮动奖取 min 并标注（不写第二份奖级表）

    Returns:
        dict: {"fixed_ev": float, "float_note": str, "tiers": [...], "ticket_price": ...}
    """
    rules = load_rules()
    if not isinstance(rules, dict):
        return {"error": "奖级规则读不到，按诚实铁律返回暂缺（不猜测）"}
    spec = (rules.get("rules") or {}).get(lot) or {}
    tiers = spec.get("tiers") or []
    total = comb(33, 6)  # TODO: 仅双色球口径；其他彩种待按需扩展
    detail, fixed_ev = [], 0.0
    for t in tiers:
        prize = t.get("prize")
        is_float = prize == "浮动"
        amount = float(t.get("min") or 0) if is_float else float(prize or 0)
        conds = t.get("match") or []
        p = _tier_prob(conds, total)
        if not is_float:
            fixed_ev += amount * p
        detail.append({"tier": t.get("tier"), "cond": t.get("cond"),
                       "prize": ("浮动≥%d" % amount) if is_float else amount,
                       "prob": round(p, 8)})
    return {"ticket_price": 2, "fixed_ev": round(fixed_ev, 4),
            "tiers": detail,
            "float_note": "一/二等奖为浮动奖（奖池÷中奖注数），按真源 min 下限估算，实际以官方公告为准",
            "rules_updated_at": rules.get("updated_at")}


def _tier_prob(conds, total):
    """按 red_blue 奖级的 match 条件算单注概率（双色球口径：前区 6/33、后区 1/16）

    ⚠️ 踩坑记录：初版写成 `sum(comb(6,i)*comb(27,6-i) for i in range(fr,7))`，
    算的是 P(红 ≥ fr) 而不是 P(红 == fr)。六等奖条件是 (0,1)(1,1)(2,1) 三个，
    累加后概率被放大到 12.68%（真实 5.89%），期望收益随之虚高近一倍。
    奖级是**互斥**的，必须逐条件取"恰好命中 fr 个红球"的概率再相加。
    """
    p = 0.0
    for fr, bk in conds:
        fr = int(fr)
        if fr < 0 or fr > 6:
            continue
        pr = comb(6, fr) * comb(27, 6 - fr) / float(total)
        pb = (1.0 / 16.0) if int(bk) >= 1 else (15.0 / 16.0)
        p += pr * pb
    return min(p, 1.0)


def combo_coverage(draws, rlo, rhi, k=COMBO_K):
    """统计「从未一起出现过」的 k 码组合有多少（用户提问：最不可能结合的数字）

    Returns:
        dict: {"total": int, "never": int, "ratio": float, "top": [(combo, cnt)]}
    """
    cnt = Counter()
    for d in draws:
        for c in combinations(d[0], k):
            cnt[c] += 1
    allk = list(combinations(range(rlo, rhi + 1), k))
    never = len(allk) - len(cnt)
    return {"k": k, "total": len(allk), "never": never,
            "ratio": round(never / float(len(allk)), 4) if allk else 0.0,
            "top": [["-".join("%02d" % x for x in c), n] for c, n in cnt.most_common(10)]}


def dimension_profile(draws, rlo, rhi):
    """分类教学：九个维度的实测分布（描述历史，不用于预测）

    Returns:
        dict: 各维度的 Counter 计数
    """
    span = rhi - rlo + 1
    def z(x):
        return min(int((x - rlo) * ZONE_COUNT / span), ZONE_COUNT - 1)
    prof = {
        "奇偶": Counter(sum(1 for x in d[0] if x % 2 == 1) for d in draws),
        "大小": Counter(sum(1 for x in d[0] if x <= (rlo + rhi) / 2.0) for d in draws),
        "三区": Counter(tuple(sum(1 for x in d[0] if z(x) == k) for k in range(ZONE_COUNT))
                     for d in draws),
        "和值": [sum(d[0]) for d in draws],
        "跨度": [max(d[0]) - min(d[0]) for d in draws],
        "连号": Counter(sum(1 for i in range(len(d[0]) - 1) if d[0][i + 1] == d[0][i] + 1)
                     for d in draws),
        "重号": Counter(len(set(draws[i][0]) & set(draws[i - 1][0]))
                     for i in range(1, len(draws))),
        "同尾": Counter(max(Counter(x % 10 for x in d[0]).values()) for d in draws),
    }
    return prof


def _render(summary):
    """把结果渲染成人话文本（结论先行）。中文用 io.open 写出，避免管道转码。"""
    L = [DISCLAIMER, ""]
    b = summary["basic"]
    L.append("样本：%s %d 期（%s ~ %s），回测 %d 期（预热 %d 期）"
             % (b["lot"], b["total_draws"], b["first"], b["last"],
                b["tested"], b["warmup"]))
    L.append("")
    L.append("== 一、九种复盘选号法 walk-forward（命中判定复用引擎 _evaluate_hit）==")
    L.append("%-12s %8s %10s %10s" % ("方法", "引擎命中", "官方中奖", "样本"))
    for name, s in summary["score"].items():
        L.append("%-12s %8d %10d %10d" % (name, s["engine_hit"], s["prize_win"], s["total"]))
    L.append("")
    L.append("== 二、置换检验（打乱期序 %d 次）==" % summary["perm_rounds"])
    L.append("%-12s %9s %9s %9s %9s %8s  %s"
             % ("方法", "真实", "打乱最小", "打乱中位", "打乱最大", "p值", "判定"))
    for name, p in summary["perm"].items():
        L.append("%-12s %8.3f%% %8.3f%% %8.3f%% %8.3f%% %8.3f  %s"
                 % (name, p["real"] * 100, (p["min"] or 0) * 100,
                    (p["median"] or 0) * 100, (p["max"] or 0) * 100,
                    p["p"], p["verdict"]))
    L.append("")
    eco = summary["economics"]
    if eco.get("error"):
        L.append("== 三、经济账 ==")
        L.append("  " + eco["error"])
    else:
        L.append("== 三、经济账（奖金读自 config/lottery_prize_rules.json，规则日期 %s）=="
                 % eco.get("rules_updated_at"))
        L.append("  每注 %d 元；固定奖部分期望回收 = %.4f 元" % (eco["ticket_price"], eco["fixed_ev"]))
        for t in eco["tiers"]:
            L.append("    %-6s %-12s 奖金 %-10s 概率 %.6f%%"
                     % (t["tier"], t["cond"], t["prize"], t["prob"] * 100))
        L.append("  " + eco["float_note"])
    L.append("")
    cc = summary["cold_combo"]
    L.append("== 四、冷门组合（从未同时出现的 %d 码）==" % cc["k"])
    L.append("  共 %d 种，从未出现 %d 种（%.1f%%）—— 组合数学必然，非规律"
             % (cc["total"], cc["never"], cc["ratio"] * 100))
    L.append("  出现最多的组合：" + ", ".join("%s(%d次)" % (c, n) for c, n in cc["top"][:5]))
    L.append("")
    L.append(DISCLAIMER)
    return "\n".join(L)


def run(lot="双色球", warmup=WARMUP_DRAWS, rounds=PERM_ROUNDS):
    """跑完整研究流程，返回结构化 dict"""
    draws = load_draws(lot)
    if len(draws) <= warmup + 10:
        return {"error": "历史期数不足（%d 期），无法回测" % len(draws)}
    rlo, rhi, rn, blo, bhi, bn = _pool(lot)
    blue_pool = tuple(range(blo, blo + bn)) if bn else ()
    picks = build_picks(draws, warmup, rlo, rhi, rn)
    score = score_picks(lot, picks, draws, warmup, blue_pool)
    perm = perm_test(lot, picks, draws, warmup, blue_pool, rounds=rounds)
    return {
        "basic": {"lot": lot, "total_draws": len(draws),
                  "first": str(draws[0][3]), "last": str(draws[-1][3]),
                  "tested": len(draws) - warmup, "warmup": warmup},
        "score": score,
        "perm": perm,
        "perm_rounds": rounds,
        "economics": economics(lot, len(draws)),
        "cold_combo": combo_coverage(draws, rlo, rhi),
        "dimension": {k: (dict(v) if isinstance(v, Counter) else v)
                      for k, v in dimension_profile(draws, rlo, rhi).items()},
    }


def main():
    ap = argparse.ArgumentParser(description="金水谣 · 彩票分类复盘研究（walk-forward + 置换检验）")
    ap.add_argument("--lot", default="双色球", help="彩种（默认 双色球）")
    ap.add_argument("--warmup", type=int, default=WARMUP_DRAWS, help="预热期数")
    ap.add_argument("--perm", type=int, default=PERM_ROUNDS, help="置换检验轮次")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--out", help="写出到文件（默认仅打印）")
    args = ap.parse_args()

    summary = run(args.lot, args.warmup, args.perm)
    if args.json:
        text = json.dumps(summary, ensure_ascii=False, indent=2)
    else:
        text = _render(summary) if "error" not in summary else summary["error"]
    print(text)
    if args.out:
        with io.open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("\n已写出: %s" % args.out)


if __name__ == "__main__":
    main()
