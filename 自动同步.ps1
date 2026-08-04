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

    # 4) Commit + push only when something staged (带门禁, 不再 --no-verify:
    #    防止坏代码/未验证改动绕过 pre-commit 直接入库, W63补32 修复)
    $staged = git diff --cached --name-only 2>$null | Where-Object { $_ }
    if ($staged.Count -gt 0) {
        $commitOut = git commit -m "auto-sync: automatic sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-String
        $commitOk = $LASTEXITCODE -eq 0
        if (-not $commitOk) {
            $commitOut | Out-File -FilePath $Log -Append -Encoding utf8
            git reset --mixed 2>&1 | Out-Null
            Log "commit blocked by pre-commit gate, staged files reset (see above)"
            exit 1
        }
        git push origin master 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Log "committed and pushed ($($staged.Count) files)"
            # 4.1) 提交后把关键活文档拷回根目录并校准 mtime
            #     （GITSYNC 双向检查要求 repo 不领先根目录，JS-20260804-XX 校准）
            $keyFiles = @(
                "启动提示词.txt", "复制启动提示词.bat",
                "金水谣_纲.md", "金水谣_契.md", "金水谣_录.md",
                "AI协作交接中心.md", "工作留痕总索引.md",
                "金水谣助手门户.html"
            )
            $RootDir = Split-Path -Parent $Repo
            foreach ($kf in $keyFiles) {
                $repoPath = Join-Path $Repo $kf
                $rootPath = Join-Path $RootDir $kf
                if ((Test-Path -LiteralPath $repoPath) -and (Test-Path -LiteralPath $rootPath)) {
                    Copy-Item -LiteralPath $repoPath -Destination $rootPath -Force
                    $src = Get-Item -LiteralPath $repoPath
                    $dst = Get-Item -LiteralPath $rootPath
                    $dst.LastWriteTime = $src.LastWriteTime
                }
            }
            Log "key docs mirrored back to root dir"
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

# 7) 数据真实性自动守卫: 全量检测足彩/股票/彩票数据真实性, 结果写 data_truth.log
#    状态变化(健康<->降级<->异常)时弹窗提醒, 平时静默
if (Test-Path $py) {
    $truthOut = & $py "$Repo\tools\auto_data_truth.py" 2>&1
    $truthCode = $LASTEXITCODE
    if ($truthOut -match "STATUS-CHANGED") {
        Notify "数据真实性检测状态变化: $(($truthOut | Select-Object -Last 1))"
    } elseif ($truthCode -eq 2) {
        Log "data truth: critical (exit=$truthCode)"
    } elseif ($truthCode -ne 0) {
        Log "data truth: degraded (exit=$truthCode)"
    }
}


# 8) 知识网关索引保鲜: 重生成知识网关索引.md(资产规模/入口), 供外部AI第一入口读
if (Test-Path $py) {
    & $py "$Repo\tools\gen_knowledge_index.py" 2>&1 | Out-Null
}

exit 0
