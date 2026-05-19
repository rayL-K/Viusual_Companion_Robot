[CmdletBinding()]
param(
    [string]$RemoteHost = "192.168.5.83",
    [string]$RemoteUser = "firefly",
    [string]$RemoteRoot = "/home/firefly/wwk/Visual_Companion_Robot",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\id_ed25519_firefly",
    [string]$PythonCommand = "python3",
    [string]$PythonVersion = "3.8",
    [switch]$NoSync,
    [double]$DurationSec = 5,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = "Stop"

$Remote = "${RemoteUser}@${RemoteHost}"
$SyncScript = Join-Path $PSScriptRoot "sync_firefly.ps1"

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$FilePath 执行失败，退出码：$exitCode"
    }
}

if (-not $NoSync) {
    Write-Host "[运行] 执行前先同步项目到 Firefly"
    & $SyncScript -RemoteHost $RemoteHost -RemoteUser $RemoteUser -RemoteRoot $RemoteRoot -KeyPath $KeyPath
    if ($LASTEXITCODE -ne 0) {
        throw "同步失败"
    }
}

$mainArgs = if ($ScriptArgs.Count -gt 0) {
    ($ScriptArgs | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join " "
}
else {
    ""
}

$remoteCommand = @"
set -e
cd '$RemoteRoot/main'
export DISPLAY=:0
export XAUTHORITY=/home/firefly/.Xauthority

PY='$PythonCommand'
REQUIRED_PYTHON='$PythonVersion'

if ! command -v "`$PY" >/dev/null 2>&1; then
  echo "[运行:错误] 未找到 Python 命令：`$PY" >&2
  exit 67
fi

ACTUAL_PYTHON="`$(`$PY -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "`$ACTUAL_PYTHON" != "`$REQUIRED_PYTHON" ]; then
  echo "[运行:错误] Python 版本不一致：当前为 `$ACTUAL_PYTHON，要求为 `$REQUIRED_PYTHON。" >&2
  echo "[运行:错误] 请优先统一到 Firefly 当前运行目标 Python `$REQUIRED_PYTHON.x。" >&2
  exit 68
fi

if ! "`$PY" -c "import yaml" >/dev/null 2>&1; then
  echo "[运行] 正在通过 apt 安装 PyYAML 对应包 python3-yaml"
  sudo apt-get update
  sudo apt-get install -y python3-yaml
fi

echo "[运行] Python 版本："
"`$PY" --version
echo "[运行] 工作目录：`$(pwd)"
"`$PY" app.py $mainArgs
"@

Write-Host "[运行] 正在 Firefly 上执行：${Remote}:${RemoteRoot}/main"
Invoke-CheckedProcess -FilePath "ssh.exe" -ArgumentList @(
    "-t",
    "-i", $KeyPath,
    "-o", "IdentitiesOnly=yes",
    $Remote,
    $remoteCommand
)
