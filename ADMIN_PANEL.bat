@echo off
chcp 65001 >nul
title EproPos Admin
cd /d "%~dp0"
rem Sotuvchi paneli: mijozlar, obuna to'lovlari va faollashtirish kodlari (faqat shu kompyuterda)
where pythonw >nul 2>nul
if errorlevel 1 (
    start "" python "%~dp0admin\admin.py"
) else (
    start "" pythonw "%~dp0admin\admin.py"
)
