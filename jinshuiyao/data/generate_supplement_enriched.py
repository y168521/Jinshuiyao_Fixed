# -*- coding: utf-8 -*-
"""
赛奇(Sage) - 金水谣 matches 数据优化改造脚本 (P2 / P3 / P4)
==========================================================
本脚本在上一轮 matches_supplemented.csv(8列, 400行, seed=42) 与
matches.csv(3行模板) 的基础上，做三项增量改造：

  P3  清洗原始模板 matches.csv 的脏数据
      - 将 league=='世界杯半决赛' 修正为合法联赛 '欧冠资格赛'
      - 覆盖写回 matches.csv（幂等：已修正则跳过）

  P2  扩展演示数据字段（保持 match_id 与三赔率完全不变，仅追加）
      - handicap     让球盘口（依据 d=odds_lose-odds_win 映射亚洲盘）
      - over_under   大小球（依联赛均值取 2.5 / 3.5，固定 seed 微随机）
      - home_rank    主队联赛排名（1~20，依据主胜赔强弱）
      - away_rank    客队联赛排名（1~20，依据客胜赔强弱，同场不重复）
      - home_form    主队近5场战绩（'WWDLW' 形式，{W,D,L}）
      - away_form    客队近5场战绩

  P4  数据字典与来源字段
      - 追加 collected_at（采集时间，统一 '2026-07-28'）
      - 追加 source（来源，固定 '演示数据-赛奇生成(seed=42)-非真实赛果'）
      - 写出 matches_data_dictionary.md（全部 16 字段数据字典）
      - 明确 P1 的 result / score 真实赛果字段尚未填充

可复现性：
  - 所有随机性使用 np.random.RandomState(42)，按行顺序确定性抽数。
  - 脚本读取当前 matches_supplemented.csv 的 8 个基础列重新派生新字段，
    因此无论当前文件是 8 列还是 16 列，重复运行均得到逐字节一致的结果（幂等）。
  - 注意：P1(result/score 真实赛果) 依赖用户真实数据，本脚本不生成。

运行环境：venv（pandas 3.0.3 / numpy 2.5.1），固定 seed=42。
"""
import os
import datetime as dt
import numpy as np
import pandas as pd

# ---------- 固定随机种子（保证可复现） ----------
SEED = 42
rng = np.random.RandomState(SEED)

DATA_DIR = r"C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed\jinshuiyao\data"
SRC = os.path.join(DATA_DIR, "matches.csv")
SUP = os.path.join(DATA_DIR, "matches_supplemented.csv")
DICT = os.path.join(DATA_DIR, "matches_data_dictionary.md")

ALLOWED_LEAGUES = ["英超", "西甲", "德甲", "意甲", "法甲", "欧冠资格赛", "欧联杯"]
BASE_COLS = ["match_id", "home", "away", "league", "match_time",
             "odds_win", "odds_draw", "odds_lose"]

COLLECTED_AT = "2026-07-28"
SOURCE = "演示数据-赛奇生成(seed=42)-非真实赛果"

# 让球盘口合法取值集合
HANDICAP_VALUES = {-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0}

# 赔率区间（与 generate_supplement.py 保持一致，用于排名映射）
OW_LO, OW_HI = 1.20, 6.00     # odds_win 合理区间
OL_LO, OL_HI = 1.50, 9.00     # odds_lose 合理区间


# ============================================================
# 字段派生函数
# ============================================================
def map_handicap(d):
    """依据 d = odds_lose - odds_win 映射亚洲让球盘口。
    取值严格限定于 HANDICAP_VALUES。区间连续无缺口、无重叠。"""
    if d > 2.0:
        return -2.0
    elif d > 1.2:
        return -1.5
    elif d > 0.6:
        return -1.0
    elif d > 0.2:
        return -0.5
    elif d >= -0.2:
        return 0.0
    elif d >= -0.6:
        return 0.5
    elif d >= -1.2:
        return 1.0
    elif d >= -2.0:
        return 1.5
    else:
        return 2.0


