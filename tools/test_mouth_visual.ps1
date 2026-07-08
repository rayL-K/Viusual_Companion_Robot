[CmdletBinding()]
param(
    [string]$EnvName = "visual-companion-robot",
    [switch]$NoOpen,
    [int]$DurationMs = 180,
    [string]$MouthConfig = ""
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$GeneratorScript = Join-Path $ProjectRoot "main\scripts\generate_mouth_visual_test.py"

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 conda。请先确认 Anaconda 或 Miniconda 已加入 PATH。"
}

$envList = & conda env list
if (-not ($envList | Select-String -SimpleMatch $EnvName -Quiet)) {
    throw "未找到 Conda 环境：$EnvName。请先运行 tools\launchers\setup_conda.bat。"
}

$args = @($GeneratorScript, "--duration-ms", $DurationMs)
if ($MouthConfig.Trim().Length -gt 0) {
    $args += @("--mouth-config", $MouthConfig)
}
if (-not $NoOpen) {
    $args += "--open"
}

& conda run -n $EnvName python @args
exit $LASTEXITCODE
