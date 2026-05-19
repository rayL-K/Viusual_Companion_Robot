@echo off
setlocal

set "PWSH_EXE=pwsh"
where pwsh >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pwsh.exe was not found. Please install PowerShell 7+.
    exit /b 1
)

pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\test_live2d_stage.ps1" %*
exit /b %ERRORLEVEL%
