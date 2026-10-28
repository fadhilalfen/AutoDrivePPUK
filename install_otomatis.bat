@echo off
title Installer Otomatis AutoDrive Ekin PPUK
cd /d "%~dp0"

echo ======================================================
echo       INSTALLER OTOMATIS - AUTODRIVE EKIN PPUK
echo ======================================================
echo.

REM 1. Periksa apakah Python sudah terpasang
echo [1/3] Memeriksa Python di komputer...
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Python belum terdeteksi. Memasang Python 3.12 via Windows Package Manager...
    winget install Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
    if %ERRORLEVEL% neq 0 (
        echo Gagal menginstal Python otomatis. Silakan pasang manual dari python.org.
        pause
        exit /b 1
    )
    echo Python berhasil dipasang!
) else (
    echo Python sudah terpasang.
)

REM 2. Pasang semua dependensi
echo.
echo [2/3] Memasang semua dependensi pustaka yang dibutuhkan...
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python -m pip install -r requirements.txt
) else (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m pip install -r requirements.txt
)

REM 3. Jalankan Aplikasi
echo.
echo [3/3] Instalasi selesai! Menjalankan aplikasi...
echo ======================================================
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    start python main.py
) else (
    start "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" main.py
)

exit
