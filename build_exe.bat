@echo off
title Build Standalone EXE - AutoDrive Ekin PPUK
cd /d "%~dp0"

echo ======================================================
echo    BUILD STANDALONE EXE - AUTODRIVE EKIN PPUK
echo ======================================================
echo.

REM 1. Pasang PyInstaller jika belum ada
echo [1/3] Memeriksa PyInstaller...
python -m pip install pyinstaller

REM 2. Lakukan build menjadi file .exe portabel dengan ikon Perpusnas
REM Catatan Penting: Jangan gunakan --collect-all PIL karena PyInstaller sudah memiliki hook resmi.
echo.
echo [2/3] Mengompilasi aplikasi menjadi file EXE...
python -m PyInstaller -y --noconsole --onedir --name "AutoDrive" --icon="assets\app_icon.ico" --add-data="assets;assets" --collect-all customtkinter main.py

REM 3. Salin credentials.json, version.json, dan assets ke folder dist jika ada
echo.
echo [3/3] Menyalin file konfigurasi dan assets ke folder output...
if not exist dist\AutoDrive\assets (
    mkdir dist\AutoDrive\assets
)
xcopy /Y /E /I /Q assets dist\AutoDrive\assets
if exist credentials.json (
    copy /Y credentials.json dist\AutoDrive\credentials.json
)
if exist version.json (
    copy /Y version.json dist\AutoDrive\version.json
)

REM Pastikan token.json TIDAK ikut terbawa
if exist dist\AutoDrive\token.json (
    del /f /q dist\AutoDrive\token.json
)

echo.
echo ======================================================
echo BUILD SELESAI!
echo Folder aplikasi siap kirim ada di: dist\AutoDrive\
echo Rekan Anda cukup membuka dist\AutoDrive\AutoDrive.exe
echo ======================================================
pause
