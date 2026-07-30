# -*- coding: utf-8 -*-
"""
金水谣 P1 真实赛果回测分析 (data-scientist / 赛奇)
输入 (只读): matches_real.csv  (143 场 2025-26 五大联赛真实完赛结果)
输出: 频率表 / 校准表(Brier+偏差) / 预测命中率 / 代表性检验 / 庄家 margin

所有数字可追溯：
 - 实际频率 = matches_real.csv 本样本(143) 逐场统计
 - 隐含概率(英超/西甲) = 诺亚 WebSearch 公开赔率 1/odds (含 margin)
 - 隐含近似(德甲/意甲/法甲) = 诺亚 WebSearch 外部赛季基准实际频率 (无逐场赔率)
 - 外部基准实际(英超/德甲/意甲/法甲) = 诺亚 WebSearch 赛季汇总, 用于样本代表性检验
"""
import os
import json
import numpy as np
import pandas as pd

CSV_PATH = r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\jinshuiyao\data\matches_real.csv"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
np.random.seed(42)

# ----------------------------------------------------------------------------
# 0. 外部基准常量 (来源: 诺亚 WebSearch 公开来源整理, 2025-26 赛季, 数据截至 2026-07-04)
# ----------------------------------------------------------------------------
# 赔率隐含概率 (英超/西甲, 取自真实赔率样本均值 1/odds, 含庄家 margin)
# 英超: home~2.2, draw~3.98, away~3.4  (诺亚给定)
# 西甲: home~1.9, draw~3.5, away~4.0  (theschoolofodds)
IMPLIED_ODDS = {
    "英超": {"H": 1/2.2,  "D": 1/3.98, "A": 1/3.4},
    "西甲": {"H": 1/1.9,  "D": 1/3.5,  "A": 1/4.0},
}

# 外部赛季基准实际频率 (用于样本代表性检验)
# 英超: 赛季全量 380 场 (dedicatedbetting.co.uk + soccer188.net)
# 德甲/意甲/法甲: mid-season 汇总 (footballtradingprofits, 2026-01-13)
EXT_ACTUAL = {
    "英超": {"H": 0.426, "D": 0.274, "A": 0.290},  # full 380
    "德甲": {"H": 0.44,  "D": 0.23,  "A": 0.33},   # mid 142
    "意甲": {"H": 0.37,  "D": 0.30,  "A": 0.33},   # mid 196
    "法甲": {"H": 0.50,  "D": 0.22,  "A": 0.28},   # mid 153
    # 西甲外部实际频率诺亚未提供 (仅给隐含), 留空
}

LEAGUES = ["英超", "西甲", "德甲", "意甲", "法甲"]
RESULT_MAP = {"主胜": "H", "平": "D", "客胜": "A"}
RESULT_CN = {"H": "主胜", "D": "平", "A": "客胜"}

# ----------------------------------------------------------------------------
# 1. 读取 + 实际频率统计 (本样本)
# ----------------------------------------------------------------------------
df = pd.read_csv(CSV_PATH)
df["outcome"] = df["result"].map(RESULT_MAP)
assert df["outcome"].notna().all(), "存在未映射的 result 值"
N_TOTAL = len(df)

# 总体频率
overall = df["outcome"].value_counts().reindex(["H", "D", "A"]).fillna(0)
overall_freq = (overall / N_TOTAL)

# 按联赛频率
league_counts = {}      # league -> {H,D,A 计数}
league_freq = {}        # league -> {H,D,A 频率}
for lg in LEAGUES:
    sub = df[df["league"] == lg]
    vc = sub["outcome"].value_counts().reindex(["H", "D", "A"]).fillna(0)
    league_counts[lg] = {k: int(vc[k]) for k in ["H", "D", "A"]}
    league_freq[lg] = {k: vc[k] / len(sub) for k in ["H", "D", "A"]}
    league_freq[lg]["n"] = len(sub)

