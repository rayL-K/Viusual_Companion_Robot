[CmdletBinding()]
param(
    [string]$EnvName = "visual-companion-robot",
    [int]$Port = 8765,
    [string]$HostAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONNOUSERSITE = "1"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ServerScript = Join-Path $ProjectRoot "main\scripts\live2d_control_server.py"
$ReportsRoot = Join-Path $ProjectRoot "main\reports"
New-Item -ItemType Directory -Path $ReportsRoot -Force | Out-Null

$LocalEnvPath = Join-Path $ProjectRoot "main\config\local.env"
if (Test-Path -LiteralPath $LocalEnvPath) {
    foreach ($line in Get-Content -LiteralPath $LocalEnvPath -Encoding UTF8) {
        $trimmedLine = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmedLine) -or $trimmedLine.StartsWith("#")) {
            continue
        }

        $separatorIndex = $trimmedLine.IndexOf("=")
        if ($separatorIndex -le 0) {
            continue
        }

        $name = $trimmedLine.Substring(0, $separatorIndex).Trim()
        $value = $trimmedLine.Substring($separatorIndex + 1).Trim()
        if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        Set-Item -Path "Env:$name" -Value $value
    }
}

$Listening = Get-NetTCPConnection -LocalAddress $HostAddress -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($Listening) {
    Write-Host "Live2D 控制服务已在 $HostAddress`:$Port 运行。PID=$($Listening.OwningProcess -join ',')"
    exit 0
}

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "未找到 conda，无法启动本地控制服务。"
}

$stdoutLogPath = Join-Path $ReportsRoot "live2d_tts_server.out.log"
$stderrLogPath = Join-Path $ReportsRoot "live2d_tts_server.err.log"
$env:LIVE2D_CONTROL_HOST = $HostAddress
$env:LIVE2D_CONTROL_PORT = "$Port"
$condaCommand = Get-Command conda -ErrorAction Stop
$process = Start-Process `
    -FilePath $condaCommand.Source `
    -ArgumentList @("run", "-n", $EnvName, "python", $ServerScript) `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLogPath `
    -RedirectStandardError $stderrLogPath `
    -PassThru

$pidPath = Join-Path $ReportsRoot "live2d_tts_server.pid"
[IO.File]::WriteAllText($pidPath, "$($process.Id)`r`n", [Text.UTF8Encoding]::new($false))

$startupTimeoutSeconds = 30
$Listening = $null
for ($elapsed = 0; $elapsed -lt $startupTimeoutSeconds; $elapsed++) {
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
        $stderrPreview = (Get-Content -LiteralPath $stderrLogPath -Tail 20) -join [Environment]::NewLine
    }

    if ([string]::IsNullOrWhiteSpace($stderrPreview)) {
        throw "Live2D 控制服务启动失败，请查看 $stderrLogPath。"
    }

    throw "Live2D 控制服务启动失败，请查看 $stderrLogPath。日志尾部：$([Environment]::NewLine)$stderrPreview"
}

Write-Host "Live2D 控制服务已启动：http://$HostAddress`:$Port/health PID=$($process.Id)"
