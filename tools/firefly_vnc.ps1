[CmdletBinding()]
param(
    [ValidateSet("Start", "Connect")]
    [string]$Mode = "Start",
    [string]$FireflyHost = "firefly",
    [string]$FireflyIP = "100.85.172.117",
    [int]$LocalVncPort = 5900,
    [int]$RemoteVncPort = 5900,
    [string]$ViewerTarget = "127.0.0.1::5900",
    [switch]$SelfTest,
    [switch]$NoElevate
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RealVncViewerPage = "https://www.realvnc.com/en/connect/download/viewer/windows/"
$RealVncViewerStandaloneUrl = "https://downloads.realvnc.com/download/file/viewer.files/VNC-Viewer-7.15.1-Windows-64bit.exe"
$RealVncViewerExe = Join-Path $env:LOCALAPPDATA "VisualCompanionRobot\VNC-Viewer.exe"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Restart-AsAdministrator {
    $args = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $PSCommandPath,
        "-Mode",
        $Mode,
        "-FireflyHost",
        $FireflyHost,
        "-FireflyIP",
        $FireflyIP,
        "-LocalVncPort",
        $LocalVncPort,
        "-RemoteVncPort",
        $RemoteVncPort,
        "-ViewerTarget",
        $ViewerTarget
    )
    Start-Process -FilePath "pwsh.exe" -ArgumentList $args -WorkingDirectory $ProjectRoot -Verb RunAs
}

function Get-TailscaleExe {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Tailscale\tailscale.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    $command = Get-Command "tailscale.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "未找到 tailscale.exe。请安装或修复 Windows 版 Tailscale。"
}

function Assert-CommandExists {
    param([string]$CommandName, [string]$InstallHint)

    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "$CommandName 不可用。$InstallHint"
    }
}

function Invoke-ExternalOk {
    param([string]$FilePath, [string[]]$Arguments)

    & $FilePath @Arguments
    return $LASTEXITCODE -eq 0
}

function Start-NetworkServices {
    Write-Host "[1/9] 正在启动 Windows 网络服务..."
    Set-Service -Name "iphlpsvc" -StartupType Automatic
    Start-Service -Name "iphlpsvc" -ErrorAction SilentlyContinue
    Start-Service -Name "Tailscale" -ErrorAction SilentlyContinue
}

function Ensure-TailscaleReady {
    param([string]$TailscaleExe)

    Write-Host "[2/9] 正在检查 Tailscale 登录状态..."
    if (Invoke-ExternalOk $TailscaleExe @("status")) {
        return
    }

    Write-Host "Tailscale 尚未就绪，正在尝试启动..."
    if (-not (Invoke-ExternalOk $TailscaleExe @("up", "--unattended", "--timeout", "30s"))) {
        Write-Host "如果上方输出了登录链接，请打开链接并批准这台 Windows 设备。"
        Read-Host "完成后按 Enter 继续"
    }

    if (Invoke-ExternalOk $TailscaleExe @("status")) {
        return
    }

    Write-Host "Tailscale 仍未就绪，正在尝试重置本地 Tailscale 选项..."
    if (-not (Invoke-ExternalOk $TailscaleExe @("up", "--reset", "--unattended", "--timeout", "30s"))) {
        Write-Host "如果上方输出了登录链接，请打开链接并批准这台 Windows 设备。"
        Read-Host "完成后按 Enter 继续"
    }

    if (-not (Invoke-ExternalOk $TailscaleExe @("status"))) {
        throw "Tailscale 未连接。请手动启动 Tailscale 后重新运行 tools\launchers\start.bat。"
    }
}

function Wait-FireflyOnline {
    param([string]$TailscaleExe)

    Write-Host "[3/9] 正在等待 Firefly 接入 Tailscale..."
    for ($index = 1; $index -le 60; $index += 1) {
        if (Invoke-ExternalOk $TailscaleExe @("ping", "--c=1", "--timeout=5s", $FireflyIP)) {
            Write-Host "Firefly 已在线。"
            return
        }
        Write-Host "暂时无法访问 Firefly，等待 5 秒后重试... $index/60"
        Start-Sleep -Seconds 5
    }
    throw "Firefly 未能通过 Tailscale 连通。请确认开发板已通电、已联网，并且在 Tailscale 中在线。"
}

function Test-SshAccess {
    Write-Host "[4/9] 正在检查免密 SSH..."
    if (-not (Invoke-ExternalOk "ssh.exe" @("-o", "BatchMode=yes", "-o", "ConnectTimeout=8", $FireflyHost, "hostname"))) {
        throw "SSH 连接 Firefly 失败。预期可执行命令：ssh $FireflyHost"
    }
}