def map_over_under(league):
    """大小球：欧战多 2.5；五大联赛约半随机 2.5/3.5。固定 seed。"""
    if league in ("欧冠资格赛", "欧联杯"):
        return 2.5 if rng.random() < 0.85 else 3.5
    else:
        return 2.5 if rng.random() < 0.50 else 3.5


def odds_to_rank(odds, lo, hi):
    """赔率 -> 联赛排名(1~20)。赔率越低(越强)排名越靠前(数字越小)。"""
    t = (odds - lo) / (hi - lo)
    t = min(max(t, 0.0), 1.0)
    return int(round(1.0 + t * 19.0))   # 1..20


def compute_ranks(ow, ol):
    """主/客排名：依据各自赔率强弱；同场两 rank 不重复。"""
    hr = odds_to_rank(ow, OW_LO, OW_HI)
    ar = odds_to_rank(ol, OL_LO, OL_HI)
    if hr == ar:
        # 碰撞处理：客队 +1，越界则主队 -1
        if ar < 20:
            ar += 1
        else:
            hr -= 1
    hr = max(1, min(20, hr))
    ar = max(1, min(20, ar))
    return hr, ar


def rank_to_probs(rank):
    """排名 -> 近5场 W/D/L 概率。排名越靠前(越小)胜率越高。"""
    t = (rank - 1) / 19.0                  # 0=最强, 1=最弱
    p_w = 0.70 - 0.35 * t                  # 最强 0.70 -> 最弱 0.35
    p_l = 0.20 + 0.35 * t                  # 最强 0.20 -> 最弱 0.55
    p_d = 1.0 - p_w - p_l
    if p_d < 0.10:                         # 保底平局概率，重归一化
        p_d = 0.10
        rem = 1.0 - p_d
        s = p_w + p_l
        p_w = p_w / s * rem
        p_l = p_l / s * rem
    s = p_w + p_d + p_l
    return p_w / s, p_d / s, p_l / s


def gen_form(rank):
    """依据排名概率生成 5 字符战绩序列，字符集 {W,D,L}。"""
    p_w, p_d, p_l = rank_to_probs(rank)
    return "".join(rng.choice(["W", "D", "L"], size=5, p=[p_w, p_d, p_l]))


# ============================================================
# P3：清洗原始模板 matches.csv 脏数据
# ============================================================
print("=" * 60)
print("【P3】清洗原始模板 matches.csv 脏数据")
print("=" * 60)
df_src = pd.read_csv(SRC, encoding="utf-8-sig")
clean_log = []
mask = df_src["league"] == "世界杯半决赛"
for idx in df_src[mask].index:
    mid = df_src.at[idx, "match_id"]
    df_src.at[idx, "league"] = "欧冠资格赛"
    clean_log.append((mid, "世界杯半决赛", "欧冠资格赛"))
    print(f"  修正 match_id={mid}: league '世界杯半决赛' -> '欧冠资格赛'")
if not clean_log:
    print("  未检测到 '世界杯半决赛' 脏数据（可能已清洗，幂等跳过）")
# 仅当确有改动或其它字段需保留时写回；始终覆盖写回以保证一致
df_src.to_csv(SRC, index=False, encoding="utf-8-sig")
print(f"  已覆盖写回: {SRC}（{len(df_src)} 行）")

# ============================================================
# P2 + P4：读取补充数据 -> 派生新字段 -> 写回增强版
# ============================================================
print("\n" + "=" * 60)
print("【P2+P4】扩展 matches_supplemented.csv 字段")
print("=" * 60)
df = pd.read_csv(SUP, encoding="utf-8-sig")
# 仅取 8 个基础列（幂等：无论当前为 8 列或 16 列，均从这里重新派生）
missing = [c for c in BASE_COLS if c not in df.columns]
if missing:
    raise SystemExit(f"matches_supplemented.csv 缺少基础列: {missing}")
