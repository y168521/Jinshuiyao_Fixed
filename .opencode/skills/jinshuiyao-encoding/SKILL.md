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
