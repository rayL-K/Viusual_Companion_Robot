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
$PackageRoot = Join-Path $ProjectRoot "main"

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 conda。请先确认 Anaconda 或 Miniconda 已加入 PATH。"
}

$envList = & conda env list
if ($envList | Select-String -SimpleMatch $EnvName -Quiet) {
    Write-Host "[Conda] 正在更新环境：$EnvName"
    & conda env update -n $EnvName -f $EnvironmentFile
}
else {
    Write-Host "[Conda] 正在创建环境：$EnvName"
    & conda env create -f $EnvironmentFile
}
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "[Conda] 正在安装当前项目包"
& conda run -n $EnvName python -m pip install --no-deps --editable $PackageRoot
exit $LASTEXITCODE
