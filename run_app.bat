@echo off
title AutoDrive Ekin PPUK
cd /d "%~dp0"
echo Memulai AutoDrive Ekin PPUK...

REM Cek apakah python di PATH atau gunakan path absolut
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python main.py
) else (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" main.py
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo Terjadi kendala saat menjalankan aplikasi.
    pause
)
