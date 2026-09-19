# =============================================================================
# 金水谣 · 收工门禁每日任务执行器 (closeout gate daily runner)
#
# 被 Windows 计划任务 "Jinshuiyao收工门禁" 每日 23:30 调用（静默，无弹窗）。
# 由 JS-20260920-07 创建：收工门禁此前只能在 AI 会话里手动跑，第 8 闸（本轮事项
# 反向自查）等于半个门禁 —— 没人跑的时候就没人拦。
#
# 行为：
#   1. 定位 python（候选路径探测，计划任务环境 PATH 很窄，不能裸调 python）
#   2. 空闲跳过：当天没有任何「非 auto-sync 提交」且工作区干净 → 视为非工作日，
#      记 SKIP 不告警（否则每个不干活的夜晚都会 FAIL，狼来了）
#   3. 跑 tools/closeout_gate.py，全量输出追加进 closeout_gate_task.log
#   4. RC!=0 写 closeout_gate_task.FAIL 标记文件；下次通过自动清除
#
# 编码说明：本文件必须保存为 **UTF-8 带 BOM**。Windows PowerShell 5.1 对无 BOM 的
#          .ps1 按 ANSI 解析，里面的中文路径会变乱码。改完请确认 BOM 还在。
# =============================================================================
param([switch]$Force)

$ErrorActionPreference = 'Continue'

$Root   = Split-Path -Parent $PSScriptRoot          # ...\Jinshuiyao_Fixed
$LogDir = Join-Path $Root '金水谣数据\log'
if (-not (Test-Path -LiteralPath $LogDir)) { $LogDir = $Root }
$Log  = Join-Path $LogDir 'closeout_gate_task.log'
$Flag = Join-Path $LogDir 'closeout_gate_task.FAIL'

function Log($m) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
    [IO.File]::AppendAllText($Log, $line + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    # 日志超 256KB 自动瘦身，只留最后 300 行
    if ((Get-Item -LiteralPath $Log -ErrorAction SilentlyContinue).Length -gt 262144) {
        $tail = Get-Content -LiteralPath $Log -Tail 300 -Encoding UTF8
        [IO.File]::WriteAllLines($Log, $tail, [Text.UTF8Encoding]::new($false))
    }
}

function Resolve-Py {
    foreach ($c in @(
        'E:\Project_Env\jinshuiyao_env\Scripts\python.exe',
        'D:\Project_Env\jinshuiyao_env\Scripts\python.exe',
        'C:\Project_Env\jinshuiyao_env\Scripts\python.exe',
        'E:\Python314\python.exe',
        'C:\Python314\python.exe'
    )) { if (Test-Path -LiteralPath $c) { return $c } }
    $w = Get-Command python -ErrorAction SilentlyContinue
    if ($w) { return $w.Source }
    return $null
}

function Resolve-Git {
    $cands = @()
    $cands += (Get-ChildItem "$env:LOCALAPPDATA\..\.workbuddy\binaries\PortableGit\versions\*\cmd\git.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    $cands += 'E:\下载\Git\bin\git.exe'
    $cands += 'C:\Program Files\Git\cmd\git.exe'
    $cands += 'C:\Program Files (x86)\Git\cmd\git.exe'
    foreach ($c in $cands) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    $w = Get-Command git -ErrorAction SilentlyContinue
    if ($w) { return $w.Source }
    return $null
}

$py = Resolve-Py
if (-not $py) {
    Log 'FATAL: 找不到可用 python.exe（候选路径全部不存在），收工门禁未执行'
    exit 2
}

# --- 空闲跳过（非工作日不告警）---------------------------------------------
if (-not $Force) {
    $git = Resolve-Git
    if ($git) {
        $today = (Get-Date).ToString('yyyy-MM-dd')
        Push-Location -LiteralPath $Root
        $mine  = @(& $git log "--since=$today 00:00:00" --grep='auto-sync' --invert-grep --oneline 2>$null | Where-Object { $_ })
        $dirty = @(& $git status --porcelain 2>$null | Where-Object { $_ })
        Pop-Location
        if ($mine.Count -eq 0 -and $dirty.Count -eq 0) {
            Log 'SKIP: 今日无 AI 协作痕迹（无非 auto-sync 提交、工作区干净），不跑门禁'
            if (Test-Path -LiteralPath $Flag) { Remove-Item -LiteralPath $Flag -Force -ErrorAction SilentlyContinue }
            exit 0
        }
    } else {
        Log 'WARN: 找不到 git.exe，空闲跳过失效（本次仍会执行门禁）'
    }
}

# --- 执行门禁 ---------------------------------------------------------------
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'

$out = & $py (Join-Path $Root 'tools\closeout_gate.py') 2>&1 | Out-String
$rc  = $LASTEXITCODE

Log "=== closeout_gate RC=$rc ==="
foreach ($ln in ($out -split "`r?`n")) {
    if ($ln.Trim().Length -gt 0) { Log "  $ln" }
}

if ($rc -ne 0) {
    [IO.File]::WriteAllText(
        $Flag,
        "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') 收工门禁未通过 (RC=$rc)，详见 closeout_gate_task.log" + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false))
} elseif (Test-Path -LiteralPath $Flag) {
    Remove-Item -LiteralPath $Flag -Force -ErrorAction SilentlyContinue
    Log 'FLAG CLEARED: 门禁已通过，标记文件已清除'
}

exit $rc
