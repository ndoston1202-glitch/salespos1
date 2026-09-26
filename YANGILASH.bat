@echo off
chcp 65001 >nul
title EproPos - yangilash

rem Yangilanish shu faylning o'zini ham almashtirishi mumkin - shuning uchun nusxadan ishlaymiz
if not "%~1"=="--nusxa" (
    copy /y "%~f0" "%TEMP%\epropos_yangilash.bat" >nul
    call "%TEMP%\epropos_yangilash.bat" --nusxa "%~dp0"
    exit /b
)
set "APPDIR=%~2"
set "DEST=%APPDIR:~0,-1%"
cd /d "%APPDIR%"
set GIT_TERMINAL_PROMPT=0
set "ZIPURL=https://github.com/ndoston1202-glitch/salespos1/archive/refs/heads/main.zip"

echo GitHub dan yangi versiya olinmoqda...

rem Papka git clone orqali olingan bo'lsa - git pull, aks holda (ZIP yuklangan) - yangi ZIP yuklab olinadi
where git >nul 2>nul
if errorlevel 1 goto zip
if not exist "%APPDIR%.git" goto zip
git pull --ff-only
if errorlevel 1 goto failed
goto restart

:zip
set "TMPZIP=%TEMP%\epropos_yangi.zip"
set "TMPDIR=%TEMP%\epropos_yangi"
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri '%ZIPURL%' -OutFile '%TMPZIP%'; Expand-Archive -Force -Path '%TMPZIP%' -DestinationPath '%TMPDIR%'"
if errorlevel 1 goto failed
if not exist "%TMPDIR%\salespos1-main\server.py" goto failed

rem Server to'xtatiladi, keyin fayllar almashtiriladi (baza, rasmlar va sozlamalar tegilmaydi)
call :stopserver
robocopy "%TMPDIR%\salespos1-main" "%DEST%" /E /XF epropos.db epropos.db-* epropos.pid epropos.log /XD uploads tools .git /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto failed
rmdir /s /q "%TMPDIR%" >nul 2>&1
del "%TMPZIP%" >nul 2>&1

:restart
rem Yangi kod kuchga kirishi uchun orqa fondagi serverni qayta ishga tushiramiz
call :stopserver
echo.
echo Tayyor! EproPos yangi versiyada ochilmoqda...
call "%APPDIR%ISHGA_TUSHIR.bat"
timeout /t 3 >nul
exit /b 0

:stopserver
if not exist "%APPDIR%epropos.pid" exit /b 0
set /p PID=<"%APPDIR%epropos.pid"
taskkill /PID %PID% /T /F >nul 2>&1
del "%APPDIR%epropos.pid" >nul 2>&1
timeout /t 1 >nul
exit /b 0

:failed
echo.
echo Yangilab bo'lmadi. Internetni tekshiring.
pause
