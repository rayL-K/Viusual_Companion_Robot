param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScriptPath,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArguments
)

$ErrorActionPreference = "Stop"
$resolvedPath = (Resolve-Path -LiteralPath $ScriptPath).Path
$scriptDirectory = Split-Path -Parent $resolvedPath
$scriptName = [IO.Path]::GetFileNameWithoutExtension($resolvedPath)
$temporaryPath = Join-Path $scriptDirectory (".{0}.ps51.{1}.ps1" -f $scriptName, [Guid]::NewGuid().ToString("N"))
$utf8WithBom = New-Object Text.UTF8Encoding($true)

try {
    $content = [IO.File]::ReadAllText($resolvedPath, [Text.Encoding]::UTF8)
    [IO.File]::WriteAllText($temporaryPath, $content, $utf8WithBom)
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $temporaryPath @RemainingArguments
    exit $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
}
