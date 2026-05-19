[CmdletBinding()]
param(
    [switch]$SelfTest,
    [string]$EnvName = "visual-companion-robot",
    [int]$Port = 5174,
    [int]$TtsPort = 8765
)

$ErrorActionPreference = "Stop"
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StageRoot = Join-Path $ProjectRoot "main\live2d_stage"
$TestStageScript = Join-Path $PSScriptRoot "test_live2d_stage.ps1"
$TtsServerScript = Join-Path $PSScriptRoot "live2d_tts_server.ps1"
$GenerateControlScript = Join-Path $PSScriptRoot "generate_llm_control.ps1"

function Resolve-PowerShellExe {
    $fixedPwshPath = Join-Path $env:ProgramFiles "PowerShell\7\pwsh.exe"
    if (Test-Path -LiteralPath $fixedPwshPath) {
        return $fixedPwshPath
    }

    foreach ($candidate in @("pwsh.exe", "powershell.exe")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            return $command.Source
        }
    }

    throw "未找到 PowerShell 运行时。请安装 PowerShell 7，或修复系统 powershell.exe。"
}

$PowerShellExe = Resolve-PowerShellExe

function Assert-RequiredPath {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "缺少必要文件：$Path"
    }
}

function Invoke-ProjectScript {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments = @()
    )

    Assert-RequiredPath $ScriptPath
    & $PowerShellExe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "脚本执行失败：$ScriptPath，退出码 $LASTEXITCODE"
    }
}

function Pause-Menu {
    Write-Host ""
    Read-Host "按 Enter 返回菜单"
}

function Show-Menu {
    Clear-Host
    Write-Host "=== Visual Companion Robot / Live2D 网页启动菜单 ==="
    Write-Host ""
    Write-Host "项目目录：$ProjectRoot"
    Write-Host "网页地址：http://127.0.0.1:$Port/"
    Write-Host "控制服务：http://127.0.0.1:$TtsPort/health"
    Write-Host ""
    Write-Host "1. 一键开启：控制服务 + Live2D 网页 + 浏览器"
    Write-Host "2. 只开启 Live2D 网页并打开浏览器"
    Write-Host "3. 只开启本地控制 / TTS 服务"
    Write-Host "4. 只打开浏览器网页"
    Write-Host "5. 运行 Live2D 网页静态检查"
    Write-Host "6. 生成 / 刷新 LLM 控制文件"
    Write-Host "0. 退出"
    Write-Host ""
}

function Start-All {
    Invoke-ProjectScript $TestStageScript @(
        "-Open",
        "-EnvName", $EnvName,
        "-Port", "$Port",
        "-TtsPort", "$TtsPort"
    )
}

function Start-StageOnly {
    Invoke-ProjectScript $TestStageScript @(
        "-Open",
        "-NoTts",
        "-EnvName", $EnvName,
        "-Port", "$Port",
        "-TtsPort", "$TtsPort"
    )
}

function Start-ControlServiceOnly {
    Invoke-ProjectScript $TtsServerScript @(
        "-EnvName", $EnvName,
        "-Port", "$TtsPort",
        "-HostAddress", "127.0.0.1"
    )
}

function Open-StageBrowser {
    Start-Process "http://127.0.0.1:$Port/"
}

function Test-StageOnly {
    Invoke-ProjectScript $TestStageScript @(
        "-EnvName", $EnvName,
        "-Port", "$Port",
        "-TtsPort", "$TtsPort"
    )
}

function Update-ControlFile {
    Invoke-ProjectScript $GenerateControlScript @(
        "-EnvName", $EnvName
    )
}

if ($SelfTest) {
    Assert-RequiredPath $StageRoot
    Assert-RequiredPath $TestStageScript
    Assert-RequiredPath $TtsServerScript
    Assert-RequiredPath $GenerateControlScript
    Write-Host "Live2D 网页启动菜单自检通过。"
    exit 0
}

while ($true) {
    Show-Menu
    $choice = Read-Host "请选择操作"
    try {
        switch ($choice.Trim()) {
            "1" {
                Start-All
                Pause-Menu
            }
            "2" {
                Start-StageOnly
                Pause-Menu
            }
            "3" {
                Start-ControlServiceOnly
                Pause-Menu
            }
            "4" {
                Open-StageBrowser
                Pause-Menu
            }
            "5" {
                Test-StageOnly
                Pause-Menu
            }
            "6" {
                Update-ControlFile
                Pause-Menu
            }
            "0" {
                exit 0
            }
            default {
                Write-Host "无效选项：$choice"
                Pause-Menu
            }
        }
    } catch {
        Write-Host ""
        Write-Host "[错误] $($_.Exception.Message)"
        Pause-Menu
    }
}
