import sqlite3
import os

if os.path.exists("/data"):
    DB_PATH = "/data/finance.db"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "finance.db")

def get_db_connection():
    """Membuat koneksi ke database SQLite dengan row_factory Row untuk akses berbasis kolom."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Inisialisasi tabel dan data awal (default wallets & categories)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Tabel Dompet / Akun
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        balance REAL DEFAULT 0
    );
    """)

    # 2. Tabel Kategori Transaksi
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        type TEXT CHECK(type IN ('IN', 'OUT')) NOT NULL
    );
    """)

    # 3. Tabel Transaksi Utama
    cursor.execute("""
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
    """)

    # 4. Tabel API Keys (Gemini Multi-Key Pool)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_value TEXT UNIQUE NOT NULL,
        label TEXT,
        is_active INTEGER DEFAULT 1,
        fail_count INTEGER DEFAULT 0,
        last_used TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Inisialisasi API key dari .env jika ada dan belum terdaftar di database
    env_keys_raw = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
    if env_keys_raw:
        for k in env_keys_raw.split(","):
            cleaned_k = k.strip()
            if cleaned_k and cleaned_k != "masukkan_api_key_gemini_disini":
                cursor.execute("""
                    INSERT OR IGNORE INTO api_keys (key_value, label)
                    VALUES (?, ?);
                """, (cleaned_k, "Default (.env)"))

    # Inisialisasi wallet bawaan jika tabel wallets masih kosong
    cursor.execute("SELECT COUNT(*) FROM wallets;")
    if cursor.fetchone()[0] == 0:
        default_wallets = [
            ("Cash", 0.0),
            ("Jago", 0.0)
        ]
        cursor.executemany("INSERT INTO wallets (name, balance) VALUES (?, ?);", default_wallets)

    # Inisialisasi kategori bawaan jika tabel categories masih kosong
    cursor.execute("SELECT COUNT(*) FROM categories;")
    if cursor.fetchone()[0] == 0:
        default_categories = [
            ("Makanan & Minuman", "OUT"),
            ("Belanja Bulanan", "OUT"),
            ("Transportasi", "OUT"),
            ("Utilitas & Tagihan", "OUT"),
            ("Cicilan & Hutang", "OUT"),
            ("Hiburan & Hobi", "OUT"),
            ("Kesehatan", "OUT"),
            ("Umum", "OUT"),
            ("Gaji", "IN"),
            ("Bonus & Hadiah", "IN"),
            ("Investasi", "IN"),
            ("Pemasukan Lain", "IN")
        ]
        cursor.executemany("INSERT INTO categories (name, type) VALUES (?, ?);", default_categories)
    else:
        cursor.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?);", ("Cicilan & Hutang", "OUT"))

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database SQLite finance.db berhasil diinisialisasi!")

