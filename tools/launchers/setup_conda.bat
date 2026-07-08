@echo off
setlocal EnableExtensions
set "VCR_PS_SCRIPT=%~dp0..\setup_conda.ps1"
call "%~dp0run_ps1.bat" %*
exit /b %ERRORLEVEL%
