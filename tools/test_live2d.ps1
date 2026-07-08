[CmdletBinding()]
param(
    [string]$EnvName = "visual-companion-robot",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CompatScript = Join-Path $ProjectRoot "main\scripts\check_python_compat.py"
$AssetTestScript = Join-Path $ProjectRoot "main\scripts\test_live2d_assets.py"
$TestsRoot = Join-Path $ProjectRoot "main\tests"

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 conda。请先确认 Anaconda 或 Miniconda 已加入 PATH。"
}

$envList = & conda env list
if (-not ($envList | Select-String -SimpleMatch $EnvName -Quiet)) {
    throw "未找到 Conda 环境：$EnvName。请先运行 tools\launchers\setup_conda.bat。"
}

& conda run -n $EnvName python $CompatScript
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& conda run -n $EnvName python -m unittest discover -s $TestsRoot -p "test_*.py"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& conda run -n $EnvName python $AssetTestScript @ScriptArgs
exit $LASTEXITCODE
