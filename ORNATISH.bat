@echo off
chcp 65001 >nul
title EproPos - o'rnatish
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python topilmadi!
    echo https://www.python.org/downloads/ dan o'rnating va "Add Python to PATH" ni belgilang.
    pause
    exit /b 1
)

echo Ish stoli va Pusk menyusiga "EproPos" yorlig'i qo'shilmoqda...
python "%~dp0desktop.py" --install
if errorlevel 1 (
    pause
    exit /b 1
)

netsh advfirewall firewall show rule name="EproPos" >nul 2>&1
if errorlevel 1 call "%~dp0TARMOQQA_RUXSAT.bat"

echo.
echo Endi EproPos'ni ish stolidagi "EproPos" ikonkasi orqali oching.
echo.
pause
