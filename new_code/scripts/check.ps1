[CmdletBinding()]
param(
    [switch]$WithE2E
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function Assert-Match {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if ($Text -notmatch $Pattern) { throw $Message }
}

function Assert-NoMatch {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if ($Text -match $Pattern) { throw $Message }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Command,
        [Parameter(Mandatory = $true)][string]$Message
    )
    & $Command
    if ($LASTEXITCODE -ne 0) { throw $Message }
}

$PythonCandidates = @()
foreach ($CommandName in @("python", "python3")) {
    $Command = Get-Command $CommandName -ErrorAction SilentlyContinue |
        Where-Object CommandType -eq "Application" |
        Select-Object -First 1
    if ($Command) { $PythonCandidates += $Command.Source }
}
if ($env:LOCALAPPDATA) {
    foreach ($Version in @("Python312", "Python311", "Python310")) {
        $PythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\$Version\python.exe"
    }
}
$Python = $null
foreach ($Candidate in ($PythonCandidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $Candidate)) { continue }
    & $Candidate -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 13) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $Python = $Candidate
        break
    }
}
if (-not $Python) {
    throw "A working Python 3.10-3.12 interpreter is required; Windows Store aliases are not accepted."
}

# 新产品只保留通用 Linux/API-first 发布面；板端发布器仍可从 Git 历史恢复。
foreach ($LegacyPath in @(
    "scripts\start-elf2.sh",
    "scripts\package-board-release.ps1",
    "deploy\install-control-plane.sh",
    "docs\deployment-elf2.md"
)) {
    if (Test-Path -LiteralPath (Join-Path $Root $LegacyPath)) {
        throw "Legacy board-only artifact is not allowed in new_code: $LegacyPath"
    }
}

