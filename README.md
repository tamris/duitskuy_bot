# 🤖 Bot Telegram Pencatatan Keuangan Pribadi (AI Vision Struk Belanja)

Bot Telegram pintar untuk mencatat dan memantau keuangan harian dengan cepat (*effortless*), terstruktur, dan dilengkapi fitur **AI Vision (OCR Struk Belanja)** menggunakan **Google Gemini 2.5 Flash**.

---

## 🚀 Fitur Utama

1. **Pencatatan Kilat (*Smart Text Parsing*):**
   - Catat pengeluaran cukup dengan: `-25000 kopi` atau `-25k kopi susu`
   - Catat pemasukan cukup dengan: `+1500000 gaji` atau `+1.5jt bonus`
   - Mendukung pemisah ribuan lokal: `-25.000 makan siang`
   - Deteksi kategori otomatis berdasarkan nama transaksi.
   - Saldo dompet langsung ter-update otomatis.

2. **AI Vision Pembacaan Struk Belanja (Google Gemini 2.5 Flash):**
   - Cukup foto dan kirimkan struk fisik belanjaan Anda (Indomaret, Alfamart, restoran, supermarket, dll.).
   - AI otomatis mengekstrak:
     - Nama Toko / Merchant
     - Total Belanja
     - Kategori Transaksi
     - Daftar Barang Belanjaan & Kuantitas
   - Langsung tersimpan otomatis ke database sebagai pengeluaran.

3. **Multi-Key Pool & Round-Robin Failover (`/api`):**
   - Mendukung banyak Gemini API Key gratisan sekaligus.
   - Rotasi otomatis secara *Round-Robin* (beban kuota terbagi rata).
   - *Auto Failover*: Jika satu key limit (429 / kuota habis), bot otomatis beralih ke key cadangan berikutnya tanpa henti.
   - Tambah & hapus key langsung via chat Telegram:
     - `+api [key]` (Pesan chat otomatis dihapus seketika demi keamanan).
     - `-api [id]` (Hapus key dari pool).
     - `/api` (Monitoring status pool & tes kesehatan semua key).

4. **Rekap & Laporan Keuangan (`/rekap`):**
   - Total Pemasukan (`IN`) dan Pengeluaran (`OUT`) bulan berjalan.
   - Perhitungan *Net Cash Flow* (Arus Kas Bersih).
   - Rincian pengeluaran dan pemasukan per kategori.

4. **Monitoring Saldo Akun / Dompet (`/saldo`):**
   - Cek saldo masing-masing akun (Cash, BCA, dll.) serta total saldo keseluruhan.

5. **Riwayat Transaksi (`/transaksi`):**
   - Menampilkan daftar transaksi terbaru secara ringkas.

7. **Ekspor Laporan Excel Profesional (`/export`):**
   - Menghasilkan file Microsoft Excel (.xlsx) resmi dengan 2 lembar kerja (*Sheets*):
     - **📊 Ringkasan Eksekutif:** Kartu Finansial (KPI), Portofolio Saldo Dompet, Analisis Pengeluaran & Pemasukan per Kategori.
     - **📝 Buku Kas Transaksi:** Detail ledger seluruh transaksi, badge warna tipe (hijau/merah), auto-filter, zebra-striping, dan rumus grand total dinamis.

---

## 📁 Struktur Direktori

```text
bot_financial/
│
├── .env                  # Token bot Telegram dan Gemini API Key
├── requirements.txt      # Dependensi pustaka Python
├── database.py           # Inisialisasi & skema tabel SQLite
├── models.py             # Operasi query database & kalkulasi keuangan
├── handlers.py           # Handler pesan, command, parsing regex, dan AI Vision OCR
├── main.py               # Entry point bot Telegram (aiogram 3 polling)
└── README.md             # Petunjuk instalasi dan penggunaan
```

---

## 🛠️ Panduan Menjalankan Bot

### 1. Konfigurasi API Token di `.env`
Buka file `.env` di text editor, lalu masukkan kredensial Anda:
```env
TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
GEMINI_API_KEY=AIzaSy...
```
> *Tips:*
> - `TELEGRAM_TOKEN` didapatkan gratis dari Telegram [@BotFather](https://t.me/BotFather).
> - `GEMINI_API_KEY` didapatkan gratis dari [Google AI Studio](https://aistudio.google.com/).

### 2. Instalasi Dependensi
Jalankan di terminal:
```bash
pip install -r requirements.txt
```

### 3. Jalankan Bot
```bash
python main.py
```

