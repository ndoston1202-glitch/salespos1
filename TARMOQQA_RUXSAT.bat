@echo off
chcp 65001 >nul
title EproPos - tarmoqqa ruxsat
cd /d "%~dp0"

rem Administrator huquqi kerak - bo'lmasa o'zini qayta so'rab ishga tushiradi
net session >nul 2>&1
if errorlevel 1 (
    echo Administrator huquqi so'ralmoqda...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set PORT=8100
if not "%EPROPOS_PORT%"=="" set PORT=%EPROPOS_PORT%

echo [1/4] Python uchun qo'yilgan taqiqlar olib tashlanmoqda...
powershell -NoProfile -Command "Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like '*python*' } | Get-NetFirewallRule | Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' } | Remove-NetFirewallRule" >nul 2>&1

echo [2/4] %PORT%-port ochilmoqda...
netsh advfirewall firewall delete rule name="EproPos" >nul 2>&1
netsh advfirewall firewall add rule name="EproPos" dir=in action=allow protocol=TCP localport=%PORT% profile=any >nul

echo [3/4] Python dasturiga ruxsat berilmoqda...
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if defined PYEXE (
    netsh advfirewall firewall delete rule name="EproPos Python" >nul 2>&1
    netsh advfirewall firewall add rule name="EproPos Python" dir=in action=allow program="%PYEXE%" profile=any >nul
)

echo [4/4] Wi-Fi tarmog'i "Private" (Chastnaya) turiga o'tkazilmoqda...
powershell -NoProfile -Command "Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq 'Public' } | Set-NetConnectionProfile -NetworkCategory Private" >nul 2>&1

echo.
echo Tayyor! Endi EproPos'ni qayta ishga tushiring (qora oynani yopib, ISHGA_TUSHIR.bat).
echo Telefon/planshetda qora oynadagi "Telefon/planshetdan" manzilini oching.
echo.
pause