base = df[BASE_COLS].copy()

handicap_list, ou_list, hr_list, ar_list, hf_list, af_list = [], [], [], [], [], []
for _, row in base.iterrows():
    d = float(row["odds_lose"]) - float(row["odds_win"])
    handicap_list.append(map_handicap(d))
    ou_list.append(map_over_under(row["league"]))
    hr, ar = compute_ranks(float(row["odds_win"]), float(row["odds_lose"]))
    hr_list.append(hr)
    ar_list.append(ar)
    hf_list.append(gen_form(hr))
    af_list.append(gen_form(ar))

base["handicap"] = handicap_list
base["over_under"] = ou_list
base["home_rank"] = hr_list
base["away_rank"] = ar_list
base["home_form"] = hf_list
base["away_form"] = af_list
base["collected_at"] = COLLECTED_AT
base["source"] = SOURCE

# 固定列顺序
FINAL_COLS = BASE_COLS + ["handicap", "over_under", "home_rank", "away_rank",
                          "home_form", "away_form", "collected_at", "source"]
base = base[FINAL_COLS]
base.to_csv(SUP, index=False, encoding="utf-8-sig")
print(f"  已写出增强版: {SUP}")
print(f"  行数={len(base)}  列数={len(base.columns)}")
print(f"  列顺序: {list(base.columns)}")

# ============================================================
# 新字段取值合理性自检
# ============================================================
print("\n" + "=" * 60)
print("【自检】新字段取值合理性")
print("=" * 60)
# 1) handicap 取值集合
hc_vals = set(float(v) for v in base["handicap"].unique())
assert hc_vals.issubset(HANDICAP_VALUES), f"handicap 越界: {hc_vals - HANDICAP_VALUES}"
print(f"  handicap 取值集合 ⊆ 合法集合: {sorted(hc_vals)}  ✓")
print(f"  handicap 分布: {base['handicap'].value_counts().sort_index().to_dict()}")

# 2) over_under 取值
ou_vals = sorted(float(v) for v in base["over_under"].unique())
assert set(ou_vals).issubset({2.5, 3.5}), f"over_under 越界: {ou_vals}"
print(f"  over_under 取值: {ou_vals}  ✓")
print(f"  over_under 分布: {base['over_under'].value_counts().sort_index().to_dict()}")

# 3) rank 范围与同场不重复
assert base["home_rank"].between(1, 20).all() and base["away_rank"].between(1, 20).all()
assert (base["home_rank"] != base["away_rank"]).all(), "存在同场 rank 重复!"
print(f"  home_rank 范围 [{base['home_rank'].min()}, {base['home_rank'].max()}]  ✓")
print(f"  away_rank 范围 [{base['away_rank'].min()}, {base['away_rank'].max()}]  ✓")
print(f"  同场 home_rank != away_rank: 全部满足  ✓")

# 4) form 字符集
import re
form_re = re.compile(r"^[WDL]{5}$")
assert base["home_form"].map(lambda s: bool(form_re.match(s))).all()
assert base["away_form"].map(lambda s: bool(form_re.match(s))).all()
print(f"  home_form 字符集∈{{W,D,L}} 且长度5: 全部满足  ✓  示例={base['home_form'].iloc[0]}")
print(f"  away_form 字符集∈{{W,D,L}} 且长度5: 全部满足  ✓  示例={base['away_form'].iloc[0]}")

# 5) match_id 与赔率未被改动（与基础列一致）
assert (base[BASE_COLS].values == df[BASE_COLS].values).all(), "基础列被改动!"
print(f"  match_id 与三赔率保持完全不变  ✓")
print(f"  collected_at 统一='{base['collected_at'].iloc[0]}'  ✓")
print(f"  source 统一='{base['source'].iloc[0]}'  ✓")

