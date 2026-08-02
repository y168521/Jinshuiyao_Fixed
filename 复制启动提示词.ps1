# 复制启动提示词到剪贴板 (PowerShell 版, UTF-8 BOM)
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$file = Join-Path $dir "启动提示词.txt"
if (Test-Path -LiteralPath $file) {
    $c = Get-Content -LiteralPath $file -Encoding UTF8 -Raw
    Set-Clipboard -Value $c
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
    Write-Host "[OK] 启动提示词已复制到剪贴板！"
    Write-Host "打开任何 AI 对话框按 Ctrl+V 粘贴即可开工"
} else {
    Write-Host "[错误] 找不到: $file"
}
Start-Sleep -Seconds 3