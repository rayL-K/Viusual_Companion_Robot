@echo off
setlocal

set "PWSH_EXE=pwsh"
where pwsh >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pwsh.exe was not found. Please install PowerShell 7+.
    exit /b 1
)

pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\generate_llm_control.ps1" %*
exit /b %ERRORLEVEL%
