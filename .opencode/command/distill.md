---
description: 把经验收集箱/交接中心里的新经验提炼成 Skill。触发词：提炼skill, 升级skill, 蒸馏, 沉淀知识库。
agent: build
---

把金水谣的经验沉淀升级为可调用的 Skill。按以下步骤执行：

1. **扫描素材**：读 `金水谣数据/log/经验收集箱.md` 最新条目、`AI协作交接中心.md` 最近几行、`工作留痕总索引.md` 最新 JS 明细，找出**已验证**（成熟度=verified）且有复用价值的经验。

2. **归类**：判断它属于哪个已有 Skill（`jinshuiyao-encoding` 编码 / `jinshuiyao-sync` 同步 / `jinshuiyao-docs` 登记），或值得新建 Skill。

3. **升级已有 Skill**（优先）：
   - 读 `.opencode/skills/<name>/SKILL.md`
   - 把新经验合并进去：更新规则/清单/案例，保持结构一致
   - 不要无限膨胀——只留"可执行的规则"，过程细节留在经验收集箱即可

4. **新建 Skill**（确属新领域时）：
   - 建 `.opencode/skills/<name>/SKILL.md`
   - frontmatter 必填：`name`（小写连字符，与目录同名）+ `description`（一句话：做什么 + 何时触发 + 前置触发关键词）
   - 正文结构：来源标注 → 核心规则（铁律式）→ 实战模板 → 自检清单 → 故障处理

5. **验证**：确认 SKILL.md 的 frontmatter 合法（name 与目录一致、description 含触发词）。

6. **登记**（铁律 0）：交接中心追加一行 + 总索引登记，说明新增/升级了哪个 Skill、提炼自哪条经验。

7. **提交**：git add + commit + push。

> 注意：Skill 是"可执行规则"层（L3），经验收集箱是"原始记录"层（L1），中间的知识库卡片层（L2）用 ai_decisions.md 承载。三层各司其职，不要混写。
