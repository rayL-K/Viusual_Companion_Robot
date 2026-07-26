[CmdletBinding()]
param(
    [string]$OutputRoot,
    [string]$ReleaseId
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Repository = (Resolve-Path (Join-Path $Root "..")).Path
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $Repository "output"
}
if (-not $ReleaseId) {
    $Revision = (& git -C $Repository rev-parse --short=7 HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $Revision) {
        throw "Unable to resolve the current Git revision."
    }
    $ReleaseId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd"), $Revision
}
if ($ReleaseId -notmatch '^[0-9]{8}-[0-9a-f]{7,40}$') {
    throw "ReleaseId must use yyyyMMdd-<git-sha>."
}

$PackageName = "anima-board-deploy-$ReleaseId"
$PackageRoot = Join-Path $OutputRoot $PackageName
if (Test-Path -LiteralPath $PackageRoot) {
    throw "Refusing to overwrite an existing package: $PackageRoot"
}

$BundleRoot = Join-Path $PackageRoot "bundle"
$ControlRoot = Join-Path $BundleRoot "control"
$SourceRoot = Join-Path $BundleRoot "source"
$null = New-Item -ItemType Directory -Path @(
    (Join-Path $ControlRoot "deploy\systemd"),
    (Join-Path $ControlRoot "scripts"),
    (Join-Path $SourceRoot "backend"),
    (Join-Path $SourceRoot "config"),
    (Join-Path $SourceRoot "web")
) -Force

function Copy-RequiredFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Required release input is missing: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $Destination
}

Copy-RequiredFile (Join-Path $Root "deploy\anima.env.example") (Join-Path $ControlRoot "deploy")
Copy-RequiredFile (Join-Path $Root "deploy\anima-candidate.env.example") (Join-Path $ControlRoot "deploy")
Copy-RequiredFile (Join-Path $Root "deploy\install-control-plane.sh") (Join-Path $ControlRoot "deploy")
Get-ChildItem -LiteralPath (Join-Path $Root "deploy\systemd") -Filter "anima*.service" -File |
    Copy-Item -Destination (Join-Path $ControlRoot "deploy\systemd")
Copy-RequiredFile (Join-Path $Root "scripts\start-elf2.sh") (Join-Path $ControlRoot "scripts")
Copy-RequiredFile (Join-Path $Root "backend\pyproject.toml") (Join-Path $SourceRoot "backend")
Copy-RequiredFile (Join-Path $Root "config\persona.md") (Join-Path $SourceRoot "config")

$BackendSource = Join-Path $Root "backend\src"
$BackendTarget = Join-Path $SourceRoot "backend\src"
$null = New-Item -ItemType Directory -Path $BackendTarget
Get-ChildItem -LiteralPath $BackendSource -Recurse -File |
    Where-Object {
        $_.FullName -notmatch '[\\/](?:__pycache__|[^\\/]+\.egg-info)[\\/]' -and
        $_.Extension -ne ".pyc"
    } |
    ForEach-Object {
        $Relative = [IO.Path]::GetRelativePath($BackendSource, $_.FullName)
        $Destination = Join-Path $BackendTarget $Relative
        $null = New-Item -ItemType Directory -Path (Split-Path $Destination) -Force
        Copy-Item -LiteralPath $_.FullName -Destination $Destination
    }

$WebDist = Join-Path $Root "web\dist"
if (-not (Test-Path -LiteralPath (Join-Path $WebDist "index.html") -PathType Leaf)) {
    throw "Web production build is missing. Run npm run build first."
}
Copy-Item -LiteralPath $WebDist -Destination (Join-Path $SourceRoot "web") -Recurse

$FullRevision = (& git -C $Repository rev-parse HEAD).Trim()
$Files = Get-ChildItem -LiteralPath $BundleRoot -Recurse -File |
    Sort-Object FullName |
    ForEach-Object {
        [ordered]@{
            path = [IO.Path]::GetRelativePath($BundleRoot, $_.FullName).Replace("\", "/")
            bytes = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
$Manifest = [ordered]@{
    product = "Anima v0.0.1"
    releaseId = $ReleaseId
    gitCommit = $FullRevision
    generatedAtUtc = [DateTime]::UtcNow.ToString("o")
    files = @($Files)
}
$ManifestPath = Join-Path $PackageRoot "manifest.json"
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ManifestPath -Encoding utf8NoBOM

$ArchivePath = Join-Path $PackageRoot "$PackageName.tar.gz"
& tar -C $PackageRoot -czf $ArchivePath bundle manifest.json
if ($LASTEXITCODE -ne 0) {
    throw "tar failed with exit code $LASTEXITCODE."
}
$ArchiveHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
"$ArchiveHash  $PackageName.tar.gz" |
    Set-Content -LiteralPath (Join-Path $PackageRoot "$PackageName.sha256") -Encoding ascii

[ordered]@{
    releaseId = $ReleaseId
    packageRoot = $PackageRoot
    archive = $ArchivePath
    sha256 = $ArchiveHash
    fileCount = $Files.Count
} | ConvertTo-Json