$PortablePreflight = Join-Path $Root "deploy\portable\portable-preflight.sh"
$Bash = @(
    "C:\Program Files\Git\bin\bash.exe",
    "C:\Program Files\Git\usr\bin\bash.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($Bash) {
    Invoke-Checked -Command { & $Bash -n $PortablePreflight } -Message "Portable server preflight syntax failed."
    $PreflightHelp = (& $Bash $PortablePreflight --help 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Portable server preflight help failed." }
    Assert-Match -Text $PreflightHelp -Pattern 'gateway（默认）' -Message "Portable preflight must expose the API-first gateway profile."
}

$SystemdRoot = Join-Path $Root "deploy\systemd"
$RequiredUnits = @(
    "anima.service",
    "anima-candidate.service",
    "anima-cloudflared.service"
)
foreach ($UnitName in $RequiredUnits) {
    $UnitPath = Join-Path $SystemdRoot $UnitName
    if (-not (Test-Path -LiteralPath $UnitPath)) { throw "Missing systemd unit: $UnitName" }
    $UnitText = Get-Content -LiteralPath $UnitPath -Raw -Encoding UTF8
    Assert-Match -Text $UnitText -Pattern 'NoNewPrivileges=true' -Message "$UnitName must enable NoNewPrivileges."
    Assert-Match -Text $UnitText -Pattern 'ProtectSystem=strict' -Message "$UnitName must use ProtectSystem=strict."
    Assert-NoMatch -Text $UnitText -Pattern '/home/wenkang|visual-companion|robot\.veyralux\.org' -Message "$UnitName contains a board or v1 dependency."
}

$ActiveUnit = Get-Content -LiteralPath (Join-Path $SystemdRoot "anima.service") -Raw -Encoding UTF8
$CandidateUnit = Get-Content -LiteralPath (Join-Path $SystemdRoot "anima-candidate.service") -Raw -Encoding UTF8
$TunnelUnit = Get-Content -LiteralPath (Join-Path $SystemdRoot "anima-cloudflared.service") -Raw -Encoding UTF8
Assert-Match -Text $ActiveUnit -Pattern 'User=anima-gateway' -Message "Active Gateway must use its dedicated service user."
Assert-Match -Text $ActiveUnit -Pattern 'ANIMA_HOST=127\.0\.0\.1 .*ANIMA_PORT=8875' -Message "Active Gateway must remain loopback-only on port 8875."
Assert-Match -Text $ActiveUnit -Pattern 'ANIMA_DATA_ROOT=/var/lib/anima' -Message "Active data must use the production state directory."
Assert-Match -Text $ActiveUnit -Pattern 'LoadCredential=anima-secret-env:/etc/anima/anima\.secret\.env' -Message "Active secrets must use a systemd credential."
Assert-Match -Text $ActiveUnit -Pattern 'EnvironmentFile=/run/credentials/anima\.service/anima-secret-env' -Message "Active service must read its private credential environment."
Assert-Match -Text $CandidateUnit -Pattern 'User=anima-candidate' -Message "Candidate Gateway must use an isolated service user."
Assert-Match -Text $CandidateUnit -Pattern 'ANIMA_HOST=127\.0\.0\.1 .*ANIMA_PORT=8876' -Message "Candidate Gateway must remain loopback-only on port 8876."
Assert-Match -Text $CandidateUnit -Pattern 'ANIMA_DATA_ROOT=/var/lib/anima-candidate' -Message "Candidate data must be isolated."
Assert-Match -Text $CandidateUnit -Pattern 'ANIMA_LLM_API_KEY=candidate .*ANIMA_AUDIO_API_KEY=candidate' -Message "Candidate must use fixed non-production API placeholders."
Assert-Match -Text $CandidateUnit -Pattern 'InaccessiblePaths=/var/lib/anima /var/cache/anima /run/anima' -Message "Candidate must not see production state."
Assert-Match -Text $TunnelUnit -Pattern 'LoadCredential=anima-token:/etc/anima/tunnel-token' -Message "Tunnel token must use a systemd credential."
Assert-Match -Text $TunnelUnit -Pattern 'run --token-file /run/credentials/anima-cloudflared\.service/anima-token' -Message "Tunnel must read the private credential path."
Assert-NoMatch -Text $TunnelUnit -Pattern '(?:^|\s)--url(?:\s|=)' -Message "Remote-config Tunnel must not override managed ingress."

$EnvTemplate = Get-Content -LiteralPath (Join-Path $Root "deploy\anima.env.example") -Raw -Encoding UTF8
foreach ($RequiredSetting in @(
    'ANIMA_TOC_ENABLED=true',
    'ANIMA_REALTIME_ALLOW_ANONYMOUS=false',
    'ANIMA_REALTIME_ALLOWED_ORIGINS=https://anima.veyralux.org',
    'ANIMA_AUTH_DATABASE=/var/lib/anima/auth.sqlite3',
    'ANIMA_ASR_PROVIDER=openai-compatible',
    'ANIMA_TTS_PROVIDER=openai-compatible',
    'ANIMA_TTS_STREAMING_ENABLED=false',
    'ANIMA_VISION_PROVIDER=disabled',
    'ANIMA_PCM_BYTES_PER_SECOND=32000',
    'ANIMA_PCM_BURST_BYTES=32000',
    'ANIMA_WEBSOCKET_SEND_TIMEOUT_SECONDS=5'
)) {
    Assert-Match -Text $EnvTemplate -Pattern "(?m)^$([regex]::Escape($RequiredSetting))`r?$" -Message "Missing safe production default: $RequiredSetting"
}
Assert-NoMatch -Text $EnvTemplate -Pattern '(?m)^ANIMA_(?:LLM_API_KEY|AUDIO_API_KEY|ADMISSION_SECRET|TELEMETRY_HMAC_KEY|TURNSTILE_SECRET|LOGIN_FERNET_KEY)=' -Message "The non-secret environment template contains a secret field."
Assert-NoMatch -Text $EnvTemplate -Pattern '(?i)sk-[A-Za-z0-9]|replace-me|password\s*=' -Message "The environment template contains credential-like text."

$SecretEnvTemplate = Get-Content -LiteralPath (Join-Path $Root "deploy\anima.secret.env.example") -Raw -Encoding UTF8
foreach ($SecretName in @(
    "ANIMA_LLM_API_KEY",
    "ANIMA_AUDIO_API_KEY",
    "ANIMA_ADMISSION_SECRET",
    "ANIMA_TELEMETRY_HMAC_KEY",
    "ANIMA_TURNSTILE_SECRET",
    "ANIMA_LOGIN_FERNET_KEY"
)) {
    Assert-Match -Text $SecretEnvTemplate -Pattern "(?m)^$SecretName=`r?$" -Message "$SecretName must be listed empty in the secret credential template."
}
Assert-NoMatch -Text $SecretEnvTemplate -Pattern '(?i)sk-[A-Za-z0-9]|replace-me|password\s*=' -Message "The secret credential template contains a credential-like value."

$CandidateEnv = Get-Content -LiteralPath (Join-Path $Root "deploy\anima-candidate.env.example") -Raw -Encoding UTF8
Assert-Match -Text $CandidateEnv -Pattern '(?m)^ANIMA_ASR_PROVIDER=openai-compatible\r?$' -Message "Candidate must follow the API-first provider topology."
Assert-Match -Text $CandidateEnv -Pattern '(?m)^ANIMA_TTS_PROVIDER=openai-compatible\r?$' -Message "Candidate must follow the API-first provider topology."
Assert-Match -Text $CandidateEnv -Pattern '(?m)^ANIMA_VISION_PROVIDER=disabled\r?$' -Message "Candidate must not require an unverified local VLM."

$BenchmarkOutput = Join-Path ([System.IO.Path]::GetTempPath()) ("anima-memory-benchmark-{0}-{1}.json" -f $PID, [guid]::NewGuid())
Push-Location (Join-Path $Root "backend")
try {
    Invoke-Checked -Command { & $Python -m pytest -q } -Message "Backend tests failed."
    Invoke-Checked -Command { & $Python scripts/benchmark_memory.py --output $BenchmarkOutput } -Message "Memory benchmark failed."
}
finally {
    Pop-Location
    Remove-Item -LiteralPath $BenchmarkOutput -Force -ErrorAction SilentlyContinue
}

Push-Location (Join-Path $Root "web")
try {
    Invoke-Checked -Command { npm run check } -Message "Web checks failed."
    Invoke-Checked -Command { npm run build } -Message "Web build failed."
    if (-not (Test-Path -LiteralPath (Join-Path $PWD "dist\THIRD_PARTY_NOTICES.md"))) {
        throw "Third-party notices were not copied into the web distribution."
    }
    if ($WithE2E) {
        Invoke-Checked -Command { npm run e2e } -Message "Local browser E2E failed."
    }
}
finally {
    Pop-Location
}

Push-Location (Join-Path $Root "brand-site")
try {
    Invoke-Checked -Command { npm run typecheck } -Message "Brand site typecheck failed."
    Invoke-Checked -Command { npm test } -Message "Brand site tests failed."
    Invoke-Checked -Command { npm run build } -Message "Brand site build failed."
    Invoke-Checked -Command { npm run qa:motion } -Message "Brand site motion contract failed."
}
finally {
    Pop-Location
}

Write-Host "Anima v0.0.1 API-first checks passed."
