---
name: jinshuiyao-encoding
description: Windows 脚本编码铁律。Use when creating or fixing .bat, .ps1, or any script that touches Chinese text or Chinese paths on this Windows machine. Triggers on 乱码, 不是内部或外部命令, 锟斤拷, GBK, UTF-8 BOM, chcp, clip, 中文路径.
---

# Windows 脚本编码铁律（本项目亲历验证，2026-08-02 固化）

> 来源：JS-20260802-04 W63补4 全仓 bat 体检修复。三条铁律缺一不可，违反必出乱码。

## 铁律 1：.bat 文件必须 GBK(ANSI) 编码 + 首行 `chcp 936`

- **为什么**：Windows cmd 按系统 ANSI 代码页（中文系统=GBK/936）解析 bat。UTF-8 无 BOM 的中文在 cmd 下会乱码成命令报错：`'...' 不是内部或外部命令`。
- **怎么做**：保存 bat 时选 ANSI/GBK 编码；文件第一行写 `chcp 936 >nul`。
- **禁止**：bat 用 UTF-8 编码、bat 里写 `chcp 65001`（GBK 文件切 65001 后后续中文输出全乱）。

## 铁律 2：.ps1 文件必须 UTF-8 带 BOM

- **为什么**：PowerShell 5.1 读无 BOM 的 UTF-8 文件按 GBK 解码，含中文路径的脚本（本项目路径 `我的坚果云\模型` 全中文）会乱码，Set-Location 静默失败。
- **怎么做**：ps1 保存时必须带 BOM（EF BB BF 头字节）。验证：`$b[0..2]` 应为 `239,187,191`。
- 加了 BOM 后每次编辑都要复查（某些编辑器会吃掉 BOM）。

## 铁律 3：bat 永远不要把中文路径传给 PowerShell

- **为什么**：cmd 的 `%~dp0` 展开含中文路径时按 OEM 码页输出，传给 powershell 会损坏成 `?????` 或"锟斤拷"，文件找不到。
- **怎么做**：bat 只做"启动者"，真正干活放 ps1 里用 `$MyInvocation.MyCommand.Path` / `Split-Path -Parent` 自定位。bat 调 ps1 的命令行不要带路径参数。

## 实战模板

**复制启动提示词.bat（已验证方案）**：
```bat
@echo off
chcp 936 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0xxx.ps1"
```
**配套 xxx.ps1（UTF-8 BOM）**：
```powershell
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$file = Join-Path $dir "目标.txt"
$c = Get-Content -LiteralPath $file -Encoding UTF8 -Raw
Set-Clipboard -Value $c
```

## 自检清单（改完脚本必查）

1. bat → GBK + chcp 936？ps1 → UTF-8 BOM？
2. bat 里有没有把中文路径传给 powershell？（有就拆成 ps1 自定位）
3. 读文件用 `-Encoding UTF8` 显式声明（txt/md 源文件是 UTF-8 时）？
4. 实测一次：`& cmd /c "脚本.bat > 输出文件"` 后用 GBK 解码看输出，无"锟斤拷"、无"不是内部或外部命令"。

## 📥 自动蒸馏区（auto_distill 维护，勿手改）
- **2026-08-02 第六条：自动蒸馏器——经验到Skill的全自动管线**
  - ①启发式蒸馏能处理80%规则型经验，复杂语义经验进"待蒸馏队列"留给AI消化（分层：自动搬运+人工提炼）；②幂等标记文件（.distill_seen）要与内容分离管理，防误提交；③自动化管道要"先验证闭环再宣布成功"——实测首次12条→3进Skill+9待队列→幂等0→SKILL.md被自动同步提交(8fe4a4d)，才算闭环。
  - tools/auto_distill.py（纯标准库）挂进自动同步.ps1第6步：检测经验收集箱新条目（^## 日期 标题格式，sha256幂等）→抽取规则/教训/方案/处理段落→关键词归类到encoding/sync/docs三Skill→追加SKILL.md「📥自动蒸馏区」（标题去重）→无法归类写待蒸馏队列.md。全闭环：经验写入→30分钟自动蒸馏→SKILL.md自动更新→下轮自动commit+push。
  - 关联: JS-20260802-04 / 交接中心 W63补6

- **2026-08-02 第三条：自动同步脚本的黑名单必须覆盖所有不该入库的文件**
  - ①任何"自动提交"机制，其黑名单必须穷举所有不该入库的文件（运行时配置、密钥文件、环境变量、其他会话的工作区）；②上线自动机制前务必用"脏工作区 + 无源码改动"和"源码改动"两种场景实测；③force push 需谨慎但这里是唯一私有仓库工作副本，安全。
  - 黑名单加 server\config.py，reset 撤销 + force push 清理远程，验证修复生效。
  - 关联: JS-20260802-04 / 交接中心 W63补
- **2026-08-02 第四条：Windows 脚本编码规则（bat=GBK, ps1=UTF-8 BOM）**
  - ①.bat 文件必须 GBK(ANSI) 编码 + 首行 chcp 936；②.ps1 文件必须 UTF-8 带 BOM；③.bat 永远不要把中文路径作为参数传给 powershell——让 ps1 用 System.Management.Automation.InvocationInfo.MyCommand.Path 自定位；④含中文文件名操作优先用 ps1，别在 bat 里内联复杂 powershell 命令（内嵌引号在 GBK 下会碎裂）。
  - 12 个 bat 全查（8 个转 GBK+chcp936），复制启动提示词.bat 重写为 bat 调独立 ps1，protocol_handler.bat 中文注释+BASE 路径（已损坏成?）重写恢复。
  - 关联: JS-20260802-04 / 交接中心 W63补4
- **2026-08-02 第五条：经验三层蒸馏管线（L1原始→L2知识库→L3 Skill）**
  - ①Skill 只留"可执行规则"，过程细节留在 L1；②每个 Skill 的 description 必须含触发关键词（否则模型不会主动调用）；③Skill 改动要重启 opencode 生效。
  - 三层各司其职：L1 经验收集箱（日更原始记录，当天写）→ L2 ai_decisions.md/成败案例库（周更知识卡片）→ L3 .opencode/skills/*/SKILL.md（可执行规则，frontmatter 带触发词）。蒸馏工具 .opencode/command/distill.md：扫描素材→归类→升级已有/新建 Skill→验证→登记→提交。
  - 关联: JS-20260802-04 / 交接中心 W63补5
