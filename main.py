"""
main.py - Antarmuka Utama (CustomTkinter) dengan Dukungan Mode Ringkas (Mini Floating Widget)
Memungkinkan pengguna mengecilkan jendela aplikasi menjadi widget melayang mini
yang hanya menampilkan dropdown pemilihan folder tujuan agar tidak mengganggu layar kerja.
"""

import os
import sys
import threading
import queue
from typing import Optional, Dict, List, Any
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageDraw
import pystray

from config_manager import ConfigManager
from drive_api import DriveManager, extract_folder_id
from watcher import AutoUploadWatcher, get_windows_directories
from single_instance import SingleInstanceLock
from updater import APP_VERSION, check_for_updates, download_and_install_update, DEFAULT_UPDATE_CHECK_URL

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def get_asset_path(filename: str) -> str:
    """Mengembalikan path file asset baik saat mode dev maupun saat dibundel PyInstaller."""
    if getattr(sys, 'frozen', False):
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "assets", filename)


def create_tray_icon_image():
    """Membuat/memuat ikon 64x64 Bintang Perpusnas untuk System Tray Windows."""
    star_path = get_asset_path("logo_star.png")
    if os.path.exists(star_path):
        try:
            img = Image.open(star_path).convert("RGBA")
            return img.resize((64, 64), Image.Resampling.LANCZOS)
        except Exception:
            pass

    # Fallback jika gambar belum dibuat
    width = 64
    height = 64
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    dc.ellipse([2, 2, width - 3, height - 3], fill="#1f538d", outline="#3b8ed0", width=2)
    return image