print("=" * 70)
print(f"数据集规模: {N_TOTAL} 场  | 联赛分布: " +
      ", ".join(f"{lg}={league_freq[lg]['n']}" for lg in LEAGUES))
print("=" * 70)

# ----------------------------------------------------------------------------
# 2. 校准分析: 隐含概率 vs 实际频率 (本样本)
# ----------------------------------------------------------------------------
# 构造每联赛隐含向量
implied_vec = {}   # league -> [H,D,A] 隐含概率
implied_src = {}   # 来源标注
for lg in LEAGUES:
    if lg in IMPLIED_ODDS:
        implied_vec[lg] = np.array([IMPLIED_ODDS[lg][k] for k in ["H", "D", "A"]])
        implied_src[lg] = "真实赔率 1/odds (含 margin)"
    else:
        # 无赔率 -> 用外部赛季基准实际频率近似
        implied_vec[lg] = np.array([EXT_ACTUAL[lg][k] for k in ["H", "D", "A"]])
        implied_src[lg] = "近似: 外部赛季基准实际频率 (无逐场赔率)"

calib_rows = []
brier_rows = []
for lg in LEAGUES:
    p = implied_vec[lg]
    f = np.array([league_freq[lg][k] for k in ["H", "D", "A"]])
    bias = f - p
    # Brier: 每场用常数隐含向量 p 预测, 实际 one-hot(来自本样本)
    sub = df[df["league"] == lg]
    n = len(sub)
    onehot = np.zeros((n, 3))
    idx = {"H": 0, "D": 1, "A": 2}
    for i, o in enumerate(sub["outcome"]):
        onehot[i, idx[o]] = 1.0
    pred = np.tile(p, (n, 1))
    brier = np.mean((pred - onehot) ** 2)
    brier_rows.append({"league": lg, "brier": float(brier), "n": n,
                       "src": implied_src[lg]})
    calib_rows.append({
        "league": lg,
        "implied_H": p[0], "actual_H": f[0],
        "implied_D": p[1], "actual_D": f[1],
        "implied_A": p[2], "actual_A": f[2],
        "bias_H": bias[0], "bias_D": bias[1], "bias_A": bias[2],
        "src": implied_src[lg],
    })

# 庄家 margin (overround): 隐含概率之和
margin_rows = []
for lg in LEAGUES:
    if lg in IMPLIED_ODDS:
        s = sum(IMPLIED_ODDS[lg].values())
        margin_rows.append({"league": lg, "overround": s,
                            "margin_pct": (s - 1) * 100,
                            "note": "真实赔率 1/odds 之和"})
    else:
        margin_rows.append({"league": lg, "overround": 1.0,
                            "margin_pct": 0.0,
                            "note": "无赔率, 隐含=实际频率, overround 不适用"})

# ----------------------------------------------------------------------------
# 3. 样本代表性检验: 本样本实际 vs 外部赛季基准实际
# ----------------------------------------------------------------------------
repr_rows = []
for lg in LEAGUES:
    if lg in EXT_ACTUAL:
        f = np.array([league_freq[lg][k] for k in ["H", "D", "A"]])
        e = np.array([EXT_ACTUAL[lg][k] for k in ["H", "D", "A"]])
        diff = f - e
        repr_rows.append({
            "league": lg,
            "sample_H": f[0], "ext_H": e[0], "diff_H": diff[0],
            "sample_D": f[1], "ext_D": e[1], "diff_D": diff[1],
            "sample_A": f[2], "ext_A": e[2], "diff_A": diff[2],
        })
# 西甲外部实际缺失 -> 仅列本样本
if "西甲" not in EXT_ACTUAL:
    f = np.array([league_freq["西甲"][k] for k in ["H", "D", "A"]])
    repr_rows.append({"league": "西甲(无外部基准)",
                      "sample_H": f[0], "ext_H": np.nan, "diff_H": np.nan,
                      "sample_D": f[1], "ext_D": np.nan, "diff_D": np.nan,
                      "sample_A": f[2], "ext_A": np.nan, "diff_A": np.nan})

