[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

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