# ============================================================
# P4：写出数据字典 matches_data_dictionary.md
# ============================================================
print("\n" + "=" * 60)
print("【P4】写出 matches_data_dictionary.md")
print("=" * 60)

# 动态统计
hc_dist = base["handicap"].value_counts().sort_index()
ou_dist = base["over_under"].value_counts().sort_index()
league_dist = base["league"].value_counts()

def field_block(name, typ, meaning, scope, demo):
    return f"| {name} | {typ} | {meaning} | {scope} | {demo} |"

lines = []
lines.append("# matches_supplemented.csv 数据字典")
lines.append("")
lines.append("> 生成/维护：赛奇(Sage)｜可复现种子：seed=42｜环境：venv(pandas 3.0.3 / numpy 2.5.1)")
lines.append(f"> 采集时间(collected_at)：{COLLECTED_AT}｜行数：{len(base)}｜列数：{len(base.columns)}")
lines.append("")
lines.append("## 一、字段总览（16 列，按 CSV 列顺序）")
lines.append("")
lines.append("| 字段名 | 类型 | 含义 | 取值范围 / 示例 | 是否演示标注 |")
lines.append("|--------|------|------|---------------|--------------|")
lines.append(field_block("match_id", "string", "比赛唯一标识（演示编号 500_001~500_400）",
                         "如 500_001", "演示生成（独立编号空间，勿与原始 matches.csv 主键直接合并）"))
lines.append(field_block("home", "string", "主队名称", "如 贝蒂斯", "演示生成（真实俱乐部名）"))
lines.append(field_block("away", "string", "客队名称", "如 塞尔塔", "演示生成（真实俱乐部名）"))
lines.append(field_block("league", "string", "联赛/赛事",
                         "英超/西甲/德甲/意甲/法甲/欧冠资格赛/欧联杯", "演示生成（权重分布）"))
lines.append(field_block("match_time", "string(YYYY-MM-DD HH:MM)", "比赛时间",
                         "如 2026-08-30 22:00", "演示生成（2026-07~2026-12）"))
lines.append(field_block("odds_win", "float", "主胜赔率", f"[{OW_LO}, {OW_HI}]（2位小数）", "演示生成（概率三元组推出）"))
lines.append(field_block("odds_draw", "float", "平局赔率", "2.80~5.50（2位小数）", "演示生成（概率三元组推出）"))
lines.append(field_block("odds_lose", "float", "客胜赔率", "1.50~9.00（2位小数）", "演示生成（概率三元组推出）"))
lines.append(field_block("handicap", "float", "亚洲让球盘口（主队视角，负数=主让，正数=客让）",
                         "∈{-2,-1.5,-1,-0.5,0,0.5,1,1.5,2}", "演示推算（d=odds_lose-odds_win 映射）"))
lines.append(field_block("over_under", "float", "大小球盘口（总进球数界线）",
                         "2.5 或 3.5", "演示推算（依联赛均值）"))
lines.append(field_block("home_rank", "int", "主队联赛排名（1=榜首，20=垫底）",
                         "1~20", "演示推算（主胜赔越低越靠前）"))
lines.append(field_block("away_rank", "int", "客队联赛排名（1=榜首，20=垫底）",
                         "1~20", "演示推算（客胜赔越低越靠前，同场不重复）"))
lines.append(field_block("home_form", "string", "主队近5场战绩",
                         "5位 W/D/L 序列，如 WWDLW", "演示推算（按排名概率+seed生成）"))
lines.append(field_block("away_form", "string", "客队近5场战绩",
                         "5位 W/D/L 序列，如 DLWWL", "演示推算（按排名概率+seed生成）"))
lines.append(field_block("collected_at", "string(YYYY-MM-DD)", "数据采集/生成日期",
                         f"统一 {COLLECTED_AT}", "演示标注"))
lines.append(field_block("source", "string", "数据来源说明",
                         SOURCE, "演示标注"))

