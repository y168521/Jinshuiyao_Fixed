# 用户知识库

金水谣系统的个人知识库（右脑），对应 Karpathy「LLM Wiki」方法论的 **raw 证据层 + 卡片成品层** 双层结构。

## 目录结构
- `raw/` — 原始证据层：未经消化的原料（网页抓取全文、对话原文），只增不改，是知识的「事实源头」
- 本目录根层的 `.md` 文件 — 成品卡片（助手消化后写成的知识），一张卡片可引用多条 raw 证据
- `INDEX.json` — 卡片索引（由 `archive_knowledge.py` 自动维护，勿手改）
- `索引.md` — 人类可读索引（自动生成）

## 卡片格式
```
# 标题
- 记录时间：YYYY-MM-DD HH:MM:SS
- 记录者：金水谣助手
- 来源：...
- 相关：raw/文件名.md（可选）
- 标签：...
- 类型：概念页 / 实体页 / 摘要页（可选）

## 内容
正文...
```

## 使用
- 新增卡片：`python archive_knowledge.py --title "..." --tags "..." --body "..." --source "..."`
- 重建索引：`python archive_knowledge.py --rebuild`
- 体检：`python lint_knowledge.py`（每月 1 号调度器自动跑）

> 注意：`raw/` 里的文件不会进 INDEX.json（不是知识卡片），但会被体检检查「是否被卡片引用、是否为空」。
