# Jinshuiyao auto-sync (called by Windows Task Scheduler every 30 min)
# Commits only source/docs, ignores runtime data. Exits silently when no changes.
$ErrorActionPreference = "SilentlyContinue"
$Repo = "C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"
$Log = Join-Path $Repo "金水谣数据\log\auto_sync.log"
$env:GIT_SSH_COMMAND = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=15"
$env:PYTHONIOENCODING = "utf-8"
$env:GIT_OPTIONAL_LOCKS = "0"

function Notify($msg) {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    [System.Windows.Forms.MessageBox]::Show($msg, "金水谣自动同步", "OK", "Warning") | Out-Null
}

Set-Location -LiteralPath $Repo
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

# 1) Pull remote first (laptop may have pushed).
#    Stash unstaged changes if any (pull --rebase refuses otherwise), restore after.
git stash push -u -m "auto-sync-tmp" 2>&1 | Out-Null
git -c core.quotepath=false pull --rebase origin master 2>&1 | Out-Null
$pullOk = $LASTEXITCODE -eq 0
git stash pop 2>&1 | Out-Null
if (-not $pullOk) {
    Log "pull failed (conflict or offline), skip"
    Notify "拉取 GitHub 最新代码失败（断网或冲突），本次跳过同步。请检查网络，或找 AI 帮忙看。"
    exit 1
}

# 2) Collect changed source/doc paths (exclude runtime data)
$rows = git -c core.quotepath=false status --porcelain 2>$null | Where-Object { $_ -and $_.Length -gt 3 }
$noise = @(
    "correlation_matrix.json", "predictions.json",
    "auto_audit_report.json", "brain_state.json",
    "auto_sync.log", "token_usage.json",
    "server\config.py",
    "__pycache__", ".ruff_cache", ".pytest_cache"
)
$candidates = @()
foreach ($r in $rows) {
    $p = $r.Substring(3).Trim('"').Replace("/", "\")
    $skip = $false
    foreach ($n in $noise) { if ($p -like "*$n*") { $skip = $true; break } }
    if (-not $skip) {
        $ext = [IO.Path]::GetExtension($p).ToLower()
        if ($ext -in @(".py", ".md", ".bat", ".html", ".css", ".js", ".json", ".sh")) {
            $candidates += $p
        }
    }
}
if ($candidates.Count -gt 0) {
    # 3) Stage candidates
    foreach ($c in $candidates) {
        git add -- "$c" 2>&1 | Out-Null
    }

    # 4) Commit + push only when something staged
    $staged = git diff --cached --name-only 2>$null | Where-Object { $_ }
    if ($staged.Count -gt 0) {
        git commit --no-verify -m "auto-sync: automatic sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
        git push origin master 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Log "committed and pushed ($($staged.Count) files)"
        } else {
            Log "commit ok but push failed (network?)"
            Notify "代码已提交但推送到 GitHub 失败（网络问题）。改动保留在本地，网络恢复后会自动补推。"
        }
    } else {
        Log "nothing staged, skip commit"
    }
} else {
    Log "no source changes, skip"
}

# 5) 顺带刷新 Obsidian vault(金水谣活文档 -> vault 副本, 只读联动)
& powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Administrator\Nutstore\1\我的坚果云\模型\obsidian-vault\刷新vault.ps1" 2>&1 | Out-Null

# 6) 自动蒸馏: 经验收集箱新条目 -> SKILL.md(幂等), 有改动下轮自动同步提交
$py = "D:\Project_Env\jinshuiyao_env\Scripts\python.exe"
if (Test-Path $py) {
    & $py "$Repo\tools\auto_distill.py" 2>&1 | Out-Null
}

exit 0

