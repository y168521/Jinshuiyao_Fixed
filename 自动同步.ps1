# Jinshuiyao auto-sync (called by Windows Task Scheduler every 30 min)
# Commits only source/docs, ignores runtime data. Exits silently when no changes.
$ErrorActionPreference = "SilentlyContinue"
$Repo = "C:\Users\Administrator\Nutstore\1\我的坚果云\模型\Jinshuiyao_Fixed"
$Log = Join-Path $Repo "金水谣数据\log\auto_sync.log"
$env:GIT_SSH_COMMAND = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=15"
$env:PYTHONIOENCODING = "utf-8"
$env:GIT_OPTIONAL_LOCKS = "0"

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
if ($candidates.Count -eq 0) {
    Log "no source changes, skip"
    exit 0
}

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
    }
} else {
    Log "nothing staged, skip commit"
}
exit 0
