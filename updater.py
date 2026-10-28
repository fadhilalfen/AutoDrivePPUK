"""
updater.py - Modul Auto-Updater untuk Aplikasi Desktop AutoDrive Report Manager
Memeriksa versi terbaru, mengunduh pembaruan di latar belakang,
dan mengeksekusi skrip penggantian file (in-place update) lalu me-restart aplikasi.
"""

import os
import sys
import json
import urllib.request
import zipfile
import subprocess
import tempfile
import threading
from packaging import version
from typing import Optional, Dict, Any, Callable

# Versi Aplikasi Saat Ini
APP_VERSION = "1.0.0"

# URL default tempat menaruh version.json (bisa diatur via config.json)
# Contoh format: GitHub Raw, hosting pribadi, atau Google Drive direct download
DEFAULT_UPDATE_CHECK_URL = "https://raw.githubusercontent.com/fadhilalfen/AutoDrivePPUK/main/version.json"


def get_current_app_dir() -> str:
    """Mengembalikan direktori root aplikasi (baik saat run script maupun saat jadi EXE)."""
    if getattr(sys, 'frozen', False):
        # Saat dijalankan sebagai PyInstaller EXE
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # Saat dijalankan sebagai script python
        return os.path.dirname(os.path.abspath(__file__))


def check_for_updates(update_url: str = DEFAULT_UPDATE_CHECK_URL, timeout: int = 6) -> Optional[Dict[str, Any]]:
    """
    Memeriksa ke server/cloud atau file konfigurasi apakah versi baru tersedia.
    Mendukung URL HTTP/HTTPS maupun path file lokal untuk pengujian.
    """
    if not update_url:
        return None

    # Dukungan pengecekan file lokal (untuk pengujian atau share drive lokal)
    if os.path.exists(update_url):
        try:
            with open(update_url, "r", encoding="utf-8") as f:
                data = json.load(f)
            latest_v = data.get("latest_version")
            if latest_v:
                if version.parse(latest_v) > version.parse(APP_VERSION):
                    return {
                        "has_update": True,
                        "current_version": APP_VERSION,
                        "latest_version": latest_v,
                        "download_url": data.get("download_url"),
                        "changelog": data.get("changelog", "Pembaruan sistem."),
                        "release_date": data.get("release_date", "")
                    }
                else:
                    return {"has_update": False, "current_version": APP_VERSION, "latest_version": latest_v}
        except Exception as e:
            print(f"[Updater] Gagal membaca update lokal: {e}")
            return None

    if not update_url.startswith("http://") and not update_url.startswith("https://"):
        return None

    try:
        req = urllib.request.Request(
            update_url,
            headers={'User-Agent': f'AutoDrive-Updater/{APP_VERSION}'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                latest_v = data.get("latest_version")
                if latest_v:
                    # Bandingkan versi secara semantik (e.g. 1.1.0 > 1.0.0)
                    if version.parse(latest_v) > version.parse(APP_VERSION):
                        return {
                            "has_update": True,
                            "current_version": APP_VERSION,
                            "latest_version": latest_v,
                            "download_url": data.get("download_url"),
                            "changelog": data.get("changelog", "Pembaruan sistem."),
                            "release_date": data.get("release_date", "")
                        }
                    else:
                        return {"has_update": False, "current_version": APP_VERSION, "latest_version": latest_v}
    except Exception as e:
        print(f"[Updater] Gagal memeriksa update dari {update_url}: {e}")
        return None

    return {"has_update": False, "current_version": APP_VERSION}


def download_and_install_update(
    download_url: str,
    progress_callback: Optional[Callable[[str], None]] = None,
    pre_shutdown_callback: Optional[Callable[[], None]] = None
) -> bool:
    """
    Mengunduh file zip pembaruan, mengekstrak ke folder temporary,
    membuat script batch pengganti file, mematikan aplikasi saat ini,
    dan me-restart aplikasi dengan versi terbaru.
    """
    if not download_url:
        return False

    app_dir = get_current_app_dir()
    temp_dir = tempfile.gettempdir()
    zip_target = os.path.join(temp_dir, "autodrive_update_package.zip")
    extract_target = os.path.join(temp_dir, "autodrive_update_extracted")

    try:
        if progress_callback:
            progress_callback("Mengunduh paket pembaruan...")

        # 1. Unduh / Salin file ZIP pembaruan
        if download_url.startswith("http://") or download_url.startswith("https://"):
            req = urllib.request.Request(
                download_url,
                headers={'User-Agent': f'AutoDrive-Updater/{APP_VERSION}'}
            )
            with urllib.request.urlopen(req, timeout=60) as resp, open(zip_target, 'wb') as out_file:
                out_file.write(resp.read())
        elif os.path.exists(download_url):
            import shutil
            shutil.copy2(download_url, zip_target)
        else:
            raise ValueError(f"Sumber paket update tidak valid atau file tidak ditemukan: {download_url}")

        if progress_callback:
            progress_callback("Mengekstrak berkas pembaruan...")

        # 2. Ekstrak file ZIP ke direktori sementara
        if os.path.exists(extract_target):
            import shutil
            shutil.rmtree(extract_target, ignore_errors=True)
        os.makedirs(extract_target, exist_ok=True)

        with zipfile.ZipFile(zip_target, 'r') as zip_ref:
            zip_ref.extractall(extract_target)

        # Jika di dalam zip terdapat subfolder pembungkus (misal 'AutoDrive')
        source_dir = extract_target
        subfolders = [f for f in os.listdir(extract_target) if os.path.isdir(os.path.join(extract_target, f))]
        if len(subfolders) == 1 and (os.path.exists(os.path.join(extract_target, subfolders[0], "AutoDrive.exe")) or os.path.exists(os.path.join(extract_target, subfolders[0], "main.py"))):
            source_dir = os.path.join(extract_target, subfolders[0])

        if progress_callback:
            progress_callback("Menyiapkan skrip pembaruan otomatis...")

        # 3. Tentukan skrip restart sesuai mode (EXE atau Python Script)
        exe_path = os.path.join(app_dir, "AutoDrive.exe")
        if getattr(sys, 'frozen', False):
            restart_cmd = f'if exist "{exe_path}" ( start "" "{exe_path}" )'
        else:
            restart_cmd = f'start "" "{sys.executable}" "{os.path.join(app_dir, "main.py")}"'

        batch_script_path = os.path.join(temp_dir, "autodrive_updater_worker.bat")

        # Batch script mempertahankan credentials.json, token.json, dan config.json pengguna
        batch_content = f"""@echo off
title Memperbarui AutoDrive Ekin PPUK...
echo Menunggu aplikasi menutup sepenuhnya...
timeout /t 2 /nobreak >nul
taskkill /f /im AutoDrive.exe >nul 2>&1

echo Mengamankan data akun dan konfigurasi lokal...
if exist "{app_dir}\\config.json" (
    copy /y "{app_dir}\\config.json" "%TEMP%\\autodrive_config_backup.json" >nul 2>&1
)
if exist "{app_dir}\\credentials.json" (
    copy /y "{app_dir}\\credentials.json" "%TEMP%\\autodrive_credentials_backup.json" >nul 2>&1
)
if exist "{app_dir}\\token.json" (
    copy /y "{app_dir}\\token.json" "%TEMP%\\autodrive_token_backup.json" >nul 2>&1
)

echo Menyalin berkas versi terbaru...
xcopy /Y /E /I /H /K /R /Q "{source_dir}\\*" "{app_dir}\\"

echo Mengembalikan data konfigurasi dan login pengguna...
if exist "%TEMP%\\autodrive_config_backup.json" (
    copy /y "%TEMP%\\autodrive_config_backup.json" "{app_dir}\\config.json" >nul 2>&1
    del "%TEMP%\\autodrive_config_backup.json" >nul 2>&1
)
if exist "%TEMP%\\autodrive_credentials_backup.json" (
    copy /y "%TEMP%\\autodrive_credentials_backup.json" "{app_dir}\\credentials.json" >nul 2>&1
    del "%TEMP%\\autodrive_credentials_backup.json" >nul 2>&1
)
if exist "%TEMP%\\autodrive_token_backup.json" (
    copy /y "%TEMP%\\autodrive_token_backup.json" "{app_dir}\\token.json" >nul 2>&1
    del "%TEMP%\\autodrive_token_backup.json" >nul 2>&1
)

echo Membersihkan berkas sementara...
del /f /q "{zip_target}" >nul 2>&1
rmdir /s /q "{extract_target}" >nul 2>&1

echo Membuka AutoDrive Ekin PPUK versi terbaru...
{restart_cmd}

REM Hapus file skrip ini sendiri
del "%~f0" >nul 2>&1
exit
"""
        with open(batch_script_path, "w", encoding="utf-8") as bf:
            bf.write(batch_content)

        if progress_callback:
            progress_callback("Menutup aplikasi dan menerapkan pembaruan...")

        # Jalankan callback sebelum shutdown jika ada (e.g. hentikan watcher, lepas mutex)
        if pre_shutdown_callback:
            try:
                pre_shutdown_callback()
            except Exception as e:
                print(f"[Updater Callback Warning] {e}")

        # 4. Jalankan batch script di background terpisah
        subprocess.Popen(
            ["cmd.exe", "/c", batch_script_path],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )

        # Matikan proses saat ini agar file executable tidak terkunci
        sys.exit(0)

    except Exception as e:
        if progress_callback:
            progress_callback(f"Gagal memperbarui: {e}")
        print(f"[Updater Error] {e}")
        return False
