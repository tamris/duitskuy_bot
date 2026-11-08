# Spesifikasi Teknis: Bot Telegram Pencatatan Keuangan Pribadi (Super Lengkap & Simple)

Dokumen ini adalah *blueprint* komprehensif untuk AI Agent di **Antigravity IDE** dalam membangun Bot Telegram pencatatan keuangan pribadi yang ringan, terstruktur, dan dilengkapi fitur AI Vision (OCR Struk).

---

## 1. Ringkasan Sistem & Tech Stack
* **Tujuan:** Asisten keuangan pribadi via Telegram yang cepat, *effortless*, dan menyajikan informasi ringkas.
* **Bahasa Pemrograman:** Python 3.x
* **Framework Telegram:** `aiogram` (Versi 3.x, Asynchronous)
* **Database:** SQLite (`finance.db`) — lokal, *zero-config*, cepat, dan mudah di-backup.
* **AI Vision / OCR:** Google GenAI SDK (`google-genai` dengan model `gemini-2.5-flash`) untuk membaca foto struk belanja secara presisi.

---

## 2. Struktur Direktori Proyek
AI Agent harus membuat struktur folder berikut di dalam project Antigravity IDE:
```text
telegram-finance-bot/
│
├── .env                  # Menyimpan TOKEN_TELEGRAM dan GEMINI_API_KEY
├── requirements.txt      # Daftar dependency (aiogram, google-genai, python-dotenv)
├── database.py           # Logika koneksi dan inisialisasi SQLite
├── models.py             # Skema tabel & fungsi query database
├── handlers.py           # Logika command, parsing teks, dan handling foto struk
└── main.py               # Entry point untuk menjalankan bot (polling)
```

---

## 3. Skema Database SQLite (`database.py` / Skema SQL)

Database terdiri dari 3 tabel utama untuk mendukung pencatatan dompet, transaksi, dan kategori:

```sql
-- 1. Tabel Dompet / Akun (Contoh: Cash, BCA, Bybit, Bibit)
CREATE TABLE IF NOT EXISTS wallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    balance REAL DEFAULT 0
);

-- 2. Tabel Kategori Transaksi
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    type TEXT CHECK(type IN ('IN', 'OUT')) NOT NULL
);

-- 3. Tabel Transaksi Utama
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_id INTEGER,
    type TEXT CHECK(type IN ('IN', 'OUT')) NOT NULL,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (wallet_id) REFERENCES wallets(id)
);
```

---

## 4. Spesifikasi Fitur & Fungsionalitas

### A. Perintah Dasar & Navigasi (`/start`)
* Mengirimkan pesan sambutan interaktif yang menjelaskan cara penggunaan singkat:
  * Catat teks cepat: `-25000 kopi` atau `+1500000 gaji`
  * Kirim foto struk belanja untuk dibaca otomatis oleh AI.
  * Command rekap: `/rekap`, `/saldo`, `/export`.

### B. Pencatatan Teks Kilat (*Smart Text Parsing*)
* Menggunakan regex untuk mendeteksi format pesan masuk secara instan:
  * Format keluar: `- [nominal] [keterangan]` (Contoh: `-25000 ngopi`)
  * Format masuk: `+ [nominal] [keterangan]` (Contoh: `+500000 bonus`)
* Menyimpan data secara otomatis ke tabel `transactions` dengan kategori default `"Umum"` atau memicu *Inline Keyboard* pemilihan kategori interaktif jika diinginkan.
* Memberikan balasan konfirmasi instan yang rapi dan ringkas.

### C. Pembacaan Foto Struk via AI Vision (`handlers.py`)
* Ketika user mengirimkan foto (`F.photo`), bot mengunduh file gambar resolusi tertinggi.
* Mengirimkan *byte* gambar ke Google Gemini (`gemini-2.5-flash`) dengan instruksi (*prompt*):
  > *"Ekstrak data dari struk belanja ini ke format JSON dengan key: merchant (nama toko), total (angka nominal murni tanpa titik/koma), kategori (contoh: Belanja Bulanan / Makanan / Utilitas), items (list barang)."*
* Mem-parsing hasil respons JSON dari AI, memasukkannya ke database SQLite secara otomatis, dan memberikan ringkasan singkat ke chat Telegram.

### D. Rekap & Laporan Keuangan (`/rekap`)
* Menghitung total pemasukan (`IN`) dan pengeluaran (`OUT`) bulan berjalan.
* Menghitung selisih bersih (*Net Cash Flow* = Pemasukan - Pengeluaran).
* Menyajikan laporan dengan format teks yang bersih, menggunakan garis pemisah, dan format angka ber-separator (`Rp 1.500.000`).

---

## 5. Konfigurasi `requirements.txt`
AI Agent wajib memastikan pustaka berikut terinstal:
```text
aiogram>=3.0.0
google-genai
python-dotenv
```

---

## 6. Panduan Eksekusi untuk AI Agent di Antigravity IDE
1. Buat file `.env` dan isi variabel berikut:
   ```env
   TELEGRAM_TOKEN=masukkan_token_botfather_disini
   GEMINI_API_KEY=masukkan_api_key_gemini_disini
   ```
2. Inisialisasi struktur modular (`database.py`, `models.py`, `handlers.py`, `main.py`).
3. Pastikan penanganan *error handling* (`try-except`) aktif pada parsing teks dan pembacaan API Vision agar bot tidak *crash* jika user mengirim format yang salah atau foto buram.
4. Jalankan bot menggunakan perintah terminal: `python main.py`.