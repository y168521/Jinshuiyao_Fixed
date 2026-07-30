# 原始证据：Karpathy LLM Wiki 方法论（2026-04）

- 抓取时间：2026-07-18
- 原始来源：Andrej Karpathy 于 2026-04 发布的 LLM Wiki gist 原文 + 多篇社区深度解读
- 用途：作为「知识库对比与整合方案」的原始依据，未被消化，仅存档

## 原文要点摘录（raw）
- 核心比喻：Obsidian = IDE，LLM = 程序员，Wiki = 代码库（codebase）。
- 知识编译（knowledge compilation）vs 知识检索（RAG）：编译产出可长期复利的「活资产」，检索每次从头找。
- 三层结构：raw 证据层 / The Wiki 知识层 / The Schema 配置层。
- 页面类型：摘要页(summary)、实体页(entity)、概念页(concept)、综述页(overview)、索引页(index)。
- 三大工作流：Ingest 摄入、Query 查询并写回、Lint 健康检查。
- 与 RAG / 微软 GraphRAG 的关系：Wiki 更像「编译后的知识」，GraphRAG 是「检索时的图增强」。
- 四大风险：幻觉复利(hallucination compounding)、过度确定性、可审计性(auditability)、团队扩展(team scaling)。
- 治理原则：保留 raw 证据可溯源、Lint 定期体检、关键结论要能回到原始依据。

## 社区 6 条生产经验（raw 摘录）
1. 先有 raw 层再写卡片，避免无源之水。
2. 卡片之间要互链，形成「知识图谱」而非孤岛。
3. Lint 要能抓「占位符 / 空正文 / 幻觉标记」。
4. 概念页写「一句话 + 要点」，实体页写「事实」，摘要页写「汇总 + 链接」。
5. 知识规模在百篇内不需要向量库/RAG，纯文件即可。
6. 答完问题要「回写」：把答案沉淀成卡片，闭环才成立。
