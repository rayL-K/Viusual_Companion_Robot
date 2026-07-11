[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$BashCandidates = @(
    "C:\Program Files\Git\bin\bash.exe",
    "C:\Program Files\Git\usr\bin\bash.exe"
)
$Bash = $BashCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($Bash) {
    $DeployScript = Join-Path $Root "scripts\start-elf2.sh"
    & $Bash -n $DeployScript
    if ($LASTEXITCODE -ne 0) { throw "ELF2 activation script syntax failed." }
    $GuardOutput = (& $Bash $DeployScript start 2>&1) -join "`n"
    if ($LASTEXITCODE -eq 0 -or $GuardOutput -notmatch "当前禁止部署") {
        throw "V2 board deployment guard is not enforced."
    }
}

Push-Location (Join-Path $Root "backend")
try {
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
    python scripts/benchmark_memory.py --output ..\artifacts\memory-benchmark.json
    if ($LASTEXITCODE -ne 0) { throw "Memory benchmark failed." }
}
finally {
    Pop-Location
}

Push-Location (Join-Path $Root "web")
try {
    npm run check
    if ($LASTEXITCODE -ne 0) { throw "Web checks failed." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Web build failed." }
}
finally {
    Pop-Location
}

Write-Host "VeyraSoul V2 checks passed."
