[CmdletBinding()]
param(
    [switch]$Open,
    [switch]$GenerateControl,
    [switch]$NoTts,
    [switch]$NoEmotion,
    [string]$EnvName = "visual-companion-robot",
    [int]$Port = 5174,
    [int]$TtsPort = 8765
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StageRoot = Join-Path $ProjectRoot "main\live2d_stage"
$GenerateScript = Join-Path $ProjectRoot "main\scripts\generate_control_plan.py"
$TtsScript = Join-Path $ProjectRoot "tools\live2d_tts_server.ps1"
$EmotionScript = Join-Path $ProjectRoot "tools\emotion_server.ps1"
$Utf8Runner = Join-Path $ProjectRoot "tools\invoke_utf8_ps1.ps1"

function Invoke-Utf8ProjectScript {
    param([string]$ScriptPath, [string[]]$Arguments = @())

    if ($PSVersionTable.PSVersion.Major -ge 6) {
        & $ScriptPath @Arguments
    }
    else {
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $Utf8Runner $ScriptPath @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "脚本执行失败：$ScriptPath，退出码 $LASTEXITCODE"
    }
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "未找到 node。请先安装 Node.js 18 或更新版本。"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "未找到 npm。请先安装 Node.js。"
}

Push-Location $StageRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $StageRoot "node_modules"))) {
        npm install
    }

    npm run check
}
finally {
    Pop-Location
}

if ($GenerateControl) {
    if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
        throw "未找到 conda，无法在本地 Conda 环境中调用 LLM 控制生成脚本。"
    }
    & conda run -n $EnvName python $GenerateScript
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if ($Open) {
    if (-not $NoTts) {
        try {
            Invoke-Utf8ProjectScript $TtsScript @("-EnvName", $EnvName, "-Port", "$TtsPort")
        }
        catch {
            Write-Warning "本地 TTS 服务启动失败：$($_.Exception.Message)"
            Write-Warning "展示台仍会打开，但本地语音与离线识别会显示不可用状态。"
        }
    }

    if (-not $NoEmotion) {
        try {
            Invoke-Utf8ProjectScript $EmotionScript @("-EnvName", $EnvName, "-Port", "8766")
        }
        catch {
            Write-Warning "FER+ 情绪服务启动失败：$($_.Exception.Message)"
            Write-Warning "展示台仍会打开，情绪识别将回退到浏览器 blendshape 规则。"
        }
    }

    $npmCommand = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
    if ($null -eq $npmCommand) {
        $npmCommand = Get-Command npm -ErrorAction Stop
    }

    $stdoutLogPath = Join-Path $ProjectRoot "main\reports\live2d_stage_vite.out.log"
    $stderrLogPath = Join-Path $ProjectRoot "main\reports\live2d_stage_vite.err.log"
    New-Item -ItemType Directory -Path (Split-Path -Parent $stdoutLogPath) -Force | Out-Null

    $existingStage = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($existingStage) {
        Write-Host "Live2D Stage 已在 127.0.0.1:$Port 运行。PID=$($existingStage.OwningProcess -join ',')"
    }
    else {
        Start-Process `
            -FilePath $npmCommand.Source `
            -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$Port") `
            -WorkingDirectory $StageRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLogPath `
            -RedirectStandardError $stderrLogPath

        Start-Sleep -Seconds 3
    }

    Start-Process "http://127.0.0.1:$Port/"
    Write-Host "Live2D Stage 已启动：http://127.0.0.1:$Port/"
}
