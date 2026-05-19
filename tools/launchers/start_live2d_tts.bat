@echo off
setlocal

where pwsh >nul 2>nul
if errorlevel 1 (
    echo [ERROR] pwsh.exe was not found. Please install PowerShell 7+.
    exit /b 1
)

pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\live2d_tts_server.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%VCR_NO_PAUSE%"=="1" (
    echo.
    if "%EXIT_CODE%"=="0" (
        echo [OK] Live2D TTS control service command finished.
    ) else (
        echo [ERROR] Live2D TTS control service failed with exit code %EXIT_CODE%.
    )
    pause
)
exit /b %EXIT_CODE%
