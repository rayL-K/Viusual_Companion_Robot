@echo off
setlocal
where pwsh.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pwsh.exe was not found. Please install PowerShell 7.1 or later.
    exit /b 1
)
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\test_mouth_visual.ps1" %*
exit /b %ERRORLEVEL%
