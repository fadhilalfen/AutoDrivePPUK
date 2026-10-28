"""
config_manager.py - Pengelola Konfigurasi Hierarki Folder & Pengaturan
Menyimpan URL Root Folder Google Drive, hierarki terpilih (Rencana Kinerja > Bulan > Nama Kegiatan),
preferensi Always on Top, serta Mode Tampilan (Penuh / Ringkas) ke config.json.
"""

import json
import os
from typing import Dict, Any

CONFIG_FILE = "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "always_on_top": True,
    "compact_mode": False,
    "enable_auto_rename": True,
    "enable_watermark": True,
    "auto_check_update": True,
    "update_check_url": "",
    "mode": "Drive",  # "Drive" atau "Default" (Standby Lokal)
    "root_folder_url": "",
    "hierarchy": {
        "rencana_kinerja_id": "",
        "rencana_kinerja_name": "",
        "bulan_id": "",
        "bulan_name": "",
        "kegiatan_id": "",
        "kegiatan_name": ""
    }
}


class ConfigManager:
    def __init__(self, filepath: str = CONFIG_FILE):
        self.filepath = filepath
        self.config: Dict[str, Any] = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Memuat konfigurasi dari file JSON jika ada, atau buat default."""
        if not os.path.exists(self.filepath):
            self.save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
        
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                for key, val in DEFAULT_CONFIG.items():
                    if key not in data:
                        data[key] = val
                    elif isinstance(val, dict) and isinstance(data[key], dict):
                        for sub_k, sub_v in val.items():
                            if sub_k not in data[key]:
                                data[key][sub_k] = sub_v
                return data
        except Exception as e:
            print(f"[ConfigManager] Gagal membaca konfigurasi: {e}. Menggunakan default.")
            return DEFAULT_CONFIG.copy()

    def save_config(self, config_data: Dict[str, Any] = None) -> None:
        """Menyimpan konfigurasi ke file JSON."""
        if config_data is not None:
            self.config = config_data
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ConfigManager] Gagal menyimpan konfigurasi: {e}")

    # Root Folder
    def get_root_folder_url(self) -> str:
        return self.config.get("root_folder_url", "")

    def set_root_folder_url(self, url: str) -> None:
        self.config["root_folder_url"] = url.strip()
        self.save_config()

    # Mode Operasional (Drive vs Lokal Standby)
    def get_mode(self) -> str:
        return self.config.get("mode", "Drive")

    def set_mode(self, mode: str) -> None:
        self.config["mode"] = mode
        self.save_config()

    # Hierarki Folder Terpilih
    def get_hierarchy(self) -> Dict[str, str]:
        return self.config.get("hierarchy", DEFAULT_CONFIG["hierarchy"].copy())

    def set_hierarchy(self, rk_id: str, rk_name: str, bulan_id: str, bulan_name: str, kegiatan_id: str, kegiatan_name: str) -> None:
        self.config["hierarchy"] = {
            "rencana_kinerja_id": rk_id,
            "rencana_kinerja_name": rk_name,
            "bulan_id": bulan_id,
            "bulan_name": bulan_name,
            "kegiatan_id": kegiatan_id,
            "kegiatan_name": kegiatan_name
        }
        self.save_config()

    def get_target_upload_folder_id(self) -> str:
        """Mengembalikan ID folder sasaran akhir (Nama Kegiatan)."""
        hierarchy = self.get_hierarchy()
        return hierarchy.get("kegiatan_id", "")

    # Always on Top
    def get_always_on_top(self) -> bool:
        return self.config.get("always_on_top", True)

    def set_always_on_top(self, value: bool) -> None:
        self.config["always_on_top"] = bool(value)
        self.save_config()

    # Mode Tampilan Ringkas (Mini Floating Mode)
    def get_compact_mode(self) -> bool:
        return self.config.get("compact_mode", False)

    def set_compact_mode(self, value: bool) -> None:
        self.config["compact_mode"] = bool(value)
        self.save_config()

    # Opsi Watermark & Auto-Rename
    def get_enable_auto_rename(self) -> bool:
        return self.config.get("enable_auto_rename", True)

    def set_enable_auto_rename(self, value: bool) -> None:
        self.config["enable_auto_rename"] = bool(value)
        self.save_config()

    def get_enable_watermark(self) -> bool:
        return self.config.get("enable_watermark", True)

    def set_enable_watermark(self, value: bool) -> None:
        self.config["enable_watermark"] = bool(value)
        self.save_config()

    # Pengaturan Pembaruan (Auto-Updater)
    def get_update_check_url(self) -> str:
        return self.config.get("update_check_url", "")

    def set_update_check_url(self, url: str) -> None:
        self.config["update_check_url"] = url.strip()
        self.save_config()

    def get_auto_check_update(self) -> bool:
        return self.config.get("auto_check_update", True)

    def set_auto_check_update(self, val: bool) -> None:
        self.config["auto_check_update"] = bool(val)
        self.save_config()


