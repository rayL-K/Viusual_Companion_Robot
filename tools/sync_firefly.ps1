[CmdletBinding()]
param(
    [string]$RemoteHost = "elf2-desktop.local",
    [string]$RemoteUser = "wenkang",
    [string]$RemoteRoot = "/home/wenkang/embedded_competition",
    [string]$KeyPath = "",
    [switch]$NoDelete,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Remote = "${RemoteUser}@${RemoteHost}"
$Archive = Join-Path ([IO.Path]::GetTempPath()) ("visual-companion-" + [Guid]::NewGuid().ToString("N") + ".tar.gz")
$RemoteArchive = "/tmp/visual-companion-deploy.tar.gz"
$RemoteStage = "/tmp/visual-companion-deploy-stage"
$SshOptions = @("-o", "StrictHostKeyChecking=accept-new")

if ($KeyPath) {
    $ResolvedKey = (Resolve-Path -LiteralPath $KeyPath -ErrorAction Stop).Path
    $SshOptions += @("-i", $ResolvedKey, "-o", "IdentitiesOnly=yes")
}

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath 执行失败，退出码：$LASTEXITCODE"
    }
}

try {
    Write-Host "[同步] 只打包当前 Git 提交，不传输密钥、缓存或本地输出"
    Invoke-CheckedProcess -FilePath "git.exe" -ArgumentList @(
        "-C", $ProjectRoot, "archive", "--format=tar.gz", "--output=$Archive", "HEAD"
    )

    Write-Host "[同步] 上传到 ${Remote}"
    Invoke-CheckedProcess -FilePath "scp.exe" -ArgumentList @(
        $SshOptions + @($Archive, "$Remote`:$RemoteArchive")
    )

    $DeleteOption = if ($NoDelete) { "" } else { "--delete" }
    $RemoteCommand = @"
set -Eeuo pipefail
dest='$RemoteRoot'
archive='$RemoteArchive'
stage='$RemoteStage'
case "`$dest" in
  /home/wenkang/embedded_competition) ;;
  *) echo "[同步:错误] 目标目录不安全：`$dest" >&2; exit 66 ;;
esac
rm -rf -- "`$stage"
mkdir -p -- "`$stage" "`$dest"
tar -xzf "`$archive" -C "`$stage"
rsync -a $DeleteOption \
  --exclude='.venv/' \
  --exclude='main/models/' \
  --exclude='main/data/' \
  --exclude='main/config/board.env' \
  --exclude='main/config/local.env' \
  --exclude='output/' \
  "`$stage/" "`$dest/"
rm -rf -- "`$stage"
rm -f -- "`$archive"
chmod +x "`$dest/tools/board/"*.sh
echo "[同步] ELF2 目录已更新：`$dest"
"@

    Invoke-CheckedProcess -FilePath "ssh.exe" -ArgumentList @(
        $SshOptions + @($Remote, $RemoteCommand)
    )

    if ($Restart) {
        Write-Host "[同步] 刷新服务并执行强校验"
        Invoke-CheckedProcess -FilePath "ssh.exe" -ArgumentList @(
            @("-t") + $SshOptions + @(
                $Remote,
                "cd '$RemoteRoot' && sudo tools/board/start_all.sh restart && tools/board/verify_deployment.sh"
            )
        )
    }
}
finally {
    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive -Force
    }
}
