---
name: jinshuiyao-sync
description: 金水谣自动同步与多机协作规范。Use when working with 自动同步.ps1, the Jinshuiyao自动同步 scheduled task, 刷新vault.ps1, Obsidian vault sync, GitHub push/pull between desktop and laptop, or when deciding what files may be auto-committed. Triggers on 自动同步, auto-sync, vault刷新, 计划任务, 笔记本同步, .gitignore 策略.
---

# 金水谣自动同步与多机协作规范（W63 系列落地，2026-08-02 固化）

## 系统架构

```
台式机 (本机)                                GitHub                    笔记本
┌─────────────────────────────┐           ┌───────────┐           ┌──────────────────┐
│ 计划任务"Jinshuiyao自动同步" │           │ y168521/  │           │ 计划任务"笔记本同步"│
│ 每30分钟:                   │───────────│ Jinshuiyao│───────────│ 每30分钟:         │
│ ①git pull --rebase         │  SSH push │ _Fixed    │  SSH push │ ①git pull         │
│ ②收集源码改动→commit→push   │  pull     │ (master)  │  pull     │ ②收集改动→push     │
│ ③刷新vault.ps1→Obsidian    │           └───────────┘           └──────────────────┘
└─────────────────────────────┘                                     Obsidian vault 在坚果云
```

- 台式机脚本：`自动同步.ps1`（仓库根，UTF-8 BOM）
- Obsidian 联动：`刷新vault.ps1`（vault 目录内，UTF-8 BOM）+ `link_vault.py`（注入 wikilink）
- 笔记本说明：`deliverables/笔记本同步配置说明.md`
- 日志：`金水谣数据/log/auto_sync.log`（git 同步）、`obsidian-vault/refresh.log`（vault 刷新）

## 铁律 A：永远不入库的文件（黑名单）

自动同步的 noise 列表 + 手动提交都要遵守：

| 文件 | 原因 |
|------|------|
| `server/config.py` | 运行环境配置，可能含其他会话改动/敏感信息，永不自动提交 |
| `金水谣数据/correlation_matrix.json` | 运行时数据 |
| `金水谣数据/predictions.json` | 运行时数据 |
| `金水谣数据/log/auto_audit_report.json` | 审计运行时数据 |
| `金水谣数据/log/brain_state.json` | 状态数据 |
| `金水谣数据/log/auto_sync.log` | 同步日志 |
| `金水谣数据/log/token_usage.json` | 用量数据 |
| `__pycache__` / `.ruff_cache` / `.pytest_cache` | 缓存 |

**手动 `git add -A` 前必须检查**：黑名单文件有没有被卷进来（2026-08-02 曾因 add -A 误提交 config.py，黑名单只管自动同步管不了手动）。

## 铁律 B：Obsidian vault 是只读副本

- vault（`模型/obsidian-vault/`）里的文档是**单向同步的副本**，原件在金水谣仓库。
- **不要在 vault 里改文档**——每 30 分钟自动刷新会覆盖，白改。
- 想改文档：改仓库里的原件（或让 AI 改），刷新自动带过去。
- 刷新触发：计划任务每 30 分钟调 `自动同步.ps1`，它最后一步无论有无 git 改动都刷 vault（修过的 bug：no changes 直接 exit 会跳过刷新）。

## 铁律 C：多机协作

- 两台机器**不要同时改同一个文件**（pull 会冲突）。
- 冲突时：`git stash` → `git pull` → `git stash pop`，报错发 AI 处理。
- 笔记本 push 后台式机会自动合并；台式机改完 30 分钟内笔记本自动拉到。

## 故障处理

| 症状 | 处理 |
|------|------|
| pull 失败/断网 | 自动同步弹窗提醒（Notify 函数），跳过本次，网络恢复自动补推 |
| 推送失败 | 改动保留本地，弹窗提示，下次自动重试 |
| 自动同步"静默失败" | 查 `金水谣数据/log/auto_sync.log` 尾部 |
| vault 没更新 | 查 `obsidian-vault/refresh.log`；手动跑 `刷新vault.ps1` |

## 变更注意

- 修改 `自动同步.ps1` 后必须复查：UTF-8 BOM 还在吗？（编辑工具会吃 BOM）
- 修改后实测完整链路：有改动 → commit+push；无改动 → 只刷 vault。
- 新增"不该入库"的文件时，**同时**加进 `自动同步.ps1` 的 noise 列表（只加黑名单不够）。
