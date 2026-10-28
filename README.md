# 🏛️ AutoDrive Ekin PPUK (Perpustakaan Nasional RI)

Aplikasi desktop Windows resmi untuk mempermudah dan mempercepat pelaporan bukti kinerja (E-Kinerja) dengan struktur **Pohon Folder Google Drive Bertingkat (*Cascading Dropdowns*)**:
```text
🏠 Link Root Folder (Home)
   └── 📁 Rencana Kinerja (Dropdown 1)
       └── 📅 Bulan (Dropdown 2)
           └── 🎯 Nama Kegiatan (Dropdown 3 / Folder Sasaran Akhir)
               └── 📄 File (Download & Screenshot Otomatis Diberi Cap, Diganti Nama, & Diunggah)
```

---

## 🌟 Fitur Baru: Watermark Bukti & Auto-Rename Otomatis

1. **💧 Watermark Bukti Screenshot (Cap Tanggal & Kegiatan)**:
   - Setiap screenshot layar yang diambil (`Win + PrtScn` atau Snipping Tool) otomatis diberi cap teks elegan semi-transparan di sudut kanan bawah:
     - 📅 **Tanggal & Jam Presisi** *(Contoh: `📅 28 Okt 2026, 13:05:22 WIB`)*
     - 🎯 **Nama Kegiatan & Rencana Kinerja** *(Contoh: `🎯 Sosialisasi Standar Pelayanan`)*
   - Badge gelap semi-transparan memastikan teks **selalu terbaca jelas** di latar belakang gambar apapun (terang maupun gelap).
   - Dapat diaktifkan / dinonaktifkan kapan saja melalui checkbox `💧 Watermark Bukti`.

2. **🏷️ Auto-Rename Kegiatan Terstandarisasi**:
   - Menghilangkan nama file acak seperti `Screenshot (12).png` atau `Tangkapan layar 2026-10-28.png`.
   - Nama file yang diunggah ke Google Drive otomatis diformat rapi:
     `[YYYY-MM-DD]_[Nama_Kegiatan]_[Waktu].png`
     *(Contoh: `2026-10-28_Bimtek_Pelayanan_130522.png`)*.
   - Untuk file unduhan dokumen (PDF/Word/Excel):
     `2026-10-28_Bimtek_Pelayanan_Daftar_Hadir.pdf`.

3. **🗗 Mode Ringkas (*Mini Floating Widget*)**:
   - Jendela dapat diperkecil menjadi widget melayang mini (385 x 275 px) di sudut layar agar tidak mengganggu pengerjaan laporan di Word/Excel.
   - Mendukung kontrol *Melayang (Always on Top)* dan minimize ke *System Tray*.

---

## 🚀 Cara Menjalankan

### Versi Standalone EXE (Rekomendasi untuk Rekan Kerja)
Cukup kirimkan file **`AutoDrive_EXE_Siap_Kirim.zip`**.
Rekan kerja tinggal ekstrak dan jalankan **`AutoDrive.exe`** (tanpa butuh install Python).

### Versi Source Code (Python)
```bash
cd AutoDriveReportManager
python main.py
```
*(Atau klik ganda `run_app.bat`)*.
