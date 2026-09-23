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

1. **批次顺序**：建议 A → B → C（A 最机械、B 需逐页核对派生色、C 需逐页确认表格祖先）。
2. **批次 B 的派生中性色**：若某页派生色在令牌中无等价物，是「先扩展 tokens.css」还是「该页暂不接主题切换」——需逐页决定。
3. 是否把 `frontend/` 的排版审计（字号/垂直节奏/容器宽度）也排进后续批次 —— 本次未做该项取证。
