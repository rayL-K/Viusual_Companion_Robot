[CmdletBinding()]
param(
    [string]$EnvName = "visual-companion-robot",
    [int]$Port = 8766,
    [string]$HostAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONNOUSERSITE = "1"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ModelPath = Join-Path $ProjectRoot "main\models\emotion\emotion-ferplus-8.onnx"
$ReportsRoot = Join-Path $ProjectRoot "main\reports"
New-Item -ItemType Directory -Path $ReportsRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "缺少 FER+ 模型。请先运行：conda run -n $EnvName python tools\download_emotion_ferplus.py"
}

$Listening = Get-NetTCPConnection -LocalAddress $HostAddress -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Listening) {
    Write-Host "FER+ 情绪服务已在 $HostAddress`:$Port 运行。PID=$($Listening.OwningProcess -join ',')"
    exit 0
}

$condaCommand = Get-Command conda -ErrorAction Stop
$env:PYTHONPATH = Join-Path $ProjectRoot "main\src"
$stdoutLogPath = Join-Path $ReportsRoot "emotion_server.out.log"
$stderrLogPath = Join-Path $ReportsRoot "emotion_server.err.log"
$process = Start-Process `
    -FilePath $condaCommand.Source `
    -ArgumentList @("run", "-n", $EnvName, "python", "-m", "visual_companion_robot.perception.emotion_server") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLogPath `
    -RedirectStandardError $stderrLogPath `
    -PassThru

for ($elapsed = 0; $elapsed -lt 30; $elapsed++) {
    Start-Sleep -Seconds 1
    $Listening = Get-NetTCPConnection -LocalAddress $HostAddress -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($Listening) {
        break
    }
    $process.Refresh()
    if ($process.HasExited) {
        break
    }
}

if (-not $Listening) {
    $stderrPreview = ""
    if (Test-Path -LiteralPath $stderrLogPath) {
        $stderrPreview = (Get-Content -LiteralPath $stderrLogPath -Encoding UTF8 -Tail 20) -join [Environment]::NewLine
    }
    throw "FER+ 情绪服务启动失败。$([Environment]::NewLine)$stderrPreview"
}

$pidPath = Join-Path $ReportsRoot "emotion_server.pid"
[IO.File]::WriteAllText($pidPath, "$($process.Id)`r`n", $utf8)
Write-Host "FER+ 情绪服务已启动：http://$HostAddress`:$Port/emotion PID=$($process.Id)"
