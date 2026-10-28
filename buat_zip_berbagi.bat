@echo off
title Pembuat ZIP Siap Pakai - AutoDrive Ekin PPUK
cd /d "%~dp0"

echo ======================================================
echo    MEMBUAT PAKET ZIP BERBAGI - AUTODRIVE EKIN PPUK
echo ======================================================
echo.

python -c "import zipfile, os; files = ['main.py', 'drive_api.py', 'watcher.py', 'config_manager.py', 'image_processor.py', 'updater.py', 'version.json', 'single_instance.py', 'requirements.txt', 'install_otomatis.bat', 'run_app.bat', 'README.md', 'credentials.json']; zipf = zipfile.ZipFile('AutoDrive_Siap_Pakai.zip', 'w', zipfile.ZIP_DEFLATED); [zipf.write(f, os.path.join('AutoDrive', f)) for f in files if os.path.exists(f)]; [zipf.write(os.path.join('assets', af), os.path.join('AutoDrive', 'assets', af)) for af in os.listdir('assets') if os.path.isfile(os.path.join('assets', af))]; zipf.close(); print('Selesai! Ukuran file:', os.path.getsize('AutoDrive_Siap_Pakai.zip'), 'bytes')"

echo.
echo ======================================================
echo SELESAI!
echo File 'AutoDrive_Siap_Pakai.zip' siap dikirim ke rekan kerja.
echo (File credentials.json sudah otomatis dimasukkan ke dalamnya,
echo  dan token.json pribadi Anda aman TIDAK ikut dimasukkan).
echo ======================================================
pause
