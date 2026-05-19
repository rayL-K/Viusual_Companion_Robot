[CmdletBinding()]
param(
    [string]$EnvName = "visual-companion-robot"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvironmentFile = Join-Path $ProjectRoot "environment.yml"

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 conda。请先确认 Anaconda 或 Miniconda 已加入 PATH。"
}

$envList = & conda env list
if ($envList | Select-String -SimpleMatch $EnvName -Quiet) {
    Write-Host "[Conda] 环境已存在：$EnvName"
    exit 0
}

Write-Host "[Conda] 正在创建环境：$EnvName"
& conda env create -f $EnvironmentFile
exit $LASTEXITCODE