function Stop-OldTunnels {
    Write-Host "[5/9] 正在清理旧的本地 SSH 隧道..."
    $vncPattern = "$LocalVncPort`:127\.0\.0\.1:$RemoteVncPort"
    Get-CimInstance Win32_Process -Filter "name = 'ssh.exe'" |
        Where-Object {
            $_.CommandLine -match '(^| )-L( |$)' -and
            ($_.CommandLine -match $vncPattern -or $_.CommandLine -match '3390:127\.0\.0\.1:3389')
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

function Restart-RemoteX11Vnc {
    Write-Host "[6/9] 正在启动 Firefly x11vnc 物理桌面服务..."
    $remoteCommand = "sudo systemctl restart x11vnc && sudo systemctl is-active --quiet x11vnc && for i in 1 2 3 4 5; do ss -ltn 2>/dev/null | grep -q '127.0.0.1:5900' && exit 0; sleep 1; done; exit 1"
    if (-not (Invoke-ExternalOk "ssh.exe" @($FireflyHost, $remoteCommand))) {
        throw "Firefly 上的 x11vnc 启动失败。可尝试：ssh $FireflyHost `"sudo systemctl status x11vnc`""
    }
}

function Test-LocalPortListening {
    $connection = Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $LocalVncPort -State Listen -ErrorAction SilentlyContinue
    return $null -ne $connection
}

function Start-VncTunnel {
    Write-Host "[7/9] 正在创建 VNC 本地 SSH 隧道..."
    if (-not (Test-LocalPortListening)) {
        $forward = "$LocalVncPort`:127.0.0.1:$RemoteVncPort"
        Start-Process -WindowStyle Hidden -FilePath "ssh.exe" -ArgumentList @("-N", "-L", $forward, $FireflyHost)
        Start-Sleep -Seconds 2
    }
    if (-not (Test-LocalPortListening)) {
        throw "本地 VNC 隧道创建失败。可手动尝试：ssh -N -L $LocalVncPort`:127.0.0.1:$RemoteVncPort $FireflyHost"
    }
}

function Find-VncViewer {
    $candidates = @(
        $RealVncViewerExe,
        (Join-Path $env:ProgramFiles "RealVNC\VNC Viewer\vncviewer.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "RealVNC\VNC Viewer\vncviewer.exe"),
        (Join-Path $env:ProgramFiles "TightVNC\tvnviewer.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "TightVNC\tvnviewer.exe"),
        (Join-Path $env:ProgramFiles "TigerVNC\vncviewer.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "TigerVNC\vncviewer.exe")
    )
    return $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

function Ensure-VncViewer {
    Write-Host "[8/9] 正在确认 VNC Viewer 可用..."
    $viewer = Find-VncViewer
    if ($viewer) {
        return $viewer
    }

    $viewerDir = Split-Path $RealVncViewerExe -Parent
    New-Item -ItemType Directory -Force -Path $viewerDir | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri $RealVncViewerStandaloneUrl -OutFile $RealVncViewerExe
    if (Test-Path $RealVncViewerExe) {
        return $RealVncViewerExe
    }

    Start-Process $RealVncViewerPage
    throw "VNC Viewer 不可用，已打开下载页面。"
}

function Open-VncViewer {
    param([string]$ViewerPath)

    Write-Host "[9/9] 正在打开 VNC Viewer..."
    Start-Process -FilePath $ViewerPath -ArgumentList $ViewerTarget
}

function Invoke-SelfTest {
    Assert-CommandExists "pwsh.exe" "请安装 PowerShell 7.1 或更新版本。"
    Assert-CommandExists "ssh.exe" "请启用 Windows OpenSSH 客户端。"
    Write-Host "PowerShell: $($PSVersionTable.PSVersion)"
    Write-Host "Mode: $Mode"
    Write-Host "Firefly: $FireflyHost ($FireflyIP)"
    Write-Host "VNC target: $ViewerTarget"
}

try {
    Set-Location $ProjectRoot
    if ($SelfTest) {
        Invoke-SelfTest
        exit 0
    }

    if ($Mode -eq "Start" -and -not $NoElevate -and -not (Test-IsAdministrator)) {
        Write-Host "正在请求管理员权限..."
        Restart-AsAdministrator
        exit 0
    }

    Assert-CommandExists "ssh.exe" "请启用 Windows OpenSSH 客户端。"

    Write-Host ""
    Write-Host "=== Visual Companion Robot VNC ==="
    Write-Host "Firefly: $FireflyHost ($FireflyIP)"
    Write-Host "VNC:     $ViewerTarget"
    Write-Host ""

    if ($Mode -eq "Start") {
        $tailscaleExe = Get-TailscaleExe
        Start-NetworkServices
        Ensure-TailscaleReady $tailscaleExe
        Wait-FireflyOnline $tailscaleExe
    }

    Test-SshAccess
    Stop-OldTunnels
    Restart-RemoteX11Vnc
    Start-VncTunnel
    $viewer = Ensure-VncViewer
    Open-VncViewer $viewer

    Write-Host ""
    Write-Host "=== 已就绪 ==="
    Write-Host "VNC Viewer 连接目标：$ViewerTarget"
    Write-Host "当前隧道方案不需要单独输入 VNC 密码。"
    exit 0
}
catch {
    Write-Host ""
    Write-Host "[错误] $($_.Exception.Message)"
    Write-Host "流程未完成。"
    exit 1
}
