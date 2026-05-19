[CmdletBinding()]
param(
    [string]$RemoteHost = "192.168.5.83",
    [string]$RemoteUser = "firefly",
    [string]$RemoteRoot = "/home/firefly/wwk/Visual_Companion_Robot",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\id_ed25519_firefly",
    [switch]$NoDelete
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Remote = "${RemoteUser}@${RemoteHost}"
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("vcr-sync-" + [Guid]::NewGuid().ToString("N"))
$Stage = Join-Path $TempRoot "stage"
$Archive = Join-Path $TempRoot "Visual_Companion_Robot.tar.gz"
$RemoteArchive = "/tmp/Visual_Companion_Robot.tar.gz"
$RemoteStage = "/tmp/Visual_Companion_Robot_sync"

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [int[]]$AllowedExitCodes = @(0)
    )

    & $FilePath @ArgumentList
    $exitCode = $LASTEXITCODE
    if ($AllowedExitCodes -notcontains $exitCode) {
        throw "$FilePath 执行失败，退出码：$exitCode"
    }
}

try {
    if (-not (Test-Path $KeyPath)) {
        throw "未找到 SSH 密钥：$KeyPath"
    }

    New-Item -ItemType Directory -Force -Path $Stage | Out-Null

    Write-Host "[同步] 正在整理本地项目：$ProjectRoot"
    $robocopyArgs = @(
        $ProjectRoot,
        $Stage,
        "/MIR",
        "/XD", ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "dist", "build",
        "/XF", "*.pyc", "*.pyo", "*.log"
    )
    Invoke-CheckedProcess -FilePath "robocopy.exe" -ArgumentList $robocopyArgs -AllowedExitCodes @(0, 1, 2, 3, 4, 5, 6, 7)

    Write-Host "[同步] 正在创建传输压缩包"
    Invoke-CheckedProcess -FilePath "tar.exe" -ArgumentList @("-czf", $Archive, "-C", $Stage, ".")

    Write-Host "[同步] 正在确认 Firefly 目标目录：${Remote}:${RemoteRoot}"
    Invoke-CheckedProcess -FilePath "ssh.exe" -ArgumentList @(
        "-i", $KeyPath,
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        $Remote,
        "mkdir -p '$RemoteRoot'"
    )

    Write-Host "[同步] 正在上传压缩包"
    Invoke-CheckedProcess -FilePath "scp.exe" -ArgumentList @(
        "-i", $KeyPath,
        "-o", "IdentitiesOnly=yes",
        $Archive,
        "$Remote`:$RemoteArchive"
    )

    $deleteFlag = if ($NoDelete) { "0" } else { "1" }
    $remoteCommand = @"
set -e
dest='$RemoteRoot'
archive='$RemoteArchive'
stage='$RemoteStage'
delete_flag='$deleteFlag'

case "`$dest" in
  /home/firefly/wwk/Visual_Companion_Robot*) ;;
  *) echo "[同步:错误] 目标目录不安全：`$dest" >&2; exit 66 ;;
esac

rm -rf "`$stage"
mkdir -p "`$stage" "`$dest"
tar -xzf "`$archive" -C "`$stage"

if [ "`$delete_flag" = "1" ]; then
  rsync -a --delete "`$stage"/ "`$dest"/
else
  rsync -a "`$stage"/ "`$dest"/
fi

rm -rf "`$stage" "`$archive"
echo "[同步] Firefly 目录已就绪：`$dest"
"@

    Write-Host "[同步] 正在 Firefly 端展开并应用文件"
    Invoke-CheckedProcess -FilePath "ssh.exe" -ArgumentList @(
        "-i", $KeyPath,
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        $Remote,
        $remoteCommand
    )

    Write-Host "[同步] 完成"
}
finally {
    if (Test-Path $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
