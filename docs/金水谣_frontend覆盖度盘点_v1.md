# 金水谣 `frontend/` 子系统 · 设计系统覆盖度盘点 v1

> 生成日期：2026-09-24　|　编号：JS-20260924-10　|　性质：**只读盘点，未改动任何代码**
> 盘点对象：`frontend/**/*.html`（37 页）　|　对照：`jinshuiyao-guide`（31 页，排版审计已收口）

---

## 结论先行

**`frontend/` 是比 `jinshuiyao-guide` 更大的半边（37 页 vs 31 页），但设计系统覆盖度显著更低。**
四类缺口按「价值 ÷ 风险」排序，建议分三个批次推进：

| 批次 | 内容 | 规模 | 风险 | 建议 |
|---|---|---|---|---|
| **A** | 原生对话框 → `JSY` 反馈组件 | 6 页 / 12 处 | 低（同 guide 已验证做法） | **优先做** |
| **B** | 5 页"完全在设计系统外"接回令牌 | 5 页 / 12 个硬编码色 | 低（补 `tokens.css` 为纯变量） | 做 |
| **C** | 表格溢出兜底 | 6 页 / 13 张表 | 低 | 做 |
| — | 焦点环随 `theme.css` 生效 | 9 页未覆盖 | — | 随 B 批顺带解决 |

**明确不动**：禁用色 0 命中（无需清洗）、栅格 `grid-2/3/4` 仅 1 处使用（P2 栅格整改在此无收益）。

---

## 一、总览（37 页）

| 指标 | 已覆盖 | 未覆盖 | 说明 |
|---|---|---|---|
| 引用 `theme.css` | 28 | **9** | 未引则拿不到令牌 @import、垂直节奏、表格兜底、焦点环 |
| 引用 `tokens.css` | 4 | **33** | 仅 P0-2 收口过的 4 页 |
| 引用 `ui-feedback` | **0** | **37** | 反馈组件在此子系统完全空白 |
| `<html lang>` | 37 | 0 | ✅ 全站合规 |
| 禁用五色命中 | — | **0 页 / 0 处** | ✅ 无需清洗 |
| 含 `<table>` | 19 页 / 31 张表 | — | 其中 **6 页无溢出处理** |
| 用 `grid-2/3/4` | 1 页 / 1 处 | — | 可忽略 |

---

## 二、缺口 1：5 页完全在设计系统之外（最严重）

这 5 页**既不引 `theme.css` 也不引 `tokens.css`**，并且在私有 `:root` 里硬编码核心色 —— 与 guide 侧的 `agent-pipeline-visualizer.html` 属同一类，但数量是 5 倍。

| 页面 | 硬编码核心色 | 行数 | 备注 |
|---|---|---|---|
| `frontend/dashboard/jinshuiyao-dashboard.html` | 1 | **2207** | 体量最大，风险敞口最大 |
| `frontend/lottery/rotation-matrix.html` | 3 | 531 | 另有 1 处原生对话框 |
| `frontend/lottery/omission-heatmap.html` | 3 | 503 | |
| `frontend/lottery/prize-calculator.html` | 2 | 464 | 另有 2 处原生对话框、2 张表无溢出处理 |
| `frontend/trend/jinshuiyao-trend.html` | 3 | 134 | |

**建议做法**（同 guide 侧论证过的顺序）：
1. 先补引 `tokens.css`（**纯变量文件、无布局规则 → 零布局风险**）；
2. 再把硬编码核心色改为 `var(--js-*, 当前值)`，回退值 = 当前值 → **默认主题视觉零变化**；
3. 派生中性色是否在令牌中有等价物需逐页核对，**没有等价物时不可强行接主题切换**（否则浅色模式下文字会隐形，比现状更糟）。

### 二·补　批次 B 复核（执行前取证）：**实为"换色工程"，不是机械接线，暂缓**

> 2026-09-24 批次 A 完成后，对这 5 页的私有 `:root` 做了完整取证，结论**推翻了上面的原建议**，特此更正。

**关键机制**：`var(--js-x, 回退值)` 的回退值**只在令牌未定义时生效**。一旦引入 `tokens.css`，令牌即被定义 → 页面会采用**令牌值**而非自己的原值。因此"回退值 = 当前值 ⇒ 视觉零变化"**仅在两者本来就相等时成立**。

**取证结果：这 5 页的颜色与 L2 令牌几乎全部不相等**，且整体属于另一套调色板（Slate/Tailwind 风格），并非 L2 七色：

