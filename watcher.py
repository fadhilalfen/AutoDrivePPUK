"""
watcher.py - Folder Watcher & Hierarchical Auto-Upload Engine (Anti-Duplikasi)
Memantau folder Downloads & Screenshots Windows, memverifikasi kesiapan file,
mencegah duplikasi event sistem berkas (debouncing), mengunggah ke target Drive,
dan menghapus file lokal secara aman.
"""

import os
import time
import queue
import threading
from typing import Callable, Optional, Dict, Set
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent

from drive_api import DriveManager
from config_manager import ConfigManager
from image_processor import is_image_file, add_watermark, generate_report_filename

IGNORE_EXTENSIONS = {
    '.crdownload', '.tmp', '.part', '.download', '.partial', '.opdownload'
}

# Jeda waktu minimum (detik) untuk memproses ulang file yang sama (Anti-Duplikasi)
DEBOUNCE_SECONDS = 5.0


def get_windows_directories():
    """Mengambil path default folder Downloads dan Screenshots di Windows."""
    user_profile = os.environ.get('USERPROFILE', os.path.expanduser('~'))
    downloads_dir = os.path.join(user_profile, 'Downloads')
    screenshots_dir = os.path.join(user_profile, 'Pictures', 'Screenshots')

    if not os.path.exists(screenshots_dir):
        try:
            os.makedirs(screenshots_dir, exist_ok=True)
        except Exception:
            pass

    return downloads_dir, screenshots_dir


def wait_for_file_ready(file_path: str, timeout: int = 40, check_interval: float = 0.8) -> bool:
    """Menunggu sampai file selesai ditulis browser/OS dan tidak terkunci."""
    start_time = time.time()
    last_size = -1
    stable_count = 0

    while time.time() - start_time < timeout:
        if not os.path.exists(file_path):
            return False

        try:
            current_size = os.path.getsize(file_path)
            with open(file_path, 'ab'):
                pass

            if current_size > 0 and current_size == last_size:
                stable_count += 1
                if stable_count >= 2:
                    return True
            else:
                stable_count = 0

            last_size = current_size

        except (PermissionError, OSError):
            stable_count = 0

        time.sleep(check_interval)

    return False


class FileWatcherHandler(FileSystemEventHandler):
    """Handler event sistem berkas untuk Watchdog dengan proteksi debouncing."""

    def __init__(self, task_queue: queue.Queue, log_callback: Optional[Callable[[str, str], None]] = None):
        super().__init__()
        self.task_queue = task_queue
        self.log_callback = log_callback
        self._lock = threading.Lock()
        self._recent_events: Dict[str, float] = {}

    def _should_process(self, path: str) -> bool:
        if not path or os.path.isdir(path):
            return False
        
        filename = os.path.basename(path)
        if filename.startswith('~$') or filename.startswith('.'):
            return False

        _, ext = os.path.splitext(filename.lower())
        if ext in IGNORE_EXTENSIONS:
            return False

        # Proteksi Anti-Duplikasi (Debouncing Event Windows)
        # Windows Snipping Tool sering kali memicu on_created dan on_moved sekaligus untuk file yang sama
        norm_path = os.path.normcase(os.path.abspath(path))
        now = time.time()

        with self._lock:
            last_time = self._recent_events.get(norm_path, 0)
            if now - last_time < DEBOUNCE_SECONDS:
                # Event duplikat dalam jeda 5 detik diabaikan
                return False
            self._recent_events[norm_path] = now

            # Bersihkan cache event lama jika terlalu banyak
            if len(self._recent_events) > 500:
                cutoff = now - 60
                self._recent_events = {k: v for k, v in self._recent_events.items() if v > cutoff}

        return True

    def on_created(self, event: FileCreatedEvent):
        if not event.is_directory and self._should_process(event.src_path):
            self.task_queue.put(event.src_path)

    def on_moved(self, event: FileMovedEvent):
        # Browser rename saat download tuntas
        if not event.is_directory and self._should_process(event.dest_path):
            self.task_queue.put(event.dest_path)


