@echo off
setlocal EnableExtensions
set "VCR_PS_SCRIPT=%~dp0..\firefly_vnc.ps1"
call "%~dp0run_ps1.bat" -Mode Start %*
exit /b %ERRORLEVEL%