| 页面变量 | 现值 | 对应令牌值 | 是否相等 |
|---|---|---|---|
| `--bg` | `#0b0f19` | `--js-deep` = `#0B1A2F` | ❌ 会变 |
| `--card` | `#131a2a` | `--js-card-bg` = `#162840` | ❌ 会变 |
| `--text` | `#e4e8f1` | `--js-ink` = `#E8ECF1` | ❌ 会变 |
| `--primary` | `#00d4aa` | `--js-jade` = `#2D8B7E` | ❌ 会变 |
| `--gold` | `#ffd93d` | `--js-gold` = `#C9A96E` | ❌ 会变 |
| `--blue` | `#60a5fa` | `--js-ice` = `#5BC0DE` | ❌ 会变 |
| `--danger` | `#ff6b6b` | `--js-copper` = `#C8755A` | ❌ 会变 |

（`trend` 页有 2 个例外恰好相等：`--blue:#5BC0DE` == `--js-ice`、`--danger:#C8755A` == `--js-copper`，但不足以支撑整页安全接入。）

**另有两处设计系统合规问题**（不在禁用五色之列，故门禁未报，但偏离七色）：
- 出现多个七色池之外的色值：`#00d4aa` / `#00ffcc` / `#00d4ff` / `#f59e0b` / `#d29922` / `#ff6b6b` / `#ffd93d` / `#60a5fa` / `#b197fc`。
- `dashboard/jinshuiyao-dashboard.html`（2207 行）自带 33 个变量，含渐变、玻璃拟态等完整视觉体系。

**结论**：把"5 页接回令牌"理解为机械接线是错的——**它等价于重做这 5 页的配色**，其中含一个 2207 行的主仪表盘。属"改变观感、需单独评审"的变更，**本次不擅自执行**，转人工拍板（见第七节第 4 条）。

### 二·补二　批次 B **已执行**（JS-20260924-26）：方案丙→甲 落地

> 用户拍板"走最优解路线"→ 先出换色前后对照（丙，见 `docs/批次B_换色前后对照_mockup.html`），确认后执行换色（甲）。

**执行范围**：5 页全部引入 `tokens.css`，私有 `:root` 改为 `var(--js-*)` 派生，布局/结构零改动。

**最终映射（与初版草案的差异已论证）**：

| 角色 | 私有变量（原值） | → L2 令牌 | 备注 |
|---|---|---|---|
| 页面底 / 卡片 | `#0b0f19` / `#131a2a` | `--js-deep` / `--js-card-bg` | |
| 正文 / 次要文字 | `#e4e8f1` / `#7a8499` | `--js-ink` / `--js-ink-mid` | |
| 分隔线 | `#1e2a40` | `--js-border-elev-0` | 层级改由 ice 描边表达 |
| **主强调 / 主操作** | `#00d4aa`(薄荷青) | **`--js-gold`** | ⚠️ 初版草案给的是 `--js-jade`，取证后改金 |
| 次强调 / 蓝球 / 数据 | `#60a5fa` | `--js-ice` | |
| 奖级 / 警告 | `#ffd93d` / `#f59e0b` | `--js-gold` | tokens.css 明定 warning = gold |
| 成功 | `#2D8B7E` | `--js-jade` | 本就相等，零变更 |
| 危险 | `#ff6b6b` | `--js-copper` | 消除禁色裸用 |
| 紫 | `#b197fc` | **删除** | 禁用色相且 5 页 0 引用 |