class AutoUploadWatcher:
    """Mesin utama watcher dan antrean unggah file otomatis ke folder hierarki."""

    def __init__(self, config_manager: ConfigManager, drive_manager: DriveManager, log_callback: Optional[Callable[[str, str], None]] = None):
        self.config_manager = config_manager
        self.drive_manager = drive_manager
        self.log_callback = log_callback
        
        self.task_queue = queue.Queue()
        self.observer = None
        self.worker_thread = None
        self.is_running = False
        self._active_uploads: Set[str] = set()
        self._upload_lock = threading.Lock()

    def log(self, message: str, level: str = "INFO"):
        if self.log_callback:
            self.log_callback(message, level)
        else:
            print(f"[{level}] {message}")

    def _worker_loop(self):
        while self.is_running:
            try:
                file_path = self.task_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._process_single_file(file_path)
            except Exception as e:
                self.log(f"Error memproses '{os.path.basename(file_path)}': {e}", "ERROR")
            finally:
                self.task_queue.task_done()

    def _process_single_file(self, file_path: str):
        if not os.path.exists(file_path):
            return

        norm_path = os.path.normcase(os.path.abspath(file_path))

        with self._upload_lock:
            if norm_path in self._active_uploads:
                return
            self._active_uploads.add(norm_path)

        try:
            self._do_upload_and_cleanup(file_path)
        finally:
            with self._upload_lock:
                self._active_uploads.discard(norm_path)

    def _do_upload_and_cleanup(self, file_path: str):
        filename = os.path.basename(file_path)
        mode = self.config_manager.get_mode()

        # 1. Mode Standby: jangan upload
        if mode == "Default":
            self.log(f"File terdeteksi: '{filename}'. Mode Standby aktif -> file tetap disimpan di lokal.", "INFO")
            return

        # 2. Dapatkan folder tujuan akhir
        hierarchy = self.config_manager.get_hierarchy()
        target_folder_id = hierarchy.get("kegiatan_id")
        kegiatan_name = hierarchy.get("kegiatan_name") or "Tidak Diketahui"
        rk_name = hierarchy.get("rencana_kinerja_name") or "-"
        bulan_name = hierarchy.get("bulan_name") or "-"

        if not target_folder_id:
            self.log(
                f"File '{filename}' terdeteksi, namun folder tujuan akhir ('Nama Kegiatan') "
                f"belum dipilih pada dropdown! File tetap disimpan di lokal.",
                "WARNING"
            )
            return

        path_display = f"{rk_name} > {bulan_name} > {kegiatan_name}"
        self.log(f"Menyiapkan '{filename}' untuk diunggah ke: [{path_display}]...", "INFO")

        # 3. Tunggu hingga file selesai ditulis dan stabil
        is_ready = wait_for_file_ready(file_path, timeout=35)
        if not is_ready:
            self.log(f"File '{filename}' masih terkunci oleh proses lain. Dibatalkan.", "WARNING")
            return

        # Pastikan file masih ada sebelum diunggah
        if not os.path.exists(file_path):
            return

        # 4. Terapkan Watermark (Khusus File Gambar) jika diaktifkan
        if self.config_manager.get_enable_watermark() and is_image_file(file_path):
            self.log(f"Menambahkan cap watermark tanggal & kegiatan pada '{filename}'...", "INFO")
            if add_watermark(file_path, kegiatan_name, rk_name):
                self.log("Watermark berhasil dicantumkan pada gambar.", "SUCCESS")

        # 5. Tentukan Nama File (Auto-Rename) jika diaktifkan
        target_filename = filename
        if self.config_manager.get_enable_auto_rename():
            target_filename = generate_report_filename(filename, kegiatan_name)
            if target_filename != filename:
                self.log(f"Auto-Rename: '{filename}' -> '{target_filename}'", "INFO")

        # 6. Unggah ke Google Drive
        try:
            self.log(f"Mengunggah '{target_filename}' ke Google Drive...", "UPLOAD")
            upload_result = self.drive_manager.upload_file(file_path, target_folder_id, custom_name=target_filename)
            file_id = upload_result.get('id', 'N/A')
            self.log(f"SUKSES UPLOAD: '{target_filename}' disimpan di [{path_display}] (ID: {file_id})", "SUCCESS")

            # 7. Hapus file lokal setelah terkonfirmasi berhasil
            time.sleep(0.3)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    self.log(f"HAPUS LOKAL: File lokal '{filename}' berhasil dibersihkan dari komputer.", "SUCCESS")
                except Exception as del_err:
                    self.log(f"Upload sukses, namun gagal menghapus file lokal: {del_err}", "WARNING")

        except Exception as up_err:
            self.log(f"GAGAL UPLOAD '{filename}': {up_err}. File lokal tetap aman disimpan.", "ERROR")

    def start(self):
        if self.is_running:
            return

        self.is_running = True
        downloads_dir, screenshots_dir = get_windows_directories()

        self.observer = Observer()
        handler = FileWatcherHandler(self.task_queue, self.log_callback)

        watched_paths = []
        if os.path.exists(downloads_dir):
            self.observer.schedule(handler, downloads_dir, recursive=False)
            watched_paths.append(downloads_dir)

        if os.path.exists(screenshots_dir):
            self.observer.schedule(handler, screenshots_dir, recursive=False)
            watched_paths.append(screenshots_dir)

        self.observer.start()

        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

        paths_str = ", ".join([os.path.basename(p) for p in watched_paths])
        self.log(f"Watcher aktif memantau: {paths_str}", "SUCCESS")

    def stop(self):
        if not self.is_running:
            return

        self.is_running = False
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=2)
            except Exception:
                pass
        self.log("Watcher dinonaktifkan.", "INFO")
