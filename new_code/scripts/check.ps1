[CmdletBinding()]
param(
    [switch]$WithE2E
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DeployScript = Join-Path $Root "scripts\start-elf2.sh"
$DeployText = Get-Content -LiteralPath $DeployScript -Raw -Encoding UTF8
$ControlInstaller = Join-Path $Root "deploy\install-control-plane.sh"
$ControlInstallerText = Get-Content -LiteralPath $ControlInstaller -Raw -Encoding UTF8
$SystemdRoot = Join-Path $Root "deploy\systemd"

$PythonCandidates = @()
foreach ($CommandName in @("python", "python3")) {
    $Command = Get-Command $CommandName -ErrorAction SilentlyContinue |
        Where-Object CommandType -eq "Application" |
        Select-Object -First 1
    if ($Command) { $PythonCandidates += $Command.Source }
}
if ($env:LOCALAPPDATA) {
    $PythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    $PythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    $PythonCandidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"
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

$BashCandidates = @(
    "C:\Program Files\Git\bin\bash.exe",
    "C:\Program Files\Git\usr\bin\bash.exe"
)
$Bash = $BashCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if ($Bash) {
    & $Bash -n $DeployScript
    if ($LASTEXITCODE -ne 0) { throw "Anima deployment script syntax failed." }

    $Plan = (& $Bash $DeployScript plan 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "Anima deployment plan check failed." }
    Assert-Match -Text $Plan -Pattern 'sequence=stage -> health -> activate; rollback uses previous-release' -Message "Deployment plan does not expose the safe release sequence."
    Assert-Match -Text $Plan -Pattern 'staging=/home/wenkang/anima/candidate -> 127\.0\.0\.1:8876' -Message "Candidate must use its isolated loopback port."
    Assert-Match -Text $Plan -Pattern 'active=/home/wenkang/anima/current -> 127\.0\.0\.1:8875' -Message "Active service must use its stable loopback port."
    Assert-Match -Text $Plan -Pattern 'runtime=/home/wenkang/anima/\.venv' -Message "Deployment must expose the shared ELF2 runtime."
    Assert-Match -Text $Plan -Pattern 'data=/var/lib/anima' -Message "Deployment must expose the persistent data root."
    Assert-Match -Text $Plan -Pattern 'control=/opt/anima-control' -Message "Deployment must expose the root-owned control bundle."
    Assert-Match -Text $Plan -Pattern 'entrypoint=/usr/local/sbin/anima-deploy' -Message "Deployment must expose the fixed root-owned launcher."
    Assert-Match -Text $Plan -Pattern 'remote_config_tunnel=anima\.veyralux\.org -> http://127\.0\.0\.1:8875' -Message "Deployment must preserve the remote-config Tunnel ingress."
}

# 发布安全门：候选实例先健康，再切换指针；旧服务不在管理范围内。
Assert-Match -Text $DeployText -Pattern '(?s)deploy\).*?stage_release\s+health_candidate\s+activate_candidate' -Message "Deploy action must preserve stage -> health -> activate ordering."
Assert-Match -Text $DeployText -Pattern '(?s)activate_candidate\(\).*?HEALTHY_RECORD.*?health_ready.*?systemctl stop "\$\{CANDIDATE_UNIT\}".*?atomic_symlink' -Message "Activation must re-check the healthy candidate before atomic switching."
Assert-Match -Text $DeployText -Pattern 'restore_after_failed_activation' -Message "Activation failure must have an automatic restore path."
Assert-Match -Text $DeployText -Pattern 'assert_release_path' -Message "Release and rollback paths must be confined to /home/wenkang/anima/releases."
Assert-Match -Text $DeployText -Pattern 'verify_shared_runtime' -Message "Deployment must validate the shared ELF2 runtime."
Assert-Match -Text $DeployText -Pattern 'verify_runtime_imports' -Message "Deployment must import-check the shared ELF2 runtime before candidate startup."
Assert-Match -Text $DeployText -Pattern 'websockets\.exceptions' -Message "Deployment must detect an incomplete websockets installation."
Assert-Match -Text $DeployText -Pattern '"websockets-sansio" not in WS_PROTOCOLS' -Message "Deployment must require Uvicorn SansIO WebSocket support."
Assert-Match -Text $DeployText -Pattern 'verify_model_assets' -Message "Deployment must validate service-readable model assets."
Assert-Match -Text $DeployText -Pattern 'resolve_release_link' -Message "Deployment must distinguish an absent release pointer from a canonical non-existent path."
Assert-NoMatch -Text $DeployText -Pattern 'readlink -f "\$\{(?:CURRENT_LINK|CANDIDATE_LINK)\}"' -Message "Release pointers must always pass through resolve_release_link."
Assert-Match -Text $DeployText -Pattern 'verify_control_plane' -Message "Every privileged action must validate the root-owned control plane."
Assert-Match -Text $DeployText -Pattern 'SOURCE_ROOT="/home/wenkang/anima/source"' -Message "The deployer must use the fixed non-privileged source input."
Assert-Match -Text $DeployText -Pattern 'CONTROL_ROOT="/opt/anima-control"' -Message "The deployer must use the fixed root-owned control bundle."
Assert-Match -Text $DeployText -Pattern 'LAUNCHER_PATH="/usr/local/sbin/anima-deploy"' -Message "The deployer must require the fixed launcher."
Assert-NoMatch -Text $DeployText -Pattern 'cp -a "\$\{CONTROL_ROOT\}/(scripts|deploy)' -Message "Runtime releases must never carry or install the control plane."
Assert-Match -Text $DeployText -Pattern 'ANIMA_HOST\|ANIMA_PORT\|ANIMA_WEB_DIST\|ANIMA_DATA_ROOT\|ANIMA_MEMORY_PATH\|ANIMA_PERSONA_PATH\|ANIMA_ADMISSION_REQUIRED\|ANIMA_ALLOWED_ORIGINS\|PYTHONPATH' -Message "Runtime config must reject every deployment-reserved environment key."
Assert-NoMatch -Text $DeployText -Pattern 'exec sudo|sudo --preserve-env' -Message "A writable source script must never self-elevate."
Assert-NoMatch -Text $DeployText -Pattern 'cp -a .*\.venv|backend/\.venv' -Message "A release must not copy or reference a per-release venv."
Assert-NoMatch -Text $DeployText -Pattern 'ALLOW_V2_BOARD_ACTIVATION|visual-companion|robot\.veyralux\.org|/etc/cloudflared/token(?:\s|"|$)' -Message "Deployment script still contains an obsolete activation lock, legacy service control, or shared token path."

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
    Assert-NoMatch -Text $UnitText -Pattern 'veyrasoul-v2|visual-companion|/etc/cloudflared/token(?:\s|$)' -Message "$UnitName contains a legacy unit or shared tunnel token."
}

$ActiveUnit = Get-Content -LiteralPath (Join-Path $SystemdRoot "anima.service") -Raw -Encoding UTF8
$CandidateUnit = Get-Content -LiteralPath (Join-Path $SystemdRoot "anima-candidate.service") -Raw -Encoding UTF8
Assert-Match -Text $ActiveUnit -Pattern 'ExecStart=/usr/bin/env .*ANIMA_HOST=127\.0\.0\.1 .*ANIMA_PORT=8875 .*ANIMA_WEB_DIST=/opt/anima/current/web/dist .*ANIMA_DATA_ROOT=/var/lib/anima .*ANIMA_MEMORY_PATH=/var/lib/anima/memory/anima\.db .*ANIMA_PERSONA_PATH=/opt/anima/current/config/persona\.md .*ANIMA_ADMISSION_REQUIRED=true .*ANIMA_ALLOWED_ORIGINS=https://anima\.veyralux\.org .*PYTHONPATH=/opt/anima/current/backend/src /opt/anima/runtime/\.venv/bin/python' -Message "Active ExecStart must force every reserved path and public admission policy after EnvironmentFile loading."
Assert-Match -Text $CandidateUnit -Pattern 'ExecStart=/usr/bin/env .*ANIMA_HOST=127\.0\.0\.1 .*ANIMA_PORT=8876 .*ANIMA_WEB_DIST=/opt/anima/candidate/web/dist .*ANIMA_DATA_ROOT=/var/lib/anima-candidate .*ANIMA_MEMORY_PATH=/var/lib/anima-candidate/memory/anima\.db .*ANIMA_PERSONA_PATH=/opt/anima/candidate/config/persona\.md .*ANIMA_LLM_API_KEY=candidate .*ANIMA_ADMISSION_REQUIRED=false .*ANIMA_TURNSTILE_SECRET= .*ANIMA_TURNSTILE_SITE_KEY= .*PYTHONPATH=/opt/anima/candidate/backend/src /opt/anima/runtime/\.venv/bin/python' -Message "Candidate must force independent data, loopback-only no-admission health mode, and no production credentials."
Assert-NoMatch -Text $ActiveUnit -Pattern 'current/backend/\.venv' -Message "Active unit must not require a per-release venv."
Assert-NoMatch -Text $CandidateUnit -Pattern 'candidate/backend/\.venv' -Message "Candidate unit must not require a per-release venv."
Assert-Match -Text $ActiveUnit -Pattern 'User=anima-gateway' -Message "Active Gateway must use its dedicated service user."
Assert-Match -Text $CandidateUnit -Pattern 'User=anima-candidate' -Message "Candidate Gateway must use its own dedicated service user."
Assert-Match -Text $ActiveUnit -Pattern 'BindReadOnlyPaths=/home/wenkang/anima/current:/opt/anima/current' -Message "Active release must be mounted read-only into the service sandbox."
Assert-Match -Text $CandidateUnit -Pattern 'BindReadOnlyPaths=/home/wenkang/anima/candidate:/opt/anima/candidate' -Message "Candidate release must be mounted read-only into its sandbox."
Assert-Match -Text $ActiveUnit -Pattern 'BindReadOnlyPaths=/home/wenkang/anima/models:/opt/anima/models' -Message "Active model assets must be a read-only bind mount."
Assert-Match -Text $CandidateUnit -Pattern 'BindReadOnlyPaths=/home/wenkang/anima/models:/opt/anima/models' -Message "Candidate model assets must be a read-only bind mount."
Assert-Match -Text $CandidateUnit -Pattern 'InaccessiblePaths=/var/lib/anima /var/cache/anima /run/anima' -Message "Candidate must not see production state."
Assert-Match -Text $ActiveUnit -Pattern 'ANIMA_DATA_ROOT=/var/lib/anima' -Message "Active data must live outside the read-only home tree."
Assert-Match -Text $CandidateUnit -Pattern 'ANIMA_DATA_ROOT=/var/lib/anima-candidate' -Message "Candidate data must be isolated from production."

$TunnelUnit = Get-Content -LiteralPath (Join-Path $SystemdRoot "anima-cloudflared.service") -Raw -Encoding UTF8
Assert-Match -Text $TunnelUnit -Pattern 'LoadCredential=anima-token:/etc/anima/tunnel-token' -Message "Tunnel token must be passed through a systemd credential."
Assert-Match -Text $TunnelUnit -Pattern 'run --token-file /run/credentials/anima-cloudflared\.service/anima-token' -Message "Tunnel must read the credential from the systemd 249-compatible private credential directory."
Assert-NoMatch -Text $TunnelUnit -Pattern '(?:^|\s)--url(?:\s|=)' -Message "Remote-config Tunnel must not override ingress with --url."
Assert-Match -Text $DeployText -Pattern 'tunnel_ready' -Message "Deployment must wait for a stable Tunnel process instead of accepting a transient active state."
Assert-Match -Text $DeployText -Pattern 'main_pid.*stable_pid' -Message "Tunnel stability checks must not span different cloudflared processes."
Assert-Match -Text $DeployText -Pattern '\[\[ -s "\$\{path\}" \]\]' -Message "Private credential files must not be empty."

Assert-Match -Text $ControlInstallerText -Pattern 'install -m 700 -o root -g root.*start-elf2\.sh' -Message "The one-time installer must create a root-only deployer."
Assert-Match -Text $ControlInstallerText -Pattern '"/etc/systemd/system/\$\{unit\}"' -Message "Only the explicit one-time installer may write systemd units."
Assert-Match -Text $ControlInstallerText -Pattern 'systemctl daemon-reload' -Message "The one-time installer must reload systemd after installing trusted units."
Assert-Match -Text $ControlInstallerText -Pattern 'verify_runtime_imports' -Message "The one-time installer must reject an incomplete shared runtime."
Assert-Match -Text $ControlInstallerText -Pattern 'runuser -u anima-candidate -- "\$\{RUNTIME_ROOT\}/bin/python" -I' -Message "Runtime imports must be verified with the isolated candidate UID."
Assert-Match -Text $ControlInstallerText -Pattern 'chmod 0755' -Message "The installer must make model directories traversable by isolated service users."
Assert-Match -Text $ControlInstallerText -Pattern 'chmod 0644' -Message "The installer must make model files readable by isolated service users."
Assert-Match -Text $DeployText -Pattern 'releaseDigest' -Message "Health acceptance must bind the running process to the release digest."
Assert-Match -Text $DeployText -Pattern 'payload\.get\("service"\) == "anima-gateway"' -Message "Health acceptance must require the Anima gateway identity."

$EnvTemplate = Get-Content -LiteralPath (Join-Path $Root "deploy\anima.env.example") -Raw -Encoding UTF8
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_LLM_API_KEY=\r?$' -Message "The environment template must leave the API key empty."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_ADMISSION_SECRET=\r?$' -Message "The environment template must leave the admission secret empty."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_TELEMETRY_HMAC_KEY=\r?$' -Message "The environment template must leave the telemetry HMAC key empty."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_TURNSTILE_SITE_KEY=\r?$' -Message "The environment template must leave the Turnstile site key empty."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_TURNSTILE_SECRET=\r?$' -Message "The environment template must leave the Turnstile secret empty."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_ADMISSION_TTL_SECONDS=86400\r?$' -Message "The environment template must use the recommended admission TTL."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_DEVICE_TTL_SECONDS=2592000\r?$' -Message "The environment template must use the 30-day device identity TTL."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_TOC_ENABLED=false\r?$' -Message "The ELF2 template must explicitly select non-ToC validation mode."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_REALTIME_ALLOW_ANONYMOUS=true\r?$' -Message "The current ELF2 validation template must explicitly enable anonymous realtime."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_AUTH_DATABASE=/var/lib/anima/auth\.sqlite3\r?$' -Message "The ToC auth database must live in the writable production state directory."
Assert-Match -Text $EnvTemplate -Pattern '(?m)^ANIMA_LOGIN_FERNET_KEY=\r?$' -Message "The environment template must leave the login-state encryption key empty."
Assert-NoMatch -Text $EnvTemplate -Pattern '(?i)sk-[A-Za-z0-9]|replace-me|password\s*=' -Message "The environment template contains a secret-like placeholder or credential."
Assert-NoMatch -Text $EnvTemplate -Pattern '(?m)^\s*(ANIMA_HOST|ANIMA_PORT|ANIMA_WEB_DIST|ANIMA_DATA_ROOT|ANIMA_MEMORY_PATH|ANIMA_PERSONA_PATH|ANIMA_ADMISSION_REQUIRED|ANIMA_ALLOWED_ORIGINS|PYTHONPATH)\s*=' -Message "The environment template must not define deployment-reserved keys."

$BenchmarkOutput = Join-Path (
    [System.IO.Path]::GetTempPath()
) ("anima-memory-benchmark-{0}-{1}.json" -f $PID, [guid]::NewGuid())
Push-Location (Join-Path $Root "backend")
try {
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." }
    & $Python scripts/benchmark_memory.py --output $BenchmarkOutput
    if ($LASTEXITCODE -ne 0) { throw "Memory benchmark failed." }
}
finally {
    Pop-Location
    Remove-Item -LiteralPath $BenchmarkOutput -Force -ErrorAction SilentlyContinue
}

Push-Location (Join-Path $Root "web")
try {
    npm run check
    if ($LASTEXITCODE -ne 0) { throw "Web checks failed." }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Web build failed." }
    if (-not (Test-Path -LiteralPath (Join-Path $PWD "dist\THIRD_PARTY_NOTICES.md"))) {
        throw "Third-party notices were not copied into the web distribution."
    }
    if ($WithE2E) {
        npm run e2e
        if ($LASTEXITCODE -ne 0) { throw "Local browser E2E failed." }
    }
}
finally {
    Pop-Location
}

Write-Host "Anima v0.0.1 checks passed."
