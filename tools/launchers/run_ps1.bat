@echo off
setlocal EnableExtensions

if not defined VCR_PS_SCRIPT (
  echo VCR_PS_SCRIPT is not defined.
  exit /b 2
)

if not exist "%VCR_PS_SCRIPT%" (
  echo Missing PowerShell script: "%VCR_PS_SCRIPT%"
  exit /b 2
)

set "PS7_EXE="
if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PS7_EXE=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not defined PS7_EXE (
  where.exe pwsh.exe >nul 2>nul
  if not errorlevel 1 set "PS7_EXE=pwsh.exe"
)

if defined PS7_EXE (
  "%PS7_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%VCR_PS_SCRIPT%" %*
  exit /b %ERRORLEVEL%
)

where.exe powershell.exe >nul 2>nul
if errorlevel 1 (
  echo PowerShell was not found. Windows PowerShell 5.1 or PowerShell 7 is required.
  exit /b 1
)

set "UTF8_RUNNER=%~dp0..\invoke_utf8_ps1.ps1"
if not exist "%UTF8_RUNNER%" (
  echo Missing UTF-8 PowerShell runner: "%UTF8_RUNNER%"
  exit /b 2
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%UTF8_RUNNER%" "%VCR_PS_SCRIPT%" %*
exit /b %ERRORLEVEL%
