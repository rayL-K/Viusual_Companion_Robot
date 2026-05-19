@echo off
setlocal

set "PWSH_EXE=pwsh"
where pwsh >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pwsh.exe was not found. Please install PowerShell 7+.
    exit /b 1
)

pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\test_live2d_stage.ps1" -Open %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%VCR_NO_PAUSE%"=="1" (
    echo.
    if "%EXIT_CODE%"=="0" (
        echo [OK] Live2D Stage should now be available at http://127.0.0.1:5174/
    ) else (
        echo [ERROR] Live2D Stage failed with exit code %EXIT_CODE%.
    )
    pause
)
exit /b %EXIT_CODE%
