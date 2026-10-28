"""
image_processor.py - Modul Pemrosesan Gambar (Watermark & Auto-Rename Laporan)
Menambahkan cap tanggal/waktu & nama kegiatan semi-transparan pada screenshot
serta memformat nama file agar rapi dan standar untuk laporan.
"""

import os
import re
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}


def is_image_file(file_path: str) -> bool:
    """Memeriksa apakah file adalah gambar berdasarkan ekstensi."""
    _, ext = os.path.splitext(file_path.lower())
    return ext in IMAGE_EXTENSIONS


def sanitize_filename_part(text: str, max_len: int = 40) -> str:
    """Membersihkan teks agar aman digunakan sebagai nama file Windows."""
    clean = re.sub(r'[\\/*?:"<>|]', '', text)
    clean = re.sub(r'\s+', '_', clean.strip())
    return clean[:max_len]


def generate_report_filename(original_filename: str, kegiatan_name: str) -> str:
    """
    Menghasilkan nama file laporan terstandarisasi:
    Format: YYYY-MM-DD_[Nama_Kegiatan]_[Timestamp/NamaAsli].ext
    Contoh: 2026-10-28_Bimtek_Pelayanan_130522.png
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M%S")
    
    clean_kegiatan = sanitize_filename_part(kegiatan_name) or "Kegiatan"
    name_without_ext, ext = os.path.splitext(original_filename)

    # Jika nama asli adalah format default screenshot Windows (e.g. Screenshot (1) / Tangkapan layar)
    if "screenshot" in name_without_ext.lower() or "tangkapan layar" in name_without_ext.lower():
        new_name = f"{date_str}_{clean_kegiatan}_{time_str}{ext}"
    else:
        clean_orig = sanitize_filename_part(name_without_ext, max_len=25)
        new_name = f"{date_str}_{clean_kegiatan}_{clean_orig}{ext}"

    return new_name


def add_watermark(image_path: str, kegiatan_name: str, rk_name: str = "") -> bool:
    """
    Menambahkan badge watermark profesional di sudut kanan bawah screenshot.
    Berisi:
    - Baris 1: 📅 Tanggal & Jam (WIB)
    - Baris 2: 🎯 Nama Kegiatan (dan Rencana Kinerja)
    """
    try:
        with Image.open(image_path) as img:
            # Konversi ke RGBA agar mendukung transparansi halus
            orig_mode = img.mode
            img_rgba = img.convert("RGBA")
            width, height = img_rgba.size

            # Buat layer transparan untuk watermark
            watermark_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(watermark_layer)

            # Tentukan ukuran font proporsional terhadap resolusi gambar
            font_size = max(13, int(width / 75))
            try:
                # Gunakan font bawaan Windows (Segoe UI / Arial) jika tersedia
                font_bold = ImageFont.truetype("segoeuib.ttf", font_size)
                font_regular = ImageFont.truetype("segoeui.ttf", max(11, font_size - 2))
            except Exception:
                try:
                    font_bold = ImageFont.truetype("arialbd.ttf", font_size)
                    font_regular = ImageFont.truetype("arial.ttf", max(11, font_size - 2))
                except Exception:
                    font_bold = ImageFont.load_default()
                    font_regular = ImageFont.load_default()

            # Susun teks watermark berstempel resmi Perpusnas
            now_str = datetime.now().strftime("%d %b %Y, %H:%M:%S")
            line1 = f"🏛️ PERPUSNAS RI • {now_str} WIB"
            line2 = f"🎯 {kegiatan_name[:45]}"
            if rk_name and len(kegiatan_name) < 25:
                line2 += f" | {rk_name[:20]}"

            # Hitung dimensi teks
            bbox1 = draw.textbbox((0, 0), line1, font=font_bold)
            bbox2 = draw.textbbox((0, 0), line2, font=font_regular)

            w1, h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
            w2, h2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]

            badge_width = max(w1, w2) + 24
            badge_height = h1 + h2 + 20

            # Posisi badge: Pojok kanan bawah dengan margin 16px
            margin = 16
            x1 = width - badge_width - margin
            y1 = height - badge_height - margin
            x2 = width - margin
            y2 = height - margin

            # Pastikan posisi tidak minus pada gambar sangat kecil
            if x1 < 0 or y1 < 0:
                x1, y1 = 4, 4
                x2, y2 = min(width - 4, badge_width + 4), min(height - 4, badge_height + 4)

            # Gambar badge latar belakang kapsul slate modern semi-transparan
            # dengan garis tepi halus agar nyaman di mata dan terbaca tajam
            draw.rounded_rectangle(
                [x1, y1, x2, y2],
                radius=8,
                fill=(24, 24, 27, 215),
                outline=(82, 82, 91, 220),
                width=1
            )

            # Gambar teks putih & silver tenang
            text_x = x1 + 12
            text_y1 = y1 + 8
            draw.text((text_x, text_y1), line1, fill=(250, 250, 250, 245), font=font_bold)

            text_y2 = text_y1 + h1 + 5
            draw.text((text_x, text_y2), line2, fill=(212, 212, 216, 245), font=font_regular)

            # Gabungkan gambar asli dengan layer watermark
            final_img = Image.alpha_composite(img_rgba, watermark_layer)

            # Simpan kembali
            if orig_mode in ("RGB", "L"):
                final_img = final_img.convert(orig_mode)

            final_img.save(image_path)
            return True

    except Exception as e:
        print(f"[ImageProcessor Error] Gagal menambahkan watermark: {e}")
        return False