**主强调为何改金不选墨绿**（初版草案的修正依据）：
1. `tokens.css` 明定 gold = 强调/标题/**主按钮**；
2. jade 在令牌文件中被标注"**小字对比度 3.6/4.2 不达标，仅作填充与图形**"，且语义 = 成功，会与 dashboard 已有的 `--success #2D8B7E` 撞色；
3. 黑字压金对比度 9.4:1，优于压墨绿的 5.1:1。

**执行中暴露并一并修掉的 3 个既有缺陷**（不在原盘点结论内）：
1. **`prize-calculator` 的 `--accent/--gold/--ice` 从未定义** → 页内 21 处 `var()` 全部静默失效（选中态/主按钮/奖金数字取不到色），本次补齐；
2. **`dashboard` 的表面色变量 `--bg-deep/bg2/bg3/bg4` var 用量为 0**（写了不用），真实颜色是裸 hex，故换色必须同时改 `:root` 与裸 hex；
3. **`omission-heatmap` 的热力色阶含 `#ff4444`、`#8a3a3a` 等离牌色** → 重排为「银白(本期出现) → 冰蓝 → 墨绿 → 香槟金 → 赤铜(超高遗漏)」的冷→暖梯度。

**ECharts / canvas 色值处理**：CSS `var()` 无法直接喂给 ECharts，新增令牌读取器 `jsv(n)`（`getComputedStyle` 运行时取 `tokens.css` 真源值），避免 JS 里二次硬编码。

**验收**：离牌色 0 · 禁色 0 · 5 页内联 JS `node --check` 全通过 · 控制字符 0。

---

## 三、缺口 2：反馈组件覆盖为 0（机械、收益高）

`ui-feedback` 在 `frontend/` 是 **0/37**。残留 **12 处原生对话框**，分布在 6 页：

| 页面 | 原生调用数 |
|---|---|
| `frontend/fund/portfolio.html` | 6 |
| `frontend/lottery/prize-calculator.html` | 2 |
| `frontend/lottery/ac-calculator.html` | 1 |
| `frontend/lottery/filter-panel.html` | 1 |
| `frontend/lottery/omission-table.html` | 1 |
| `frontend/lottery/rotation-matrix.html` | 1 |

guide 侧同款改造已跑通（9 页、含 `JSY.prompt` 组件化、长异步链改 `.then` 包），**做法可直接复用**。
注意：这 6 页里有 3 页（`prize-calculator` / `filter-panel` / `rotation-matrix`）未引 `theme.css`，需一并注入 `ui-feedback.css` + `ui-feedback.js`（组件自带样式，不依赖 theme.css）。

---

## 四、缺口 3：表格溢出兜底缺失（窄屏会顶破整页）

**6 页共 13 张表**没有任何溢出处理（`table-wrap` 与 `overflow-x` 均无）：

| 页面 | 表数 |
|---|---|
| `frontend/fund/dashboard.html` | **8**（敞口最大） |
| `frontend/lottery/prize-calculator.html` | 2 |
| `frontend/fund/portfolio.html` | 1 |
| `frontend/lottery/rotation-matrix.html` | 1 |
| `frontend/stock/stock-movers.html` | 1 |
| `frontend/stock/stock-watchlist.html` | 1 |

其中 `fund/dashboard`、`portfolio`、`stock-movers`、`stock-watchlist` 已引 `theme.css` → 若其表格挂在 `.container/.wrap/main` 内，可被兜底覆盖（需逐页确认祖先）；
`prize-calculator`、`rotation-matrix` 未引 `theme.css` → **兜底完全够不到**，必须显式处理（同 guide 侧 JS-20260924-06 的盲区教训）。

---

## 五、缺口 4：焦点环覆盖不到 9 页

JS-20260924-09 新增的 `:focus-visible` 焦点环写在 `theme.css`，因此**未引 `theme.css` 的 9 页拿不到**。
这 9 页中 4 页有 `tokens.css`、5 页两者皆无 —— 随**批次 B** 补引后即可顺带覆盖。

---

## 六、与 guide 子系统的对比

| 维度 | `jinshuiyao-guide`（31 页） | `frontend/`（37 页） |
|---|---|---|
| 排版审计 | ✅ 已收口（P0-1~P0-5、P1 六项、P2 两项） | ❌ 未开展 |
| 令牌覆盖 | ✅ 30/31（1 页遗留，需先扩令牌） | ⚠️ 4/37 |
| 反馈组件 | ✅ 9 页接入、原生对话框归零 | ❌ 0/37，残留 12 处 |
| 表格兜底 | ✅ 已补盲区（JS-20260924-06） | ⚠️ 6 页无处理 |
| 焦点环 | ✅ 全站（JS-20260924-09） | ⚠️ 9 页未覆盖 |
| 禁用色 | ✅ 0 | ✅ 0 |

---

## 七、待人工拍板

1. ~~批次顺序~~：✅ **批次 A 已完成**（2026-09-24 / JS-20260924-11，原生对话框 12 处全部换 JSY，`ui-feedback` 覆盖 0/37 → 6/37，frontend 原生对话框归零）。
2. **批次 B 重新定性（新增，最要紧）**：这 5 页是**换色工程**而非接线，是否要做、以及做成哪种，需拍板：
   - **方案甲｜重做为 L2 七色**：5 页整体换品牌色，观感显著变化，含 2207 行主仪表盘；
   - **方案乙｜维持现状**：保留其自洽的深色配色，仅登记为"已知偏离"，不动；
   - **方案丙｜先做视觉评审再定**：先出这 5 页的换色前后对照（静态），你确认后再改。
3. **批次 C**：表格溢出兜底（6 页 13 张表），需逐页确认表格祖先是否在 `.container/.wrap/main` 内。
4. 是否把 `frontend/` 的排版审计（字号 / 垂直节奏 / 容器宽度）排进后续批次 —— 本次未做该项取证。
5. 上述 9 个七色池外色值是否要纳入禁用色门禁 —— 当前门禁只查 5 个禁用 hex，这些色值合规但偏离品牌。