# ----------------------------------------------------------------------------
# 3b. 代表性统计检验: 卡方拟合优度 (本样本计数 vs 外部基准期望计数)
#     H0: 本样本分布 = 外部赛季基准分布; df=2; p<0.05 拒绝 -> 样本显著偏离赛季
# ----------------------------------------------------------------------------
from scipy.stats import chisquare
chi_rows = []
for lg in LEAGUES:
    if lg in EXT_ACTUAL:
        n = league_freq[lg]["n"]
        obs = np.array([league_counts[lg][k] for k in ["H", "D", "A"]], dtype=float)
        ext_p = np.array([EXT_ACTUAL[lg][k] for k in ["H", "D", "A"]])
        ext_p = ext_p / ext_p.sum()  # 归一化 (外部基准四舍五入可能不严格=1)
        exp = ext_p * n
        chi2, p = chisquare(obs, exp)
        chi_rows.append({"league": lg, "chi2": float(chi2), "p": float(p),
                         "df": 2, "n": int(n),
                         "verdict": "显著偏离赛季基准(p<0.05)" if p < 0.05 else "与赛季基准无显著差异"})

# ----------------------------------------------------------------------------
# 4. 预测准确率回测 (联赛级, 聚合估算)
#    规则: 预测 = 隐含概率最高方
#    命中率 = 本样本中该方实际频率
# ----------------------------------------------------------------------------
RANDOM_BASE = 1/3
acc_rows = []
for lg in LEAGUES:
    p = implied_vec[lg]
    pred_side = ["H", "D", "A"][int(np.argmax(p))]
    hit = league_freq[lg][pred_side]
    acc_rows.append({
        "league": lg,
        "pred_side": pred_side,
        "pred_side_cn": RESULT_CN[pred_side],
        "hit_rate": hit,
        "n": league_freq[lg]["n"],
        "vs_random": hit - RANDOM_BASE,
        "src": implied_src[lg],
    })

# 总体加权命中率 (按样本量加权)
total_hit = sum(acc_rows[i]["hit_rate"] * league_freq[LEAGUES[i]]["n"]
                for i in range(len(LEAGUES))) / N_TOTAL

# ----------------------------------------------------------------------------
# 5. 打印结果
# ----------------------------------------------------------------------------
def pct(x): return f"{x*100:.1f}%"

print("\n【表1】真实频率 (本样本 143 场)")
print(f"{'联赛':<6}{'H':>6}{'D':>6}{'A':>6}{'n':>6}")
print(f"{'总体':<6}{pct(overall_freq['H']):>6}{pct(overall_freq['D']):>6}{pct(overall_freq['A']):>6}{N_TOTAL:>6}")
for lg in LEAGUES:
    c = league_counts[lg]; fq = league_freq[lg]
    print(f"{lg:<6}{pct(fq['H']):>6}{pct(fq['D']):>6}{pct(fq['A']):>6}{fq['n']:>6}  计数 H={c['H']} D={c['D']} A={c['A']}")

print("\n【表2】校准: 隐含概率 vs 实际频率 (偏差 = 实际 - 隐含)")
print(f"{'联赛':<6}{'隐H':>7}{'实H':>7}{'隐D':>7}{'实D':>7}{'隐A':>7}{'实A':>7}{'偏H':>7}{'偏D':>7}{'偏A':>7}")
for r in calib_rows:
    print(f"{r['league']:<6}{pct(r['implied_H']):>7}{pct(r['actual_H']):>7}"
          f"{pct(r['implied_D']):>7}{pct(r['actual_D']):>7}"
          f"{pct(r['implied_A']):>7}{pct(r['actual_A']):>7}"
          f"{r['bias_H']*100:>+6.1f}{r['bias_D']*100:>+6.1f}{r['bias_A']*100:>+6.1f}")

