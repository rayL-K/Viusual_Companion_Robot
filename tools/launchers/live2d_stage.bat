@echo off
setlocal EnableExtensions

set "PS_SCRIPT=%~dp0..\live2d_stage_menu.ps1"
set "PS_EXE="

if exist "%ProgramFiles%\PowerShell\7\pwsh.exe" set "PS_EXE=%ProgramFiles%\PowerShell\7\pwsh.exe"

if not defined PS_EXE (
  where.exe pwsh.exe >nul 2>nul
  if not errorlevel 1 set "PS_EXE=pwsh.exe"
)

if not defined PS_EXE (
  where.exe powershell.exe >nul 2>nul
  if not errorlevel 1 set "PS_EXE=powershell.exe"
)

if not defined PS_EXE (
  echo PowerShell was not found.
  echo This launcher requires PowerShell 5.1 or PowerShell 7+.
  echo.
  pause
  exit /b 1
)

if not exist "%PS_SCRIPT%" (
  echo Missing script:
  echo %PS_SCRIPT%
  echo.
  pause
  exit /b 1
)

"%PS_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Script exited with code %EXIT_CODE%.
  echo.
  pause
)

exit /b %EXIT_CODE%
