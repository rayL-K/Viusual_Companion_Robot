[CmdletBinding()]
param(
    [string]$EnvName = "visual-companion-robot",
    [string]$Prompt = "请用温柔、活泼的中文女声向用户打招呼，并展示一个开心的 Live2D 表情。",
    [string]$Model = ""
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$GenerateScript = Join-Path $ProjectRoot "main\scripts\generate_control_plan.py"

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 conda。请先确认 Anaconda 或 Miniconda 已加入 PATH。"
}
if (-not $env:DEEPSEEK_API_KEY) {
    throw "缺少 DEEPSEEK_API_KEY 环境变量。为了安全，不要把 API key 写入仓库。"
}

$args = @($GenerateScript, "--prompt", $Prompt)
if ($Model.Trim().Length -gt 0) {
    $args += @("--model", $Model)
}

& conda run -n $EnvName python @args
exit $LASTEXITCODE