print("\n【表3】Brier Score (每联赛, 常数隐含向量预测本样本 one-hot)")
for r in brier_rows:
    print(f"  {r['league']:<6} Brier={r['brier']:.4f}  (n={r['n']}, {r['src']})")

print("\n【表4】庄家 margin (overround = Σ隐含概率)")
for r in margin_rows:
    print(f"  {r['league']:<6} overround={r['overround']:.4f}  margin={r['margin_pct']:+.2f}%  ({r['note']})")

print("\n【表5】样本代表性: 本样本实际 vs 外部赛季基准实际")
print(f"{'联赛':<12}{'样H':>7}{'外H':>7}{'差H':>7}{'样D':>7}{'外D':>7}{'差D':>7}{'样A':>7}{'外A':>7}{'差A':>7}")
for r in repr_rows:
    def g(v): return "  - " if pd.isna(v) else pct(v)
    def gd(v): return "  - " if pd.isna(v) else f"{v*100:+.1f}"
    print(f"{r['league']:<12}{pct(r['sample_H']):>7}{g(r['ext_H']):>7}{gd(r['diff_H']):>7}"
          f"{pct(r['sample_D']):>7}{g(r['ext_D']):>7}{gd(r['diff_D']):>7}"
          f"{pct(r['sample_A']):>7}{g(r['ext_A']):>7}{gd(r['diff_A']):>7}")

print("\n【表5b】代表性卡方拟合优度检验 (H0: 本样本=外部赛季基准, df=2)")
for r in chi_rows:
    print(f"  {r['league']:<6} chi2={r['chi2']:.3f}  p={r['p']:.3f}  n={r['n']}  -> {r['verdict']}")

print("\n【表6】预测准确率回测 (联赛级, 预测=隐含最高方, 命中率=本样本该方频率)")
print(f"{'联赛':<6}{'预测':>6}{'命中率':>9}{'n':>6}{'vs随机':>9}  来源")
for r in acc_rows:
    print(f"{r['league']:<6}{r['pred_side_cn']:>6}{pct(r['hit_rate']):>9}{r['n']:>6}{r['vs_random']*100:>+8.1f}  {r['src']}")
print(f"\n总体加权命中率(按样本量) = {pct(total_hit)}  | 随机基线 = {pct(RANDOM_BASE)}  | 超额 = {(total_hit-RANDOM_BASE)*100:+.1f}pp")

# ----------------------------------------------------------------------------
# 6. 导出结构化结果 (供 dashboard / report 下游使用)
# ----------------------------------------------------------------------------
out = {
    "meta": {
        "n_total": N_TOTAL,
        "leagues": LEAGUES,
        "random_baseline": RANDOM_BASE,
        "weighted_hit_rate": float(total_hit),
    },
    "overall_freq": {k: float(overall_freq[k]) for k in ["H", "D", "A"]},
    "league_counts": league_counts,
    "league_freq": {lg: {k: float(league_freq[lg][k]) for k in ["H", "D", "A", "n"]} for lg in LEAGUES},
    "calibration": [
        {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in r.items()}
        for r in calib_rows
    ],
    "brier": [
        {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in r.items()}
        for r in brier_rows
    ],
    "margin": margin_rows,
    "representativeness": [
        {k: (None if (isinstance(v, float) and pd.isna(v)) else float(v) if isinstance(v, (int, float, np.floating)) else v)
         for k, v in r.items()}
        for r in repr_rows
    ],
    "chi_square": [
        {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in r.items()}
        for r in chi_rows
    ],
    "accuracy": [
        {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in r.items()}
        for r in acc_rows
    ],
}
with open(os.path.join(OUT_DIR, "backtest_metrics.json"), "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=2)
print(f"\n[已导出] {os.path.join(OUT_DIR, 'backtest_metrics.json')}")
print("[完成] 回测分析结束。")
