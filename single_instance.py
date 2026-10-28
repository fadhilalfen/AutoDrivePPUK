"""
single_instance.py - Pengaman Single Instance untuk Aplikasi Desktop Windows
Mencegah aplikasi berjalan lebih dari satu proses di latar belakang / System Tray
menggunakan Windows Named Mutex.
"""

import sys
import ctypes
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183


class SingleInstanceLock:
    def __init__(self, app_name: str = "AutoDriveReportManager_SingleInstance_Mutex"):
        self.app_name = app_name
        self.mutex = None
        self.already_running = False

        # Buat Named Mutex di Windows
        kernel32 = ctypes.windll.kernel32
        self.mutex = kernel32.CreateMutexW(None, wintypes.BOOL(True), self.app_name)
        last_error = kernel32.GetLastError()

        if last_error == ERROR_ALREADY_EXISTS:
            self.already_running = True

    def check_and_prevent_duplicate(self) -> bool:
        """
        Jika aplikasi sudah berjalan di System Tray / Background:
        Mengembalikan True jika sudah ada instance lain yang aktif.
        """
        return self.already_running

    def release(self):
        if self.mutex:
            ctypes.windll.kernel32.CloseHandle(self.mutex)
            self.mutex = None
