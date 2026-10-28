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
        self.configure(fg_color="#18181B")

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
        # -------------------------------------------------------------
        # 1. TOP BAR INSTITUSI (PERPUSNAS THEMED BANNER)
        # -------------------------------------------------------------
        self.top_bar = ctk.CTkFrame(
            self,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        self.top_bar.pack(fill="x", padx=16, pady=(12, 6))

        # Brand & Logo Perpusnas di Top Bar
        logo_png = get_asset_path("logo_star.png")
        if os.path.exists(logo_png):
            try:
                self.brand_logo_img = ctk.CTkImage(
                    light_image=Image.open(logo_png),
                    dark_image=Image.open(logo_png),
                    size=(24, 24)
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
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#F4F4F5"
        )
        self.lbl_app_brand.pack(side="left", padx=(14, 8), pady=8)

        # Lencana Versi di Top Bar
        self.btn_update_badge = ctk.CTkButton(
            self.top_bar,
            text=f"v{APP_VERSION}",
            width=58,
            height=26,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.on_click_update_btn
        )
        self.btn_update_badge.pack(side="left", padx=(0, 8), pady=8)

        # Tombol Panduan Cepat di Top Bar
        self.btn_tutorial_quick = ctk.CTkButton(
            self.top_bar,
            text="💡 Panduan",
            width=85,
            height=26,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.show_tutorial_dialog
        )
        self.btn_tutorial_quick.pack(side="left", padx=(0, 8), pady=8)

        # Tombol Minimize ke Tray cepat (Kanan)
        self.btn_tray_quick = ctk.CTkButton(
            self.top_bar,
            text="Sembunyikan",
            width=92,
            height=26,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            font=ctk.CTkFont(size=11),
            command=self.hide_to_tray
        )
        self.btn_tray_quick.pack(side="right", padx=(8, 14), pady=8)

        # Tombol Beralih Mode (Penuh / Ringkas)
        self.btn_toggle_mode = ctk.CTkButton(
            self.top_bar,
            text="🗗 Mode Ringkas",
            width=115,
            height=26,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.toggle_view_mode
        )
        self.btn_toggle_mode.pack(side="right", padx=(8, 0), pady=8)

        # Checkbox Always on Top mini
        self.chk_always_top = ctk.CTkCheckBox(
            self.top_bar,
            text="Melayang",
            font=ctk.CTkFont(size=11),
            width=65,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#E4E4E7",
            command=self.toggle_always_on_top
        )
        if self.config_mgr.get_always_on_top():
            self.chk_always_top.select()
        else:
            self.chk_always_top.deselect()
        self.chk_always_top.pack(side="right", padx=(12, 8), pady=8)

        # -------------------------------------------------------------
        # 2. FRAME PENGATURAN LENGKAP (Disembunyikan saat Mode Ringkas)
        # -------------------------------------------------------------
        self.frame_full_setup = ctk.CTkFrame(self, fg_color="transparent")
        # Akan di-pack saat mode penuh

        # Sub-Frame Status Bar & Login
        status_bar = ctk.CTkFrame(self.frame_full_setup, fg_color="transparent")
        status_bar.pack(fill="x", padx=16, pady=(4, 8))

        self.auth_badge = ctk.CTkLabel(
            status_bar,
            text="Memeriksa Drive...",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#14532D",
            text_color="#86EFAC",
            corner_radius=6,
            padx=12,
            pady=4
        )
        self.auth_badge.pack(side="left", padx=(0, 8))

        self.watcher_badge = ctk.CTkLabel(
            status_bar,
            text="● Watcher: Siaga",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1E3A8A",
            text_color="#93C5FD",
            corner_radius=6,
            padx=12,
            pady=4
        )
        self.watcher_badge.pack(side="left")

        self.btn_auth = ctk.CTkButton(
            status_bar,
            text="🔑 Login Drive",
            width=115,
            height=28,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.on_btn_auth_click
        )
        self.btn_auth.pack(side="right", padx=(8, 0))

        self.btn_tutorial = ctk.CTkButton(
            status_bar,
            text="📖 Panduan Lengkap",
            width=140,
            height=28,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.show_tutorial_dialog
        )
        self.btn_tutorial.pack(side="right", padx=(8, 0))

        self.btn_check_update = ctk.CTkButton(
            status_bar,
            text="🔄 Cek Update",
            width=100,
            height=28,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            font=ctk.CTkFont(size=11),
            command=self.on_click_update_btn
        )
        self.btn_check_update.pack(side="right", padx=(8, 0))

        # Sub-Frame Input Root Folder
        card_root = ctk.CTkFrame(
            self.frame_full_setup,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        card_root.pack(fill="x", padx=16, pady=6)

        row_root_top = ctk.CTkFrame(card_root, fg_color="transparent")
        row_root_top.pack(fill="x", padx=14, pady=(10, 6))

        lbl_root = ctk.CTkLabel(
            row_root_top,
            text="🏛️ Direktori Induk Arsip Digital (Root Folder):",
            font=ctk.CTkFont(weight="bold", size=12),
            text_color="#F4F4F5"
        )
        lbl_root.pack(side="left")

        self.seg_mode = ctk.CTkSegmentedButton(
            row_root_top,
            values=["☁️ Auto-Upload ke Drive", "📁 Standby (Lokal)"],
            height=28,
            font=ctk.CTkFont(size=11),
            selected_color="#2563EB",
            selected_hover_color="#1D4ED8",
            unselected_color="#3F3F46",
            unselected_hover_color="#52525B",
            command=self.on_mode_changed
        )
        current_mode = self.config_mgr.get_mode()
        self.seg_mode.set("☁️ Auto-Upload ke Drive" if current_mode == "Drive" else "📁 Standby (Lokal)")
        self.seg_mode.pack(side="right")

        row_root_input = ctk.CTkFrame(card_root, fg_color="transparent")
        row_root_input.pack(fill="x", padx=14, pady=(0, 10))

        self.entry_root_url = ctk.CTkEntry(
            row_root_input,
            placeholder_text="Tempel URL atau ID Root Folder Google Drive E-Kinerja...",
            height=34,
            font=ctk.CTkFont(size=11),
            fg_color="#18181B",
            border_color="#3F3F46",
            text_color="#F4F4F5"
        )
        self.entry_root_url.insert(0, self.config_mgr.get_root_folder_url())
        self.entry_root_url.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_load_root = ctk.CTkButton(
            row_root_input,
            text="🔄 Muat Katalog",
            width=125,
            height=34,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=self.load_root_structure_async
        )
        self.btn_load_root.pack(side="right")

        # -------------------------------------------------------------
        # 3. KARTU KATALOG BERTINGKAT (UTAMA - Tampil di Keduanya)
        # -------------------------------------------------------------
        self.card_cascade = ctk.CTkFrame(
            self,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        self.card_cascade.pack(fill="x", padx=16, pady=6)

        # Header Kartu Katalog
        row_cat_head = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_cat_head.pack(fill="x", padx=14, pady=(10, 6))
        ctk.CTkLabel(
            row_cat_head,
            text="📚 Katalog Bertingkat Bukti Kinerja:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F4F4F5"
        ).pack(side="left")

        # Level 1: Rencana Kinerja (+ Tombol Tambah Folder)
        row_rk = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_rk.pack(fill="x", padx=14, pady=5)
        ctk.CTkLabel(
            row_rk,
            text="1. 📑 Rencana Kinerja:",
            width=140,
            anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#E4E4E7"
        ).pack(side="left")

        self.btn_add_rk = ctk.CTkButton(
            row_rk,
            text="➕",
            width=34,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            corner_radius=6,
            command=self.prompt_add_rk
        )
        self.btn_add_rk.pack(side="right")

        self.combo_rk = ctk.CTkComboBox(
            row_rk,
            values=["-- Muat Root URL dahulu --"],
            height=30,
            font=ctk.CTkFont(size=11),
            fg_color="#18181B",
            button_color="#3F3F46",
            button_hover_color="#52525B",
            border_color="#3F3F46",
            corner_radius=6,
            command=self.on_rk_selected
        )
        self.combo_rk.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Level 2: Bulan (+ Tombol Tambah Folder)
        row_bulan = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_bulan.pack(fill="x", padx=14, pady=5)
        ctk.CTkLabel(
            row_bulan,
            text="2. 📅 Periode / Bulan:",
            width=140,
            anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#E4E4E7"
        ).pack(side="left")

        self.btn_add_bulan = ctk.CTkButton(
            row_bulan,
            text="➕",
            width=34,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            corner_radius=6,
            command=self.prompt_add_bulan
        )
        self.btn_add_bulan.pack(side="right")

        self.combo_bulan = ctk.CTkComboBox(
            row_bulan,
            values=["-- Pilih Rencana Kinerja --"],
            height=30,
            font=ctk.CTkFont(size=11),
            fg_color="#18181B",
            button_color="#3F3F46",
            button_hover_color="#52525B",
            border_color="#3F3F46",
            corner_radius=6,
            command=self.on_bulan_selected
        )
        self.combo_bulan.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Level 3: Nama Kegiatan (+ Tombol Tambah Folder)
        row_kegiatan = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_kegiatan.pack(fill="x", padx=14, pady=5)
        ctk.CTkLabel(
            row_kegiatan,
            text="3. 🎯 Nama Kegiatan:",
            width=140,
            anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#E4E4E7"
        ).pack(side="left")

        self.btn_add_kegiatan = ctk.CTkButton(
            row_kegiatan,
            text="➕",
            width=34,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            corner_radius=6,
            command=self.prompt_add_kegiatan
        )
        self.btn_add_kegiatan.pack(side="right")

        self.combo_kegiatan = ctk.CTkComboBox(
            row_kegiatan,
            values=["-- Pilih Bulan dahulu --"],
            height=30,
            font=ctk.CTkFont(size=11),
            fg_color="#18181B",
            button_color="#3F3F46",
            button_hover_color="#52525B",
            border_color="#3F3F46",
            corner_radius=6,
            command=self.on_kegiatan_selected
        )
        self.combo_kegiatan.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Highlight Box Sasaran Aktif
        frame_target_box = ctk.CTkFrame(
            self.card_cascade,
            fg_color="#18181B",
            corner_radius=8,
            border_width=1,
            border_color="#3F3F46"
        )
        frame_target_box.pack(fill="x", padx=14, pady=(8, 10))

        self.lbl_active_target = ctk.CTkLabel(
            frame_target_box,
            text="📍 Katalog Sasaran: [Belum Dipilih]",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#93C5FD",
            anchor="w"
        )
        self.lbl_active_target.pack(fill="x", padx=12, pady=8)

        # Baris Opsi Watermark & Auto-Rename
        row_extra_features = ctk.CTkFrame(self.card_cascade, fg_color="transparent")
        row_extra_features.pack(fill="x", padx=14, pady=(2, 10))

        self.chk_watermark = ctk.CTkCheckBox(
            row_extra_features,
            text="💧 Cap Stempel Bukti (Waktu & Kegiatan)",
            font=ctk.CTkFont(size=11),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#E4E4E7",
            command=self.toggle_watermark
        )
        if self.config_mgr.get_enable_watermark():
            self.chk_watermark.select()
        else:
            self.chk_watermark.deselect()
        self.chk_watermark.pack(side="left", padx=(0, 24))

        self.chk_auto_rename = ctk.CTkCheckBox(
            row_extra_features,
            text="🏷️ Standarisasi Nama Arsip (Auto-Rename)",
            font=ctk.CTkFont(size=11),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#E4E4E7",
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
        self.frame_log = ctk.CTkFrame(
            self,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        # Akan di-pack saat mode penuh

        row_log_head = ctk.CTkFrame(self.frame_log, fg_color="transparent")
        row_log_head.pack(fill="x", padx=14, pady=(8, 4))

        lbl_log = ctk.CTkLabel(
            row_log_head,
            text="📜 Log Sirkulasi & Preservasi Berkas (Live Monitoring):",
            font=ctk.CTkFont(weight="bold", size=11),
            text_color="#F4F4F5"
        )
        lbl_log.pack(side="left")

        btn_clear = ctk.CTkButton(
            row_log_head,
            text="🧹 Bersihkan Log",
            width=100,
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            command=self.clear_log
        )
        btn_clear.pack(side="right")

        self.txt_log = ctk.CTkTextbox(
            self.frame_log,
            font=ctk.CTkFont(family="Consolas", size=10),
            wrap="word",
            fg_color="#121214",
            border_width=1,
            border_color="#27272A",
            text_color="#E4E4E7",
            corner_radius=6
        )
        self.txt_log.pack(fill="both", expand=True, padx=14, pady=(2, 8))

        row_quick_btn = ctk.CTkFrame(self.frame_log, fg_color="transparent")
        row_quick_btn.pack(fill="x", padx=14, pady=(0, 10))

        btn_dl = ctk.CTkButton(
            row_quick_btn,
            text="📥 Buka Folder Unduhan",
            height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            command=self.open_downloads_folder
        )
        btn_dl.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_ss = ctk.CTkButton(
            row_quick_btn,
            text="📸 Buka Folder Tangkapan Layar",
            height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            command=self.open_screenshots_folder
        )
        btn_ss.pack(side="right", fill="x", expand=True, padx=(8, 0))

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
            self.card_cascade.pack(fill="x", padx=16, pady=6)

            # Perkecil ukuran jendela menjadi widget mini
            self.minsize(420, 310)
            self.geometry("440x330")
            self.btn_toggle_mode.configure(
                text="⛶ Mode Penuh",
                fg_color="#3F3F46",
                hover_color="#52525B"
            )
            self.lbl_app_brand.configure(text=" AutoDrive Ekin [Mini]")
        else:
            # Tampilkan semua komponen
            self.frame_full_setup.pack(fill="x", padx=0, pady=0, before=self.card_cascade)
            self.card_cascade.pack_forget()
            self.card_cascade.pack(fill="x", padx=16, pady=6)
            self.frame_log.pack(fill="both", expand=True, padx=16, pady=(6, 14))

            # Kembalikan ke ukuran standar yang lapang
            self.minsize(640, 750)
            self.geometry("680x810")
            self.btn_toggle_mode.configure(
                text="🗗 Mode Ringkas",
                fg_color="#3F3F46",
                hover_color="#52525B"
            )
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
        if "Drive" in value or "Auto-Upload" in value:
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
                text="📍 Status: Standby Lokal (Berkas disimpan di laptop)",
                text_color="#86EFAC"
            )
            return

        h = self.config_mgr.get_hierarchy()
        if h.get("kegiatan_id"):
            display_str = f"📍 Katalog Sasaran: {h.get('kegiatan_name')}"
            self.lbl_active_target.configure(text=display_str, text_color="#93C5FD")
        else:
            self.lbl_active_target.configure(text="📍 Katalog Sasaran: [Belum Dipilih]", text_color="#FDE68A")

    # ==========================================
    # BUAT SUBFOLDER BARU PER TINGKAT (RK, BULAN, KEGIATAN)
    # ==========================================
    def prompt_add_rk(self):
        """Menambahkan Rencana Kinerja baru langsung di bawah Root Folder."""
        root_id = extract_folder_id(self.entry_root_url.get().strip())
        if not root_id:
            self.enqueue_log("Masukkan dan muat Root Folder terlebih dahulu sebelum menambah Rencana Kinerja!", "WARNING")
            return

        dialog = ctk.CTkInputDialog(
            text="Nama Rencana Kinerja Baru (Subfolder di Root):",
            title="Tambah Rencana Kinerja Baru"
        )
        folder_name = dialog.get_input()
        if not folder_name or not folder_name.strip():
            return
        folder_name = folder_name.strip()

        def _worker():
            try:
                self.enqueue_log(f"Membuat Rencana Kinerja '{folder_name}' di Drive...", "INFO")
                created = self.drive_mgr.create_subfolder(root_id, folder_name)
                self.enqueue_log(f"Rencana Kinerja '{created.get('name')}' berhasil dibuat!", "SUCCESS")
                if root_id in self.folder_cache:
                    del self.folder_cache[root_id]
                
                # Muat ulang daftar RK dan pilih folder yang baru dibuat
                folders = self.drive_mgr.list_subfolders(root_id)
                self.folder_cache[root_id] = folders
                self.current_rk_list = folders
                names = [f["name"] for f in folders]
                
                def _update_ui():
                    self.combo_rk.configure(values=names)
                    if folder_name in names:
                        self.combo_rk.set(folder_name)
                        self.on_rk_selected(folder_name)
                self.after(0, _update_ui)
            except Exception as e:
                self.enqueue_log(f"Gagal membuat Rencana Kinerja: {e}", "ERROR")

        threading.Thread(target=_worker, daemon=True).start()

    def prompt_add_bulan(self):
        """Menambahkan folder Periode / Bulan baru di bawah Rencana Kinerja aktif."""
        rk_name = self.combo_rk.get().strip()
        rk_item = next((f for f in self.current_rk_list if f["name"] == rk_name), None)
        if not rk_item or not rk_item.get("id"):
            self.enqueue_log("Pilih Rencana Kinerja terlebih dahulu sebelum menambah Bulan!", "WARNING")
            return

        rk_id = rk_item["id"]
        dialog = ctk.CTkInputDialog(
            text=f"Nama Periode / Bulan Baru di '{rk_name}' (contoh: 10_Oktober):",
            title="Tambah Periode / Bulan Baru"
        )
        folder_name = dialog.get_input()
        if not folder_name or not folder_name.strip():
            return
        folder_name = folder_name.strip()

        def _worker():
            try:
                self.enqueue_log(f"Membuat Bulan '{folder_name}' di '{rk_name}'...", "INFO")
                created = self.drive_mgr.create_subfolder(rk_id, folder_name)
                self.enqueue_log(f"Bulan '{created.get('name')}' berhasil dibuat!", "SUCCESS")
                if rk_id in self.folder_cache:
                    del self.folder_cache[rk_id]

                # Muat ulang daftar Bulan dan pilih folder yang baru dibuat
                subfolders = self.drive_mgr.list_subfolders(rk_id)
                self.folder_cache[rk_id] = subfolders
                self.current_bulan_list = subfolders
                names = [f["name"] for f in subfolders]

                def _update_ui():
                    self.combo_bulan.configure(values=names)
                    if folder_name in names:
                        self.combo_bulan.set(folder_name)
                        self.on_bulan_selected(folder_name)
                self.after(0, _update_ui)
            except Exception as e:
                self.enqueue_log(f"Gagal membuat Bulan: {e}", "ERROR")

        threading.Thread(target=_worker, daemon=True).start()

    def prompt_add_kegiatan(self):
        """Menambahkan folder Nama Kegiatan baru di bawah Bulan aktif."""
        bulan_name = self.combo_bulan.get().strip()
        bulan_item = next((f for f in self.current_bulan_list if f["name"] == bulan_name), None)
        if not bulan_item or not bulan_item.get("id"):
            self.enqueue_log("Pilih Periode / Bulan terlebih dahulu sebelum menambah Kegiatan!", "WARNING")
            return

        bulan_id = bulan_item["id"]
        dialog = ctk.CTkInputDialog(
            text=f"Nama Kegiatan Baru di '{bulan_name}':",
            title="Tambah Kegiatan Baru"
        )
        folder_name = dialog.get_input()
        if not folder_name or not folder_name.strip():
            return
        folder_name = folder_name.strip()

        def _worker():
            try:
                self.enqueue_log(f"Membuat Kegiatan '{folder_name}' di '{bulan_name}'...", "INFO")
                created = self.drive_mgr.create_subfolder(bulan_id, folder_name)
                self.enqueue_log(f"Kegiatan '{created.get('name')}' berhasil dibuat!", "SUCCESS")
                if bulan_id in self.folder_cache:
                    del self.folder_cache[bulan_id]

                # Muat ulang daftar Kegiatan dan pilih folder yang baru dibuat
                subfolders = self.drive_mgr.list_subfolders(bulan_id)
                self.folder_cache[bulan_id] = subfolders
                self.current_kegiatan_list = subfolders
                names = [f["name"] for f in subfolders]

                def _update_ui():
                    self.combo_kegiatan.configure(values=names)
                    if folder_name in names:
                        self.combo_kegiatan.set(folder_name)
                        self.on_kegiatan_selected(folder_name)
                self.after(0, _update_ui)
            except Exception as e:
                self.enqueue_log(f"Gagal membuat Kegiatan: {e}", "ERROR")

        threading.Thread(target=_worker, daemon=True).start()

    def prompt_create_folder(self):
        """Kompatibilitas: memanggil tambah kegiatan."""
        self.prompt_add_kegiatan()

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
                level_tags = {
                    "INFO": "📘 [INFO]",
                    "SUCCESS": "📗 [SUKSES]",
                    "WARNING": "📙 [PERINGATAN]",
                    "ERROR": "📕 [GAGAL]",
                    "UPLOAD": "📤 [UNGGAH]"
                }
                lvl_str = level_tags.get(level.upper(), f"[{level}]")
                full_text = f"[{timestamp}] {lvl_str} {msg}\n"
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
                fg_color="#14532D",
                text_color="#86EFAC"
            )
        else:
            if not os.path.exists(self.drive_mgr.credentials_path):
                self.auth_badge.configure(
                    text="⚠ credentials.json Belum Ada",
                    fg_color="#451A03",
                    text_color="#FDE68A"
                )
            else:
                self.auth_badge.configure(
                    text="● Perlu Login Pertama",
                    fg_color="#451A03",
                    text_color="#FDE68A"
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
    # PANDUAN PENDAMPINGAN (TUTORIAL STEP-BY-STEP)
    # ==========================
    def show_tutorial_dialog(self):
        """Menampilkan dialog panduan interaktif step-by-step pendampingan penggunaan aplikasi."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("📖 Panduan Pendampingan - AutoDrive Ekin PPUK")
        dialog.geometry("640x590")
        dialog.minsize(600, 560)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.configure(fg_color="#18181B")

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 320
            y = self.winfo_y() + (self.winfo_height() // 2) - 295
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        # Data Langkah Tutorial
        steps_data = [
            {
                "badge": "Langkah 1 dari 6",
                "title": "🔑 Persiapan & Login Akun Google Drive",
                "tagline": "Hubungkan aplikasi ke akun Google Drive Anda sekali saja di awal.",
                "bullets": [
                    "• AutoDrive membutuhkan otorisasi akun Google Drive yang memiliki hak akses ke folder E-Kinerja tim Anda.",
                    "• Klik tombol 'Login / Tes Drive' pada bilah status di atas (atau tombol biru di bawah).",
                    "• Browser Anda akan terbuka otomatis. Pilih akun Google Anda lalu klik 'Izinkan / Allow'.",
                    "• Setelah berhasil, indikator status akan berubah menjadi hijau: '● Drive: Terhubung'.",
                    "• Anda hanya perlu login 1 kali; aplikasi mengingat sesi login Anda di masa mendatang."
                ],
                "tip": "💡 Tips: Pastikan email Google Anda sudah ditambahkan ke daftar izin akses folder E-Kinerja unit kerja.",
                "action_text": "🔑 Uji / Login Akun Drive Sekarang",
                "action_cmd": lambda: [dialog.destroy(), self.on_btn_auth_click()]
            },
            {
                "badge": "Langkah 2 dari 6",
                "title": "📁 Memilih Folder Sasaran E-Kinerja",
                "tagline": "Tentukan folder tujuan akhir upload dengan 3 level dropdown bertingkat.",
                "bullets": [
                    "• Tempelkan tautan atau ID folder induk pada kolom '🏠 Link Root Folder (Home)'.",
                    "• Klik '🔄 Muat Subfolder' untuk membaca seluruh susunan folder dari Google Drive.",
                    "• Pilih secara bertingkat: 1) Rencana Kinerja ➔ 2) Bulan ➔ 3) Nama Kegiatan.",
                    "• Nama Kegiatan yang Anda pilih merupakan folder sasaran akhir tempat file otomatis diunggah.",
                    "• Folder belum ada di Drive? Klik tombol '➕' di samping masing-masing dropdown untuk membuatnya langsung tanpa perlu membuka browser!"
                ],
                "tip": "💡 Tips: Folder yang Anda pilih otomatis disimpan. Besok saat aplikasi dibuka kembali, pilihan Anda tetap aktif.",
                "action_text": "🏠 Muat Subfolder Root",
                "action_cmd": lambda: [dialog.destroy(), self.load_root_structure_async()]
            },
            {
                "badge": "Langkah 3 dari 6",
                "title": "📸 Ambil Screenshot & Unduh Berkas Bukti",
                "tagline": "Kerjakan tugas Anda dengan tenang, AutoDrive otomatis bekerja di latar belakang.",
                "bullets": [
                    "• Mengambil Tangkapan Layar: Tekan tombol keyboard 'Win + PrtScn' atau gunakan Snipping Tool ('Win + Shift + S').",
                    "• Mengunduh Dokumen Laporan: Unduh berkas seperti Notula, Daftar Hadir, Surat Tugas dari WhatsApp Web atau browser ke folder Downloads.",
                    "• AutoDrive langsung mendeteksi berkas baru dalam hitungan detik dan mengunggahnya ke folder kegiatan di Google Drive.",
                    "• Setelah selesai diunggah, berkas lokal di laptop Anda otomatis dibersihkan agar penyimpanan laptop tidak penuh."
                ],
                "tip": "💡 Tips: Anda dapat memantau seluruh proses pengunggahan secara live pada kotak 'Riwayat Aktivitas & Log'.",
                "action_text": "📂 Buka Folder Screenshot",
                "action_cmd": lambda: self.open_screenshots_folder()
            },
            {
                "badge": "Langkah 4 dari 6",
                "title": "🏷️ Watermark Bukti & Auto-Rename Standar",
                "tagline": "Otomatisasi cap tanggal, jam presisi, dan nama file yang terstandarisasi.",
                "bullets": [
                    "• 💧 Watermark Bukti Screenshot: Setiap tangkapan layar otomatis diberi cap resmi elegan di pojok kanan bawah berisi tanggal, jam WIB presisi, serta nama kegiatan dan rencana kinerja.",
                    "• 🏷️ Format Nama File Otomatis: Mengubah nama acak seperti 'Screenshot (14).png' menjadi format resmi: YYYY-MM-DD_[Nama_Kegiatan]_[Waktu].png (contoh: '2026-10-28_Rapat_PK_134520.png').",
                    "• Untuk dokumen PDF/Word/Excel: otomatis diberi prefiks tanggal dan nama kegiatan.",
                    "• Anda bisa mengaktifkan/menonaktifkan fitur ini kapan saja melalui centang checkbox yang tersedia."
                ],
                "tip": "💡 Tips: Bukti tangkapan layar ber-watermark resmi ini sangat mempermudah verifikasi saat audit E-Kinerja BKN.",
                "action_text": "📂 Buka Folder Downloads",
                "action_cmd": lambda: self.open_downloads_folder()
            },
            {
                "badge": "Langkah 5 dari 6",
                "title": "🗗 Mode Ringkas Melayang & System Tray",
                "tagline": "Jendela mini hemat ruang layar agar tidak menutupi dokumen kerja Anda.",
                "bullets": [
                    "• Klik tombol '🗗 Mode Ringkas' di pojok kanan atas untuk mengecilkan jendela menjadi widget mini (440 x 330 px).",
                    "• Pada mode ringkas, hanya dropdown pemilihan kegiatan yang ditampilkan sehingga Anda bisa leluasa berganti target kegiatan tanpa memakan layar kerja Word/Excel.",
                    "• Centang 'Melayang' agar jendela mini selalu berada di atas jendela lain.",
                    "• Klik tombol 'Sembunyikan' atau tombol silang (X) untuk meminimalkan aplikasi ke System Tray (ikon bintang Perpusnas di taskbar kanan bawah dekat jam)."
                ],
                "tip": "💡 Tips: Untuk membuka kembali jendela dari System Tray, klik 2x atau klik kanan pada ikon bintang Perpusnas lalu pilih 'Tampilkan Jendela'.",
                "action_text": "🗗 Coba Mode Ringkas Sekarang",
                "action_cmd": lambda: [dialog.destroy(), self.toggle_view_mode()]
            },
            {
                "badge": "Langkah 6 dari 6",
                "title": "🔄 Cek Pembaruan Sistem (Auto-Updater)",
                "tagline": "Kemudahan update aplikasi untuk rekan kerja hanya dengan 1 kali klik.",
                "bullets": [
                    "• Setiap kali aplikasi dibuka, sistem otomatis mengecek apakah ada versi perbaikan baru di GitHub repositori tim.",
                    "• Jika ada pembaruan, lencana versi di pojok kiri atas otomatis berubah menjadi warna hijau: '🎉 Update!'.",
                    "• Cukup klik tombol hijau tersebut untuk melihat catatan rilis (changelog), lalu klik '⬇️ Perbarui Sekarang'.",
                    "• Aplikasi akan mengunduh paket update, memperbarui dirinya sendiri, dan membuka kembali secara otomatis.",
                    "• Seluruh data akun Google dan pilihan folder Anda dijamin tetap tersimpan aman tanpa perlu setup ulang!"
                ],
                "tip": "💡 Tips: Anda juga bisa mengecek pembaruan secara manual kapan saja dengan mengklik tombol '🔄 Cek Update'.",
                "action_text": "🔄 Cek Pembaruan Sekarang",
                "action_cmd": lambda: [dialog.destroy(), self.on_click_update_btn()]
            }
        ]

        # State Langkah Saat Ini (0 - 5)
        current_step = [0]

        # 1. Header Bar Dialog
        header_bar = ctk.CTkFrame(
            dialog,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        header_bar.pack(fill="x", padx=16, pady=(16, 10))

        lbl_top_title = ctk.CTkLabel(
            header_bar,
            text="🏛️ Panduan Pendampingan Penggunaan AutoDrive Ekin PPUK",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#F4F4F5"
        )
        lbl_top_title.pack(anchor="w", padx=14, pady=(10, 2))

        lbl_top_sub = ctk.CTkLabel(
            header_bar,
            text="Ikuti langkah-langkah mudah di bawah ini untuk memulai otomatisasi bukti kerja ke Google Drive.",
            font=ctk.CTkFont(size=11),
            text_color="#A1A1AA"
        )
        lbl_top_sub.pack(anchor="w", padx=14, pady=(0, 10))

        # 2. Step Selector Pills (1 s.d. 6)
        pill_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        pill_frame.pack(fill="x", padx=16, pady=(0, 8))

        step_buttons: List[ctk.CTkButton] = []
        short_labels = ["1. Akun", "2. Folder", "3. Upload", "4. Cap/Nama", "5. Mini Mode", "6. Update"]

        # 3. Card Konten Langkah
        card_content = ctk.CTkFrame(
            dialog,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        card_content.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        lbl_step_badge = ctk.CTkLabel(
            card_content,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2563EB",
            text_color="#FFFFFF",
            corner_radius=6,
            padx=10,
            pady=3
        )
        lbl_step_badge.pack(anchor="w", padx=16, pady=(14, 4))

        lbl_step_title = ctk.CTkLabel(
            card_content,
            text="",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#F4F4F5",
            anchor="w"
        )
        lbl_step_title.pack(fill="x", padx=16, pady=(2, 2))

        lbl_step_tagline = ctk.CTkLabel(
            card_content,
            text="",
            font=ctk.CTkFont(size=12, slant="italic"),
            text_color="#A1A1AA",
            anchor="w"
        )
        lbl_step_tagline.pack(fill="x", padx=16, pady=(0, 10))

        txt_step_bullets = ctk.CTkTextbox(
            card_content,
            height=140,
            font=ctk.CTkFont(size=11),
            fg_color="#18181B",
            border_width=1,
            border_color="#3F3F46",
            text_color="#E4E4E7",
            corner_radius=6
        )
        txt_step_bullets.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # Box Tips
        frame_tip = ctk.CTkFrame(
            card_content,
            corner_radius=8,
            fg_color="#18181B",
            border_width=1,
            border_color="#3F3F46"
        )
        frame_tip.pack(fill="x", padx=16, pady=(0, 12))

        lbl_tip = ctk.CTkLabel(
            frame_tip,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#86EFAC",
            wraplength=560,
            justify="left"
        )
        lbl_tip.pack(fill="x", padx=12, pady=8)

        # Action Button Per Langkah
        btn_action = ctk.CTkButton(
            card_content,
            text="",
            height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8"
        )
        btn_action.pack(anchor="w", padx=16, pady=(0, 14))

        # 4. Bottom Navigation Bar
        nav_bar = ctk.CTkFrame(dialog, fg_color="transparent")
        nav_bar.pack(fill="x", padx=16, pady=(0, 16))

        btn_prev = ctk.CTkButton(
            nav_bar,
            text="⬅️ Sebelumnya",
            width=110,
            height=34,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            font=ctk.CTkFont(size=11)
        )
        btn_prev.pack(side="left")

        lbl_counter = ctk.CTkLabel(
            nav_bar,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#A1A1AA"
        )
        lbl_counter.pack(side="left", expand=True)

        btn_next = ctk.CTkButton(
            nav_bar,
            text="Selanjutnya ➡️",
            width=130,
            height=34,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        btn_next.pack(side="right")

        def _render_step(idx: int):
            current_step[0] = idx
            data = steps_data[idx]

            # Update Header & Info
            lbl_step_badge.configure(text=data["badge"])
            lbl_step_title.configure(text=data["title"])
            lbl_step_tagline.configure(text=data["tagline"])

            # Update Bullets
            txt_step_bullets.configure(state="normal")
            txt_step_bullets.delete("1.0", "end")
            txt_step_bullets.insert("1.0", "\n\n".join(data["bullets"]))
            txt_step_bullets.configure(state="disabled")

            # Update Tips & Action
            lbl_tip.configure(text=data["tip"])
            btn_action.configure(text=data["action_text"], command=data["action_cmd"])

            # Update Pills
            for i, btn in enumerate(step_buttons):
                if i == idx:
                    btn.configure(fg_color="#2563EB", text_color="#FFFFFF")
                else:
                    btn.configure(fg_color="#3F3F46", text_color="#A1A1AA")

            # Update Counter & Nav Buttons
            lbl_counter.configure(text=f"Langkah {idx + 1} dari {len(steps_data)}")
            if idx == 0:
                btn_prev.configure(state="disabled")
            else:
                btn_prev.configure(state="normal")

            if idx == len(steps_data) - 1:
                btn_next.configure(
                    text="✅ Selesai & Tutup",
                    fg_color="#15803D",
                    hover_color="#16A34A",
                    command=dialog.destroy
                )
            else:
                btn_next.configure(
                    text="Selanjutnya ➡️",
                    fg_color="#2563EB",
                    hover_color="#1D4ED8",
                    command=_next_step
                )

        def _prev_step():
            if current_step[0] > 0:
                _render_step(current_step[0] - 1)

        def _next_step():
            if current_step[0] < len(steps_data) - 1:
                _render_step(current_step[0] + 1)

        btn_prev.configure(command=_prev_step)

        # Build Step Pills
        for i, s_lbl in enumerate(short_labels):
            s_btn = ctk.CTkButton(
                pill_frame,
                text=s_lbl,
                height=26,
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda step_idx=i: _render_step(step_idx)
            )
            s_btn.pack(side="left", fill="x", expand=True, padx=2)
            step_buttons.append(s_btn)

        # Tampilkan Langkah Pertama
        _render_step(0)

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
        dialog.configure(fg_color="#18181B")

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 250
            y = self.winfo_y() + (self.winfo_height() // 2) - 225
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        # Header Card
        card_header = ctk.CTkFrame(
            dialog,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        card_header.pack(fill="x", padx=16, pady=(16, 10))

        lbl_title = ctk.CTkLabel(
            card_header,
            text="✨ Versi Baru Siap Diperbarui!",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#F4F4F5"
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
            text_color="#A1A1AA"
        )
        lbl_vers.pack(anchor="w", padx=14, pady=(0, 12))

        # Changelog Card
        card_body = ctk.CTkFrame(
            dialog,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        card_body.pack(fill="both", expand=True, padx=16, pady=6)

        lbl_notes = ctk.CTkLabel(
            card_body,
            text="Catatan Perubahan & Fitur Baru (Changelog):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F4F4F5"
        )
        lbl_notes.pack(anchor="w", padx=12, pady=(10, 4))

        txt_changelog = ctk.CTkTextbox(
            card_body,
            height=130,
            font=ctk.CTkFont(size=11),
            fg_color="#18181B",
            border_width=1,
            border_color="#3F3F46",
            text_color="#E4E4E7",
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
            text_color="#93C5FD"
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
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            font=ctk.CTkFont(size=11),
            command=self.show_update_settings_dialog
        )
        btn_settings.pack(side="left")

        btn_cancel = ctk.CTkButton(
            btn_box,
            text="Nanti Saja",
            width=95,
            height=34,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
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
            fg_color="#15803D",
            hover_color="#16A34A",
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
        dialog.configure(fg_color="#18181B")

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 210
            y = self.winfo_y() + (self.winfo_height() // 2) - 110
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        card = ctk.CTkFrame(
            dialog,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)

        lbl_icon = ctk.CTkLabel(
            card,
            text="✅ Versi Terbaru",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#86EFAC"
        )
        lbl_icon.pack(pady=(16, 6))

        lbl_desc = ctk.CTkLabel(
            card,
            text=f"Anda sudah menggunakan AutoDrive Ekin PPUK versi terbaru (v{cur_v}).\nTidak ada pembaruan baru yang ditemukan.",
            font=ctk.CTkFont(size=11),
            text_color="#A1A1AA",
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
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
            font=ctk.CTkFont(size=11),
            command=self.show_update_settings_dialog
        )
        btn_settings.pack(side="left")

        btn_ok = ctk.CTkButton(
            btn_row,
            text="Tutup",
            width=90,
            height=30,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            font=ctk.CTkFont(size=11, weight="bold"),
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
        dialog.configure(fg_color="#18181B")

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 230
            y = self.winfo_y() + (self.winfo_height() // 2) - 125
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        card = ctk.CTkFrame(
            dialog,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)

        lbl_icon = ctk.CTkLabel(
            card,
            text="ℹ️ Info Pembaruan",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#FDE68A"
        )
        lbl_icon.pack(pady=(14, 6))

        lbl_desc = ctk.CTkLabel(
            card,
            text=f"Aplikasi belum dapat menjangkau tautan pembaruan atau link belum diatur.\n\nLink saat ini:\n{url}",
            font=ctk.CTkFont(size=11),
            text_color="#A1A1AA",
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
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=self.show_update_settings_dialog
        )
        btn_settings.pack(side="left")

        btn_ok = ctk.CTkButton(
            btn_row,
            text="Tutup",
            width=90,
            height=32,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
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
        dialog.configure(fg_color="#18181B")

        try:
            x = self.winfo_x() + (self.winfo_width() // 2) - 260
            y = self.winfo_y() + (self.winfo_height() // 2) - 145
            dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

        card = ctk.CTkFrame(
            dialog,
            corner_radius=10,
            fg_color="#27272A",
            border_width=1,
            border_color="#3F3F46"
        )
        card.pack(fill="both", expand=True, padx=16, pady=16)

        lbl_title = ctk.CTkLabel(
            card,
            text="Pengaturan Link version.json",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#F4F4F5"
        )
        lbl_title.pack(anchor="w", padx=14, pady=(12, 4))

        lbl_desc = ctk.CTkLabel(
            card,
            text="Masukkan tautan URL (atau lokasi berkas version.json).\nAplikasi rekan kerja akan memeriksa link ini setiap kali mengklik 'Cek Update'.",
            font=ctk.CTkFont(size=11),
            text_color="#A1A1AA",
            justify="left",
            wraplength=460
        )
        lbl_desc.pack(anchor="w", padx=14, pady=(0, 10))

        current_url = self.config_mgr.get_update_check_url() or DEFAULT_UPDATE_CHECK_URL
        entry_url = ctk.CTkEntry(
            card,
            placeholder_text="https://raw.githubusercontent.com/.../version.json",
            height=34,
            font=ctk.CTkFont(size=11),
            fg_color="#18181B",
            border_color="#3F3F46",
            text_color="#F4F4F5"
        )
        entry_url.insert(0, current_url)
        entry_url.pack(fill="x", padx=14, pady=(0, 10))

        chk_auto = ctk.CTkCheckBox(
            card,
            text="Otomatis periksa pembaruan saat aplikasi dibuka",
            font=ctk.CTkFont(size=11),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            text_color="#E4E4E7"
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
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            command=_save_settings
        )
        btn_save.pack(side="right")

        btn_cancel = ctk.CTkButton(
            btn_row,
            text="Batal",
            width=80,
            height=32,
            fg_color="#3F3F46",
            hover_color="#52525B",
            text_color="#E4E4E7",
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
            pystray.MenuItem("📖 Panduan Aplikasi", lambda: self.after(0, self.show_tutorial_dialog)),
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
