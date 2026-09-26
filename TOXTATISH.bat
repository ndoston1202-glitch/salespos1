@echo off
chcp 65001 >nul
title EproPos - to'xtatish
cd /d "%~dp0"

if not exist "epropos.pid" goto notrunning
set /p PID=<"epropos.pid"
taskkill /PID %PID% /T /F >nul 2>&1
del "epropos.pid" >nul 2>&1
echo EproPos serveri to'xtatildi.
echo Telefon va planshetlar ham endi ulana olmaydi.
goto end

:notrunning
echo EproPos serveri ishlamayapti.

:end
pause