class AutoDriveApp(ctk.CTk):
    def __init__(self, single_instance_lock=None):
        super().__init__()
        self.single_instance_lock = single_instance_lock

        # Inisialisasi Modul
        self.config_mgr = ConfigManager()
        self.drive_mgr = DriveManager()
        self.log_queue = queue.Queue()

        # Cache struktur folder Drive
        self.folder_cache: Dict[str, List[Dict[str, str]]] = {}
        self.current_rk_list: List[Dict[str, str]] = []
        self.current_bulan_list: List[Dict[str, str]] = []
        self.current_kegiatan_list: List[Dict[str, str]] = []

        # Status Mode Tampilan (Penuh / Ringkas)
        self.is_compact_mode: bool = self.config_mgr.get_compact_mode()
        self.latest_update_info: Optional[Dict[str, Any]] = None

        # Watcher Engine
        self.watcher = AutoUploadWatcher(
            config_manager=self.config_mgr,
            drive_manager=self.drive_mgr,
            log_callback=self.enqueue_log
        )

        # Konfigurasi Awal Jendela & Ikon Perpusnas
        self.title("AutoDrive Ekin PPUK")

        ico_path = get_asset_path("app_icon.ico")
        png_path = get_asset_path("logo_star.png")
        if os.path.exists(ico_path):
            try:
                self.iconbitmap(ico_path)
            except Exception:
                pass
        if os.path.exists(png_path):
            try:
                # Mengatur iconphoto untuk kompatibilitas taskbar
                icon_img = Image.open(png_path)
                from PIL import ImageTk
                self._tk_icon = ImageTk.PhotoImage(icon_img)
                self.iconphoto(False, self._tk_icon)
            except Exception:
                pass
        
        # Always on Top awal
        is_topmost = self.config_mgr.get_always_on_top()
        self.attributes('-topmost', is_topmost)

        # Handler Close (X) ke Tray
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        # Bangun Komponen UI
        self._build_ui()

        # Inisialisasi System Tray
        self.tray_icon: Optional[pystray.Icon] = None
        self._init_system_tray()

        # Terapkan Mode Tampilan Awal (Ringkas atau Penuh)
        self._apply_view_mode(self.is_compact_mode)

        # Loop Antrean Log
        self.after(100, self._process_log_queue)

        # Jalankan Watcher Latar Belakang
        self.watcher.start()

        # Periksa status autentikasi Drive
        self._update_auth_status_badge()

        # Cek update otomatis jika diaktifkan (setelah 2.5 detik)
        if self.config_mgr.get_auto_check_update():
            self.after(2500, self.check_updates_background)

    def _build_ui(self):
        # -------------------------------------------------------------
        # 1. TOP BAR KOMPAK (Selalu terlihat di mode Penuh & Ringkas)
        # -------------------------------------------------------------
        self.top_bar = ctk.CTkFrame(self, corner_radius=10, fg_color=("#242424", "#181818"))
        self.top_bar.pack(fill="x", padx=12, pady=(10, 4))

        # Brand & Logo Perpusnas di Top Bar
        logo_png = get_asset_path("logo_star.png")
        if os.path.exists(logo_png):
            try:
                self.brand_logo_img = ctk.CTkImage(
                    light_image=Image.open(logo_png),
                    dark_image=Image.open(logo_png),
                    size=(22, 22)
                )
            except Exception:
                self.brand_logo_img = None
        else:
            self.brand_logo_img = None

        self.lbl_app_brand = ctk.CTkLabel(
            self.top_bar,
            text=" AutoDrive Ekin PPUK",
            image=self.brand_logo_img,
            compound="left",
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.lbl_app_brand.pack(side="left", padx=(10, 4), pady=6)

        # Lencana Versi & Tombol Cek Pembaruan di Top Bar
        self.btn_update_badge = ctk.CTkButton(
            self.top_bar,
            text=f"v{APP_VERSION}",
            width=58,
            height=24,
            fg_color="#37474F",
            hover_color="#455A64",
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.on_click_update_btn
        )
        self.btn_update_badge.pack(side="left", padx=2, pady=6)

        # Tombol Minimize ke Tray cepat
        self.btn_tray_quick = ctk.CTkButton(
            self.top_bar,
            text="Sembunyikan",
            width=85,
            height=26,
            fg_color="#37474F",
            hover_color="#455A64",
            font=ctk.CTkFont(size=11),
            command=self.hide_to_tray
        )
        self.btn_tray_quick.pack(side="right", padx=(4, 10), pady=6)

        # Tombol Beralih Mode (Penuh / Ringkas)
        self.btn_toggle_mode = ctk.CTkButton(
            self.top_bar,
            text="🗗 Mode Ringkas",
            width=115,
            height=26,
            fg_color="#1f538d",
            hover_color="#2b73be",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.toggle_view_mode
        )
        self.btn_toggle_mode.pack(side="right", padx=4, pady=6)

        # Checkbox Always on Top mini
        self.chk_always_top = ctk.CTkCheckBox(
            self.top_bar,
            text="Melayang",
            font=ctk.CTkFont(size=11),
            width=65,
            command=self.toggle_always_on_top
        )
        if self.config_mgr.get_always_on_top():
            self.chk_always_top.select()
        else:
            self.chk_always_top.deselect()
        self.chk_always_top.pack(side="right", padx=6, pady=6)

        # -------------------------------------------------------------
        # 2. FRAME PENGATURAN LENGKAP (Disembunyikan saat Mode Ringkas)
        # -------------------------------------------------------------
        self.frame_full_setup = ctk.CTkFrame(self, fg_color="transparent")
        # Akan di-pack saat mode penuh

        # Sub-Frame Status Bar & Login
        status_bar = ctk.CTkFrame(self.frame_full_setup, fg_color="transparent")
        status_bar.pack(fill="x", padx=12, pady=(2, 6))

        self.auth_badge = ctk.CTkLabel(
            status_bar,
            text="Memeriksa Drive...",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#333333",
            corner_radius=6,
            padx=10,
            pady=3
        )
        self.auth_badge.pack(side="left", padx=(0, 6))

        self.watcher_badge = ctk.CTkLabel(
            status_bar,
            text="● Watcher Aktif",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1d5c27",
            text_color="#85e396",
            corner_radius=6,
            padx=10,
            pady=3
        )
        self.watcher_badge.pack(side="left")

        self.btn_auth = ctk.CTkButton(
            status_bar,
            text="Login / Tes Drive",
            width=120,
            height=26,
            font=ctk.CTkFont(size=11),
            command=self.on_btn_auth_click
        )
        self.btn_auth.pack(side="right")

        self.btn_check_update = ctk.CTkButton(
            status_bar,
            text="🔄 Cek Update",
            width=90,
            height=26,
            fg_color="#37474F",
            hover_color="#455A64",
            font=ctk.CTkFont(size=11),
            command=self.on_click_update_btn
        )
        self.btn_check_update.pack(side="right", padx=(0, 6))

        # Sub-Frame Input Root Folder
        card_root = ctk.CTkFrame(self.frame_full_setup, corner_radius=10)
        card_root.pack(fill="x", padx=12, pady=4)

        row_root_top = ctk.CTkFrame(card_root, fg_color="transparent")
        row_root_top.pack(fill="x", padx=12, pady=(8, 2))

        lbl_root = ctk.CTkLabel(row_root_top, text="🏠 Link Root Folder (Home):", font=ctk.CTkFont(weight="bold", size=12))
        lbl_root.pack(side="left")

        self.seg_mode = ctk.CTkSegmentedButton(
            row_root_top,
            values=["Auto-Upload ke Drive", "Standby (Lokal)"],
            height=26,
            font=ctk.CTkFont(size=11),
            command=self.on_mode_changed
        )
        current_mode = self.config_mgr.get_mode()
        self.seg_mode.set("Auto-Upload ke Drive" if current_mode == "Drive" else "Standby (Lokal)")
        self.seg_mode.pack(side="right")

        row_root_input = ctk.CTkFrame(card_root, fg_color="transparent")
        row_root_input.pack(fill="x", padx=12, pady=(2, 8))

        self.entry_root_url = ctk.CTkEntry(
            row_root_input,
            placeholder_text="Tempel URL atau ID Root Folder Google Drive...",
            height=32,
            font=ctk.CTkFont(size=11)
        )
        self.entry_root_url.insert(0, self.config_mgr.get_root_folder_url())
        self.entry_root_url.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_load_root = ctk.CTkButton(
            row_root_input,
            text="🔄 Muat Subfolder",
            width=120,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.load_root_structure_async
        )
        self.btn_load_root.pack(side="right")

        # -------------------------------------------------------------
        # 3. KARTU DROPDOWN BERTINGKAT (UTAMA - Tampil di Keduanya)
        # -------------------------------------------------------------
        self.card_cascade = ctk.CTkFrame(self, corner_radius=10)
        self.card_cascade.pack(fill="x", padx=12, pady=4)

        # Level 1: Rencana Kinerja
        row_rk = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_rk.pack(fill="x", padx=12, pady=(8, 3))
        ctk.CTkLabel(row_rk, text="1. Rencana Kinerja:", width=125, anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        self.combo_rk = ctk.CTkComboBox(
            row_rk,
            values=["-- Muat Root URL dahulu --"],
            height=28,
            font=ctk.CTkFont(size=11),
            command=self.on_rk_selected
        )
        self.combo_rk.pack(side="right", fill="x", expand=True)

        # Level 2: Bulan
        row_bulan = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_bulan.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(row_bulan, text="2. Bulan:", width=125, anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        self.combo_bulan = ctk.CTkComboBox(
            row_bulan,
            values=["-- Pilih Rencana Kinerja --"],
            height=28,
            font=ctk.CTkFont(size=11),
            command=self.on_bulan_selected
        )
        self.combo_bulan.pack(side="right", fill="x", expand=True)

        # Level 3: Nama Kegiatan (Target Upload Akhir)
        row_kegiatan = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_kegiatan.pack(fill="x", padx=12, pady=3)
        ctk.CTkLabel(row_kegiatan, text="3. Nama Kegiatan:", width=125, anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
        self.combo_kegiatan = ctk.CTkComboBox(
            row_kegiatan,
            values=["-- Pilih Bulan dahulu --"],
            height=28,
            font=ctk.CTkFont(size=11),
            command=self.on_kegiatan_selected
        )
        self.combo_kegiatan.pack(side="right", fill="x", expand=True)

        # Info Sasaran & Tombol Buat Folder Baru
        row_target_info = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_target_info.pack(fill="x", padx=12, pady=(4, 8))

        self.lbl_active_target = ctk.CTkLabel(
            row_target_info,
            text="🎯 Sasaran: Belum Lengkap",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FFA726",
            anchor="w"
        )
        self.lbl_active_target.pack(side="left", fill="x", expand=True)

        self.btn_new_folder = ctk.CTkButton(
            row_target_info,
            text="+ Buat Subfolder",
            width=105,
            height=24,
            fg_color="#37474F",
            hover_color="#455A64",
            font=ctk.CTkFont(size=10),
            command=self.prompt_create_folder
        )
        self.btn_new_folder.pack(side="right")

        # Baris Opsi Watermark & Auto-Rename
        row_extra_features = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_extra_features.pack(fill="x", padx=12, pady=(0, 8))

        self.chk_watermark = ctk.CTkCheckBox(
            row_extra_features,
            text="💧 Watermark Bukti",
            font=ctk.CTkFont(size=11),
            command=self.toggle_watermark
        )
        if self.config_mgr.get_enable_watermark():
            self.chk_watermark.select()
        else:
            self.chk_watermark.deselect()
        self.chk_watermark.pack(side="left", padx=(0, 12))

        self.chk_auto_rename = ctk.CTkCheckBox(
            row_extra_features,
            text="🏷️ Auto-Rename Kegiatan",
            font=ctk.CTkFont(size=11),
            command=self.toggle_auto_rename
        )
        if self.config_mgr.get_enable_auto_rename():
            self.chk_auto_rename.select()
        else:
            self.chk_auto_rename.deselect()
        self.chk_auto_rename.pack(side="left")

        # -------------------------------------------------------------
        # 4. FRAME LOG AKTIVITAS (Disembunyikan saat Mode Ringkas)
        # -------------------------------------------------------------
        self.frame_log = ctk.CTkFrame(self, corner_radius=10)
        # Akan di-pack saat mode penuh

        row_log_head = ctk.CTkFrame(self.frame_log, fg_color="transparent")
        row_log_head.pack(fill="x", padx=12, pady=(6, 2))

        lbl_log = ctk.CTkLabel(row_log_head, text="Aktivitas Pemantauan:", font=ctk.CTkFont(weight="bold", size=11))
        lbl_log.pack(side="left")

        btn_clear = ctk.CTkButton(
            row_log_head,
            text="Bersihkan Log",
            width=85,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color="#424242",
            hover_color="#616161",
            command=self.clear_log
        )
        btn_clear.pack(side="right")

        self.txt_log = ctk.CTkTextbox(self.frame_log, font=ctk.CTkFont(family="Consolas", size=10), wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=12, pady=(2, 6))

        row_quick_btn = ctk.CTkFrame(self.frame_log, fg_color="transparent")
        row_quick_btn.pack(fill="x", padx=12, pady=(0, 6))

        btn_dl = ctk.CTkButton(
            row_quick_btn,
            text="📁 Folder Downloads",
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#263238",
            hover_color="#37474F",
            command=self.open_downloads_folder
        )
        btn_dl.pack(side="left", fill="x", expand=True, padx=(0, 4))

        btn_ss = ctk.CTkButton(
            row_quick_btn,
            text="📸 Folder Screenshots",
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#263238",
            hover_color="#37474F",
            command=self.open_screenshots_folder
        )
        btn_ss.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # Tampilkan label target awal
        self._refresh_target_label()

    # ==========================================
    # TOGGLE MODE RINGKAS / PENUH
    # ==========================================
    def toggle_view_mode(self):
        self.is_compact_mode = not self.is_compact_mode
        self.config_mgr.set_compact_mode(self.is_compact_mode)
        self._apply_view_mode(self.is_compact_mode)

    def _apply_view_mode(self, is_compact: bool):
        if is_compact:
            # Sembunyikan bagian setup dan log
            self.frame_full_setup.pack_forget()
            self.frame_log.pack_forget()

            # Pastikan card cascade tetap tampil
            self.card_cascade.pack_forget()
            self.card_cascade.pack(fill="x", padx=12, pady=4)

            # Perkecil ukuran jendela menjadi widget mini
            self.minsize(370, 260)
            self.geometry("385x275")
            self.btn_toggle_mode.configure(text="⛶ Mode Penuh", fg_color="#2E7D32", hover_color="#388E3C")
            self.lbl_app_brand.configure(text=" AutoDrive Ekin [Mini]")
        else:
            # Tampilkan semua komponen
            self.frame_full_setup.pack(fill="x", padx=0, pady=0, before=self.card_cascade)
            self.card_cascade.pack_forget()
            self.card_cascade.pack(fill="x", padx=12, pady=4)
            self.frame_log.pack(fill="both", expand=True, padx=12, pady=(4, 10))

            # Kembalikan ke ukuran standar
            self.minsize(580, 700)
            self.geometry("640x760")
            self.btn_toggle_mode.configure(text="🗗 Mode Ringkas", fg_color="#1f538d", hover_color="#2b73be")
            self.lbl_app_brand.configure(text=" AutoDrive Ekin PPUK")

    def toggle_watermark(self):
        val = bool(self.chk_watermark.get())
        self.config_mgr.set_enable_watermark(val)
        status = "Aktif" if val else "Nonaktif"
        self.enqueue_log(f"Watermark Gambar: {status}", "INFO")

    def toggle_auto_rename(self):
        val = bool(self.chk_auto_rename.get())
        self.config_mgr.set_enable_auto_rename(val)
        status = "Aktif" if val else "Nonaktif"
        self.enqueue_log(f"Auto-Rename File: {status}", "INFO")

    # ==========================================
    # LOGIKA POHON FOLDER GOOGLE DRIVE (ASYNC)
    # ==========================================
    def on_mode_changed(self, value: str):
        if value == "Auto-Upload ke Drive":
            self.config_mgr.set_mode("Drive")
            self.enqueue_log("Mode: Auto-Upload ke Google Drive.", "INFO")
        else:
            self.config_mgr.set_mode("Default")
            self.enqueue_log("Mode: Standby (File lokal tidak diunggah).", "INFO")
        self._refresh_target_label()

    def load_root_structure_async(self):
        root_input = self.entry_root_url.get().strip()
        root_id = extract_folder_id(root_input)

        if not root_id:
            self.enqueue_log("URL/ID Root Folder tidak valid!", "WARNING")
            return

        self.config_mgr.set_root_folder_url(root_input)
        self.btn_load_root.configure(state="disabled", text="Memuat...")

        def _worker():
            try:
                self.enqueue_log(f"Memuat daftar 'Rencana Kinerja' dari Root ID: {root_id}...", "INFO")
                folders = self.drive_mgr.list_subfolders(root_id)
                self.folder_cache[root_id] = folders
                self.current_rk_list = folders

                names = [f["name"] for f in folders]
                if not names:
                    names = ["-- Tidak ada subfolder di Root --"]

                self.after(0, lambda: self._on_rk_loaded(names))
            except Exception as e:
                self.enqueue_log(f"Gagal memuat subfolder Root: {e}", "ERROR")
                self.after(0, lambda: self.btn_load_root.configure(state="normal", text="🔄 Muat Subfolder"))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_rk_loaded(self, names: List[str]):
        self.btn_load_root.configure(state="normal", text="🔄 Muat Subfolder")
        self.combo_rk.configure(values=names)

        saved = self.config_mgr.get_hierarchy()
        saved_rk = saved.get("rencana_kinerja_name")
        if saved_rk in names:
            self.combo_rk.set(saved_rk)
            self.on_rk_selected(saved_rk)
        elif names and names[0] != "-- Tidak ada subfolder di Root --":
            self.combo_rk.set(names[0])
            self.on_rk_selected(names[0])
        else:
            self.combo_rk.set(names[0])
            self.combo_bulan.configure(values=["-- Tidak ada Bulan --"])
            self.combo_kegiatan.configure(values=["-- Tidak ada Kegiatan --"])

    def on_rk_selected(self, selected_name: str):
        selected_item = next((f for f in self.current_rk_list if f["name"] == selected_name), None)
        if not selected_item:
            return

        rk_id = selected_item["id"]
        self.combo_bulan.configure(values=["Memuat Bulan..."])
        self.combo_bulan.set("Memuat Bulan...")
        self.combo_kegiatan.configure(values=["-- Menunggu Bulan --"])
        self.combo_kegiatan.set("-- Menunggu Bulan --")

        def _worker():
            try:
                if rk_id not in self.folder_cache:
                    self.enqueue_log(f"Memuat daftar 'Bulan' untuk: {selected_name}...", "INFO")
                    subfolders = self.drive_mgr.list_subfolders(rk_id)
                    self.folder_cache[rk_id] = subfolders
                else:
                    subfolders = self.folder_cache[rk_id]

                self.current_bulan_list = subfolders
                names = [f["name"] for f in subfolders]
                if not names:
                    names = ["-- Belum ada subfolder Bulan --"]

                self.after(0, lambda: self._on_bulan_loaded(selected_item, names))
            except Exception as e:
                self.enqueue_log(f"Gagal memuat Bulan: {e}", "ERROR")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_bulan_loaded(self, rk_item: Dict[str, str], names: List[str]):
        self.combo_bulan.configure(values=names)
        saved = self.config_mgr.get_hierarchy()
        saved_bulan = saved.get("bulan_name")

        if saved_bulan in names:
            self.combo_bulan.set(saved_bulan)
            self.on_bulan_selected(saved_bulan)
        elif names and names[0] != "-- Belum ada subfolder Bulan --":
            self.combo_bulan.set(names[0])
            self.on_bulan_selected(names[0])
        else:
            self.combo_bulan.set(names[0])
            self._save_active_hierarchy(rk_item["id"], rk_item["name"], "", "", "", "")

    def on_bulan_selected(self, selected_name: str):
        selected_item = next((f for f in self.current_bulan_list if f["name"] == selected_name), None)
        if not selected_item:
            return

        bulan_id = selected_item["id"]
        self.combo_kegiatan.configure(values=["Memuat Kegiatan..."])
        self.combo_kegiatan.set("Memuat Kegiatan...")

        def _worker():
            try:
                if bulan_id not in self.folder_cache:
                    self.enqueue_log(f"Memuat 'Nama Kegiatan' untuk bulan: {selected_name}...", "INFO")
                    subfolders = self.drive_mgr.list_subfolders(bulan_id)
                    self.folder_cache[bulan_id] = subfolders
                else:
                    subfolders = self.folder_cache[bulan_id]

                self.current_kegiatan_list = subfolders
                names = [f["name"] for f in subfolders]
                if not names:
                    names = ["-- Belum ada subfolder Kegiatan --"]

                self.after(0, lambda: self._on_kegiatan_loaded(selected_item, names))
            except Exception as e:
                self.enqueue_log(f"Gagal memuat Kegiatan: {e}", "ERROR")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_kegiatan_loaded(self, bulan_item: Dict[str, str], names: List[str]):
        self.combo_kegiatan.configure(values=names)
        saved = self.config_mgr.get_hierarchy()
        saved_kegiatan = saved.get("kegiatan_name")

        if saved_kegiatan in names:
            self.combo_kegiatan.set(saved_kegiatan)
            self.on_kegiatan_selected(saved_kegiatan)
        elif names and names[0] != "-- Belum ada subfolder Kegiatan --":
            self.combo_kegiatan.set(names[0])
            self.on_kegiatan_selected(names[0])
        else:
            self.combo_kegiatan.set(names[0])
            rk_name = self.combo_rk.get()
            rk_item = next((f for f in self.current_rk_list if f["name"] == rk_name), None)
            rk_id = rk_item["id"] if rk_item else ""
            self._save_active_hierarchy(rk_id, rk_name, bulan_item["id"], bulan_item["name"], "", "")

    def on_kegiatan_selected(self, selected_name: str):
        selected_item = next((f for f in self.current_kegiatan_list if f["name"] == selected_name), None)
        if not selected_item:
            return

        rk_name = self.combo_rk.get()
        rk_item = next((f for f in self.current_rk_list if f["name"] == rk_name), None)
        rk_id = rk_item["id"] if rk_item else ""

        bulan_name = self.combo_bulan.get()
        bulan_item = next((f for f in self.current_bulan_list if f["name"] == bulan_name), None)
        bulan_id = bulan_item["id"] if bulan_item else ""

        self._save_active_hierarchy(rk_id, rk_name, bulan_id, bulan_name, selected_item["id"], selected_item["name"])
        self.enqueue_log(f"Sasaran aktif diatur ke: {selected_item['name']}", "SUCCESS")

    def _save_active_hierarchy(self, rk_id, rk_name, bulan_id, bulan_name, kegiatan_id, kegiatan_name):
        self.config_mgr.set_hierarchy(rk_id, rk_name, bulan_id, bulan_name, kegiatan_id, kegiatan_name)
        self._refresh_target_label()
        self._update_tray_menu()

    def _refresh_target_label(self):
        mode = self.config_mgr.get_mode()
        if mode == "Default":
            self.lbl_active_target.configure(
                text="🎯 Sasaran: Standby Lokal (Tidak Unggah)",
                text_color="#81C784"
            )
            return

        h = self.config_mgr.get_hierarchy()
        if h.get("kegiatan_id"):
            display_str = f"🎯 Sasaran: {h.get('kegiatan_name')}"
            self.lbl_active_target.configure(text=display_str, text_color="#64B5F6")
        else:
            self.lbl_active_target.configure(text="🎯 Sasaran: Belum Lengkap", text_color="#FFA726")

    # ==========================================
    # BUAT SUBFOLDER BARU ON-THE-FLY
    # ==========================================
    def prompt_create_folder(self):
        dialog = ctk.CTkInputDialog(
            text="Nama Subfolder Baru yang ingin dibuat di folder saat ini:",
            title="Buat Subfolder Google Drive"
        )
        folder_name = dialog.get_input()
        if not folder_name or not folder_name.strip():
            return

        bulan_name = self.combo_bulan.get()
        bulan_item = next((f for f in self.current_bulan_list if f["name"] == bulan_name), None)
        rk_name = self.combo_rk.get()
        rk_item = next((f for f in self.current_rk_list if f["name"] == rk_name), None)

        parent_id = None
        parent_level = ""
        if bulan_item and bulan_item.get("id"):
            parent_id = bulan_item["id"]
            parent_level = f"Bulan '{bulan_name}'"
        elif rk_item and rk_item.get("id"):
            parent_id = rk_item["id"]
            parent_level = f"Rencana Kinerja '{rk_name}'"
        else:
            root_id = extract_folder_id(self.entry_root_url.get())
            if root_id:
                parent_id = root_id
                parent_level = "Root Folder"

        if not parent_id:
            self.enqueue_log("Pilih folder induk terlebih dahulu!", "WARNING")
            return

        def _create_worker():
            try:
                self.enqueue_log(f"Membuat subfolder '{folder_name}'...", "INFO")
                created = self.drive_mgr.create_subfolder(parent_id, folder_name)
                self.enqueue_log(f"Subfolder '{created.get('name')}' berhasil dibuat!", "SUCCESS")
                if parent_id in self.folder_cache:
                    del self.folder_cache[parent_id]
                if parent_level.startswith("Bulan"):
                    self.after(0, lambda: self.on_bulan_selected(bulan_name))
                elif parent_level.startswith("Rencana Kinerja"):
                    self.after(0, lambda: self.on_rk_selected(rk_name))
                else:
                    self.after(0, self.load_root_structure_async)
            except Exception as e:
                self.enqueue_log(f"Gagal membuat subfolder: {e}", "ERROR")

        threading.Thread(target=_create_worker, daemon=True).start()

    # ==========================
    # ALWAYS ON TOP
    # ==========================
    def toggle_always_on_top(self):
        is_top = bool(self.chk_always_top.get())
        self.attributes('-topmost', is_top)
        self.config_mgr.set_always_on_top(is_top)
        self.enqueue_log(f"Always on Top: {'Aktif' if is_top else 'Nonaktif'}", "INFO")

    # ==========================
    # LOG QUEUE & REALTIME TEXT
    # ==========================
    def enqueue_log(self, message: str, level: str = "INFO"):
        self.log_queue.put((message, level, datetime.now().strftime("%H:%M:%S")))

    def _process_log_queue(self):
        while not self.log_queue.empty():
            try:
                msg, level, timestamp = self.log_queue.get_nowait()
                tag = f"[{timestamp}] [{level}] "
                full_text = f"{tag}{msg}\n"
                self.txt_log.insert("end", full_text)
                self.txt_log.see("end")
            except queue.Empty:
                break
        self.after(150, self._process_log_queue)

    def clear_log(self):
        self.txt_log.delete("1.0", "end")

    # ==========================
    # DRIVE AUTHENTICATION
    # ==========================
    def _update_auth_status_badge(self):
        is_ready, desc = self.drive_mgr.get_auth_status()
        if is_ready:
            self.auth_badge.configure(
                text="● Drive: Terhubung",
                fg_color="#1d5c27",
                text_color="#85e396"
            )
        else:
            if not os.path.exists(self.drive_mgr.credentials_path):
                self.auth_badge.configure(
                    text="⚠ credentials.json Belum Ada",
                    fg_color="#8a4b08",
                    text_color="#fcd34d"
                )
            else:
                self.auth_badge.configure(
                    text="● Perlu Login Pertama",
                    fg_color="#5c441d",
                    text_color="#fcd34d"
                )

    def on_btn_auth_click(self):
        def _auth_worker():
            self.enqueue_log("Memulai otorisasi Google Drive via browser...", "INFO")
            try:
                self.drive_mgr.authenticate(interactive=True)
                self.enqueue_log("Otorisasi Google Drive berhasil!", "SUCCESS")
                self.after(0, self._update_auth_status_badge)
                if self.entry_root_url.get().strip():
                    self.after(100, self.load_root_structure_async)
            except Exception as e:
                self.enqueue_log(f"Gagal otentikasi Google Drive: {e}", "ERROR")
                self.after(0, self._update_auth_status_badge)

        threading.Thread(target=_auth_worker, daemon=True).start()

    # ==========================
    # AUTO-UPDATER (Cek & Pasang Pembaruan)
    # ==========================
    def check_updates_background(self):
        """Memeriksa versi baru di server/cloud secara asinkron tanpa mengganggu UI."""
        def _worker():
            url = self.config_mgr.get_update_check_url() or DEFAULT_UPDATE_CHECK_URL
            res = check_for_updates(url)
            if res and res.get("has_update"):
                self.latest_update_info = res
                self.after(0, lambda: self._show_update_available_badge(res))
            else:
                self.latest_update_info = None

        threading.Thread(target=_worker, daemon=True).start()

    def _show_update_available_badge(self, result: Dict[str, Any]):
        """Menampilkan indikator visual saat ada pembaruan versi baru."""
        new_v = result.get("latest_version", "")
        self.btn_update_badge.configure(
            text=f"🎉 v{new_v}",
            fg_color="#2e7d32",
            hover_color="#388e3c"
        )
        if hasattr(self, 'btn_check_update'):
            self.btn_check_update.configure(
                text="⭐ Update!",
                fg_color="#2e7d32",
                hover_color="#388e3c"
            )
        self.enqueue_log(
            f"🎉 Pembaruan v{new_v} tersedia! Klik tombol versi hijau di atas untuk memperbarui.",
            "SUCCESS"
        )

    def on_click_update_btn(self):
        """Handler saat pengguna mengklik tombol versi atau tombol Cek Update."""
        if self.latest_update_info and self.latest_update_info.get("has_update"):
            self.show_update_dialog(self.latest_update_info)
            return

        if hasattr(self, 'btn_check_update'):
            self.btn_check_update.configure(text="⏳ Cek...", state="disabled")
        self.btn_update_badge.configure(state="disabled")

        def _worker():
            url = self.config_mgr.get_update_check_url() or DEFAULT_UPDATE_CHECK_URL
            self.enqueue_log("Memeriksa pembaruan ke server...", "INFO")
            res = check_for_updates(url)

            def _done():
                if hasattr(self, 'btn_check_update'):
                    self.btn_check_update.configure(state="normal", text="🔄 Cek Update")
                self.btn_update_badge.configure(state="normal")

                if res and res.get("has_update"):
                    self.latest_update_info = res
                    self._show_update_available_badge(res)
                    self.show_update_dialog(res)
                elif res and not res.get("has_update"):
                    self.latest_update_info = None
                    self.btn_update_badge.configure(
                        text=f"v{APP_VERSION}",
                        fg_color="#37474F",
                        hover_color="#455A64"
                    )
                    self._show_up_to_date_dialog(res.get("current_version", APP_VERSION))
                else:
                    self.enqueue_log("Tidak dapat terhubung ke server pembaruan atau format tidak valid.", "WARNING")
                    self._show_update_error_dialog(url)

            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def show_update_dialog(self, update_info: Dict[str, Any]):
        """Menampilkan dialog modern rincian pembaruan versi baru."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("🚀 Pembaruan AutoDrive Ekin PPUK Tersedia")
        dialog.geometry("500x450")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 250
            y = self.winfo_y() + (self.winfo_height() // 2) - 225
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        # Header Card
        card_header = ctk.CTkFrame(dialog, corner_radius=10, fg_color=("#1f538d", "#14375e"))
        card_header.pack(fill="x", padx=16, pady=(16, 10))

        lbl_title = ctk.CTkLabel(
            card_header,
            text="✨ Versi Baru Siap Diperbarui!",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#ffffff"
        )
        lbl_title.pack(anchor="w", padx=14, pady=(12, 4))

        cur_v = update_info.get("current_version", APP_VERSION)
        new_v = update_info.get("latest_version", "-")
        release_dt = update_info.get("release_date", "")
        dt_text = f" • Dirilis: {release_dt}" if release_dt else ""

        lbl_vers = ctk.CTkLabel(
            card_header,
            text=f"Versi Terpasang: v{cur_v}  ➔  Versi Terbaru: v{new_v}{dt_text}",
            font=ctk.CTkFont(size=12),
            text_color="#e0e0e0"
        )
        lbl_vers.pack(anchor="w", padx=14, pady=(0, 12))

        # Changelog Card
        card_body = ctk.CTkFrame(dialog, corner_radius=10)
        card_body.pack(fill="both", expand=True, padx=16, pady=6)

        lbl_notes = ctk.CTkLabel(
            card_body,
            text="Catatan Perubahan & Fitur Baru (Changelog):",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_notes.pack(anchor="w", padx=12, pady=(10, 4))

        txt_changelog = ctk.CTkTextbox(
            card_body,
            height=130,
            font=ctk.CTkFont(size=11),
            corner_radius=6
        )
        txt_changelog.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        changelog_text = update_info.get("changelog", "Tidak ada rincian perubahan.")
        txt_changelog.insert("1.0", changelog_text)
        txt_changelog.configure(state="disabled")

        # Status & Progress
        lbl_status = ctk.CTkLabel(
            dialog,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#4fc3f7"
        )
        lbl_status.pack(fill="x", padx=16, pady=(2, 2))

        progress_bar = ctk.CTkProgressBar(dialog, mode="indeterminate", height=8)

        # Tombol Aksi
        btn_box = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_box.pack(fill="x", padx=16, pady=(8, 16))

        btn_settings = ctk.CTkButton(
            btn_box,
            text="⚙️ Atur URL",
            width=90,
            height=34,
            fg_color="#37474F",
            hover_color="#455A64",
            font=ctk.CTkFont(size=11),
            command=self.show_update_settings_dialog
        )
        btn_settings.pack(side="left")

        btn_cancel = ctk.CTkButton(
            btn_box,
            text="Nanti Saja",
            width=95,
            height=34,
            fg_color="#424242",
            hover_color="#616161",
            font=ctk.CTkFont(size=11),
            command=dialog.destroy
        )
        btn_cancel.pack(side="right", padx=(8, 0))

        def _start_download():
            dl_url = update_info.get("download_url")
            if not dl_url:
                lbl_status.configure(text="❌ Link unduhan update tidak valid.", text_color="#ef5350")
                return

            btn_update_now.configure(state="disabled", text="⏳ Memproses...")
            btn_cancel.configure(state="disabled")
            btn_settings.configure(state="disabled")
            progress_bar.pack(fill="x", padx=16, pady=(2, 6), before=btn_box)
            progress_bar.start()

            def _progress_cb(msg: str):
                dialog.after(0, lambda: lbl_status.configure(text=msg))

            def _pre_shutdown():
                self.watcher.stop()
                if self.tray_icon:
                    self.tray_icon.stop()
                if self.single_instance_lock:
                    self.single_instance_lock.release()

            def _worker():
                ok = download_and_install_update(
                    download_url=dl_url,
                    progress_callback=_progress_cb,
                    pre_shutdown_callback=_pre_shutdown
                )
                if not ok:
                    def _fail():
                        progress_bar.stop()
                        progress_bar.pack_forget()
                        btn_update_now.configure(state="normal", text="🔄 Coba Lagi")
                        btn_cancel.configure(state="normal")
                        btn_settings.configure(state="normal")
                        lbl_status.configure(text="❌ Gagal mengunduh atau mengekstrak pembaruan.", text_color="#ef5350")
                    dialog.after(0, _fail)

            threading.Thread(target=_worker, daemon=True).start()

        btn_update_now = ctk.CTkButton(
            btn_box,
            text="⬇️ Perbarui Sekarang",
            width=150,
            height=34,
            fg_color="#2e7d32",
            hover_color="#388e3c",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=_start_download
        )
        btn_update_now.pack(side="right")

    def _show_up_to_date_dialog(self, cur_v: str):
        """Menampilkan dialog bahwa aplikasi sudah dalam versi terbaru."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Aplikasi Sudah Terbaru")
        dialog.geometry("420x220")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 210
            y = self.winfo_y() + (self.winfo_height() // 2) - 110
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        card = ctk.CTkFrame(dialog, corner_radius=10)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        lbl_icon = ctk.CTkLabel(
            card,
            text="✅ Versi Terbaru",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#81c784"
        )
        lbl_icon.pack(pady=(16, 6))

        lbl_desc = ctk.CTkLabel(
            card,
            text=f"Anda sudah menggunakan AutoDrive Ekin PPUK versi terbaru (v{cur_v}).\nTidak ada pembaruan baru yang ditemukan.",
            font=ctk.CTkFont(size=11),
            justify="center"
        )
        lbl_desc.pack(padx=16, pady=(0, 16))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 10))

        btn_settings = ctk.CTkButton(
            btn_row,
            text="⚙️ Atur URL Update",
            width=130,
            height=30,
            fg_color="#37474F",
            hover_color="#455A64",
            font=ctk.CTkFont(size=11),
            command=self.show_update_settings_dialog
        )
        btn_settings.pack(side="left")

        btn_ok = ctk.CTkButton(
            btn_row,
            text="Tutup",
            width=90,
            height=30,
            font=ctk.CTkFont(size=11),
            command=dialog.destroy
        )
        btn_ok.pack(side="right")

    def _show_update_error_dialog(self, url: str):
        """Menampilkan dialog jika gagal menghubungi server pembaruan."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Pemeriksaan Pembaruan")
        dialog.geometry("460x250")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 230
            y = self.winfo_y() + (self.winfo_height() // 2) - 125
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        card = ctk.CTkFrame(dialog, corner_radius=10)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        lbl_icon = ctk.CTkLabel(
            card,
            text="ℹ️ Info Pembaruan",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ffb74d"
        )
        lbl_icon.pack(pady=(14, 6))

        lbl_desc = ctk.CTkLabel(
            card,
            text=f"Aplikasi belum dapat menjangkau tautan pembaruan atau link belum diatur.\n\nLink saat ini:\n{url}",
            font=ctk.CTkFont(size=11),
            wraplength=400,
            justify="center"
        )
        lbl_desc.pack(padx=14, pady=(0, 14))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 8))

        btn_settings = ctk.CTkButton(
            btn_row,
            text="⚙️ Ganti / Atur URL Update",
            width=170,
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.show_update_settings_dialog
        )
        btn_settings.pack(side="left")

        btn_ok = ctk.CTkButton(
            btn_row,
            text="Tutup",
            width=90,
            height=32,
            fg_color="#424242",
            hover_color="#616161",
            font=ctk.CTkFont(size=11),
            command=dialog.destroy
        )
        btn_ok.pack(side="right")

    def show_update_settings_dialog(self):
        """Dialog untuk melihat atau mengubah URL sumber update (version.json)."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Pengaturan Sumber Pembaruan")
        dialog.geometry("520x290")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 260
            y = self.winfo_y() + (self.winfo_height() // 2) - 145
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        card = ctk.CTkFrame(dialog, corner_radius=10)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        lbl_title = ctk.CTkLabel(
            card,
            text="Pengaturan Link version.json",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        lbl_title.pack(anchor="w", padx=14, pady=(12, 4))

        lbl_desc = ctk.CTkLabel(
            card,
            text="Masukkan tautan URL (atau lokasi berkas version.json).\nAplikasi rekan kerja akan memeriksa link ini setiap kali mengklik 'Cek Update'.",
            font=ctk.CTkFont(size=11),
            justify="left",
            wraplength=460
        )
        lbl_desc.pack(anchor="w", padx=14, pady=(0, 10))

        current_url = self.config_mgr.get_update_check_url() or DEFAULT_UPDATE_CHECK_URL
        entry_url = ctk.CTkEntry(
            card,
            placeholder_text="https://raw.githubusercontent.com/.../version.json",
            height=34,
            font=ctk.CTkFont(size=11)
        )
        entry_url.insert(0, current_url)
        entry_url.pack(fill="x", padx=14, pady=(0, 10))

        chk_auto = ctk.CTkCheckBox(
            card,
            text="Otomatis periksa pembaruan saat aplikasi dibuka",
            font=ctk.CTkFont(size=11)
        )
        if self.config_mgr.get_auto_check_update():
            chk_auto.select()
        else:
            chk_auto.deselect()
        chk_auto.pack(anchor="w", padx=14, pady=(0, 14))

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 10))

        def _save_settings():
            new_val = entry_url.get().strip()
            self.config_mgr.set_update_check_url(new_val)
            self.config_mgr.set_auto_check_update(chk_auto.get() == 1)
            self.enqueue_log("Pengaturan Auto-Updater berhasil disimpan.", "SUCCESS")
            dialog.destroy()
            self.on_click_update_btn()

        btn_save = ctk.CTkButton(
            btn_row,
            text="💾 Simpan & Tes Cek Sekarang",
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=_save_settings
        )
        btn_save.pack(side="right")

        btn_cancel = ctk.CTkButton(
            btn_row,
            text="Batal",
            width=80,
            height=32,
            fg_color="#424242",
            hover_color="#616161",
            font=ctk.CTkFont(size=11),
            command=dialog.destroy
        )
        btn_cancel.pack(side="right", padx=(0, 8))

    # ==========================
    # QUICK FOLDERS
    # ==========================
    def open_downloads_folder(self):
        dl_dir, _ = get_windows_directories()
        if os.path.exists(dl_dir):
            os.startfile(dl_dir)

    def open_screenshots_folder(self):
        _, ss_dir = get_windows_directories()
        if os.path.exists(ss_dir):
            os.startfile(ss_dir)

    # ==========================
    # SYSTEM TRAY (pystray)
    # ==========================
    def _init_system_tray(self):
        icon_image = create_tray_icon_image()
        menu = self._build_tray_menu()

        self.tray_icon = pystray.Icon(
            "AutoDriveEkinPPUK",
            icon_image,
            "AutoDrive Ekin PPUK",
            menu
        )
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()

    def _build_tray_menu(self):
        h = self.config_mgr.get_hierarchy()
        target_info = h.get("kegiatan_name") or "Standby / Belum Ditentukan"
        return pystray.Menu(
            pystray.MenuItem("Tampilkan Jendela", self.show_from_tray, default=True),
            pystray.MenuItem(f"Kegiatan: {target_info}", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Keluar", self.quit_application)
        )

    def _update_tray_menu(self):
        if self.tray_icon:
            self.tray_icon.menu = self._build_tray_menu()

    def hide_to_tray(self):
        self.withdraw()
        self.enqueue_log("Aplikasi diminimalkan ke Windows System Tray.", "INFO")

    def show_from_tray(self, icon=None, item=None):
        self.after(0, self._restore_window)

    def _restore_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_application(self, icon=None, item=None):
        self.watcher.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        if self.single_instance_lock:
            self.single_instance_lock.release()
        self.after(0, self.destroy)
        sys.exit(0)


if __name__ == "__main__":
    lock = SingleInstanceLock()
    if lock.check_and_prevent_duplicate():
        import tkinter as tk
        from tkinter import messagebox
        root_temp = tk.Tk()
        root_temp.withdraw()
        messagebox.showinfo(
            "AutoDrive Ekin PPUK Sudah Berjalan",
            "Aplikasi AutoDrive Ekin PPUK sudah aktif berjalan di latar belakang (System Tray).\n\n"
            "Silakan periksa ikon bintang Perpusnas di pojok kanan bawah taskbar Windows Anda untuk membukanya."
        )
        root_temp.destroy()
        sys.exit(0)

    app = AutoDriveApp(single_instance_lock=lock)
    app.mainloop()
