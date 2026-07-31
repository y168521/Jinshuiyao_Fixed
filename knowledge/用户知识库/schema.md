# 用户知识库 · Schema

金水谣知识卡片的数据规范（单一真源：`archive_knowledge.py` 与 `lint_knowledge.py`）。

## 文件布局
- 成品卡片：`用户知识库/<日期>_<slug>.md`（根层，`slug` 由 `archive_knowledge.slugify()` 生成）
- 原始证据：`用户知识库/raw/<日期>_evidence_<主题>.md`（只增不改）
- 索引：`INDEX.json`（数组，元素字段见下）+ `索引.md`（人类可读镜像）

## 卡片文件格式（Markdown）
```
# <标题>
- 记录时间：YYYY-MM-DD HH:MM:SS
- 记录者：<作者，默认 金水谣助手>
- 来源：<可选>
- 相关：raw/xxx.md（可选，可多行）
- 标签：<逗号分隔，可选>
- 类型：概念页 | 实体页 | 摘要页（可选）

## 内容
<正文，必填，非空>
```

## INDEX.json 条目字段
| 字段 | 必填 | 说明 |
|------|------|------|
| title | 是 | 卡片标题 |
| file | 是 | 卡片文件名（须真实存在于根层，否则 Lint 报「孤儿索引」） |
| tags | 否 | 标签数组 |
| source | 否 | 来源说明 |
| time | 否 | 记录时间字符串 |

## 体检规则（lint_knowledge.py）
- 错误：占位符（`DEEPSEEK_WAS_CALLED` / `PLACEHOLDER` / `TODO` 等）、空正文、索引指向不存在的文件（孤儿索引）、raw 证据为空
- 警告：卡片不在索引、索引重复标题、缺少元文件（README.md / 索引.md / schema.md）、风险登记册问题

## 铁律
1. `raw/` 只增不改，是事实源头
2. 卡片引用 raw 证据用「相关」字段写相对路径 `raw/文件名.md`
3. 索引一律用 `archive_knowledge.py` 维护，禁止手改（手改必失配）
4. 验证纪律：新增/修改卡片后必须跑 `lint_knowledge.py` 确认无错误