lines.append("")
lines.append("## 二、派生规则说明（可追溯）")
lines.append("")
lines.append(f"- **handicap**：`d = odds_lose - odds_win`，按区间映射亚洲盘：")
lines.append("  `d>2.0→-2；1.2<d≤2.0→-1.5；0.6<d≤1.2→-1；0.2<d≤0.6→-0.5；-0.2≤d≤0.2→0；"
             "-0.6<d≤-0.2→0.5；-1.2<d≤-0.6→1；-2.0<d≤-1.2→1.5；d≤-2.0→2`。取值严格 ∈ "
             "{-2,-1.5,-1,-0.5,0,0.5,1,1.5,2}。")
lines.append(f"- **over_under**：欧冠资格赛/欧联杯 85% 取 2.5（其余 3.5）；五大联赛约 50%/50% 取 2.5/3.5。"
             "由 `np.random.RandomState(42)` 确定性抽取。")
lines.append(f"- **home_rank / away_rank**：赔率经线性映射至 1~20（`rank = round(1 + (odds-lo)/(hi-lo)*19)`，"
             "home 用 odds_win 区间[{OW_LO},{OW_HI}]，away 用 odds_lose 区间[{OL_LO},{OL_HI}]）；"
             "同场两 rank 相撞时客队 +1（越界则主队 -1），保证不重复。")
lines.append(f"- **home_form / away_form**：由对应 rank 推导 W/D/L 概率（rank1≈胜0.70/平0.20/负0.10，"
             "rank20≈胜0.35/平0.10/负0.55），再用 `RandomState(42)` 抽取 5 字符序列。")

lines.append("")
lines.append("## 三、字段分布速览（演示数据集 N=%d）" % len(base))
lines.append("")
lines.append("**handicap 分布**")
lines.append("| 盘口 | 场次 |")
lines.append("|------|------|")
for k in sorted(hc_dist.index):
    lines.append(f"| {k:g} | {int(hc_dist[k])} |")
lines.append("")
lines.append("**over_under 分布**")
lines.append("| 大小球 | 场次 |")
lines.append("|--------|------|")
for k in sorted(ou_dist.index):
    lines.append(f"| {k:g} | {int(ou_dist[k])} |")
lines.append("")
lines.append("**联赛分布（用于校验 over_under 规则）**")
lines.append("| 联赛 | 场次 |")
lines.append("|------|------|")
for lg in ALLOWED_LEAGUES:
    lines.append(f"| {lg} | {int(league_dist.get(lg, 0))} |")
lines.append(f"| **合计** | **{int(league_dist.sum())}** |")

lines.append("")
lines.append("## 四、P1 真实赛果字段（⚠️ 尚未填充）")
lines.append("")
lines.append("- **result**（主胜/平/客胜）与 **score**（比分，如 2-1）为 P1 阶段字段，")
lines.append("  **当前数据集中不存在**，必须等待用户提供真实比赛结果后方可回填。")
lines.append("- 本文件及本字典中的所有数值均为演示/推算数据，**不可作为真实赛果或预测依据**。")
lines.append("- 回填建议：按 match_id 对齐真实赛果，追加 `result`、`score` 两列；")
lines.append("  届时 source 应更新为真实来源，并移除/标注演示性质。")

lines.append("")
lines.append("## 五、可复现说明")
lines.append("")
lines.append("- 全部随机性基于 `seed=42`（脚本内 `np.random.RandomState(42)`）。")
lines.append("- 运行 `generate_supplement_enriched.py` 可幂等重建本文件（读取基础 8 列重新派生，")
lines.append("  重复运行结果逐字节一致）。")
lines.append("- 基础 8 列（match_id/home/away/league/match_time/三赔率）在派生过程中保持不变。")

dict_txt = "\n".join(lines)
with open(DICT, "w", encoding="utf-8") as f:
    f.write(dict_txt)
print(f"  已写出: {DICT}")

print("\n全部改造完成 ✓")
