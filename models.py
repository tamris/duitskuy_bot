import datetime
import re
from database import get_db_connection

def format_rupiah(amount: float) -> str:
    """Format angka float/int menjadi format mata uang Rupiah (contoh: Rp 25.000)."""
    is_negative = amount < 0
    abs_amount = abs(amount)
    formatted = f"{abs_amount:,.0f}".replace(",", ".")
    if is_negative:
        return f"-Rp {formatted}"
    return f"Rp {formatted}"

def get_default_wallet():
    """Mengambil dompet bawaan (default Cash atau wallet pertama)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wallets ORDER BY id ASC LIMIT 1;")
    wallet = cursor.fetchone()
    conn.close()
    if wallet:
        return dict(wallet)
    
    # Jika tabel dompet kosong, buat dompet default 'Cash'
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO wallets (name, balance) VALUES (?, ?);", ("Cash", 0.0))
    conn.commit()
    cursor.execute("SELECT * FROM wallets WHERE name = 'Cash';")
    wallet = cursor.fetchone()
    conn.close()
    return dict(wallet)

def get_all_wallets():
    """Mengambil seluruh data dompet dan saldo saat ini."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wallets ORDER BY id ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# Kamus singkatan populer untuk bank & e-wallet di Indonesia
WALLET_ALIASES = {
    "gpy": "Gopay",
    "gopay": "Gopay",
    "go-pay": "Gopay",
    "spay": "ShopeePay",
    "shopeepay": "ShopeePay",
    "shopee": "ShopeePay",
    "ovo": "OVO",
    "dna": "DANA",
    "dana": "DANA",
    "jg": "Jago",
    "jago": "Jago",
    "bankjago": "Jago",
    "csh": "Cash",
    "cash": "Cash",
    "tunai": "Cash",
    "bca": "BCA",
    "bri": "BRI",
    "bni": "BNI",
    "cimb": "CIMB",
    "mdr": "Mandiri",
    "mandiri": "Mandiri",
    "bsi": "BSI",
    "sea": "SeaBank",
    "seabank": "SeaBank",
    "bibit": "Bibit",
    "bybit": "Bybit",
    "pintu": "Pintu",
    "tokocrypto": "Tokocrypto"
}

def resolve_wallet_name(query: str) -> str:
    """Mengubah singkatan (seperti gpy, spay, jg) menjadi nama standar atau nama aslinya."""
    q = query.strip().lower()
    return WALLET_ALIASES.get(q, query.strip())

def get_wallet_by_name(name: str):
    """Mencari dompet berdasarkan nama atau singkatannya (case-insensitive)."""
    if not name:
        return None
    q = name.strip().lower()
    canonical = WALLET_ALIASES.get(q, q).lower()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wallets WHERE LOWER(name) = ? OR LOWER(name) = ?;", (q, canonical))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_wallet_by_id(wallet_id: int):
    """Mencari dompet berdasarkan ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wallets WHERE id = ?;", (wallet_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def extract_wallet_from_text(description: str):
    """
    Mendeteksi apakah terdapat nama dompet atau alias singkatannya pada teks transaksi.
    Mengembalikan tuple: (wallet_dict, clean_description).
    """
    wallets = get_all_wallets()
    
    for w in wallets:
        w_name_lower = w["name"].lower()
        # Kumpulkan semua alias atau singkatan yang merujuk ke dompet ini
        aliases_to_check = [w_name_lower]
        for alias, target in WALLET_ALIASES.items():
            if target.lower() == w_name_lower and alias != w_name_lower:
                aliases_to_check.append(alias)
                
        for kw in aliases_to_check:
            pattern = re.compile(rf'(?:^|\s|\[|\(|\#){re.escape(kw)}(?:$|\s|\]|\))', re.IGNORECASE)
            if pattern.search(description):
                clean_desc = pattern.sub(' ', description)
                clean_desc = re.sub(r'\s+', ' ', clean_desc).strip()
                clean_desc = re.sub(r'^[\[\(\#\]\)]+|[\[\(\#\]\)]+$', '', clean_desc).strip()
                return w, (clean_desc if clean_desc else w["name"])
                
    return get_default_wallet(), description.strip()

def add_wallet(name: str, initial_balance: float = 0.0):
    """Menambahkan dompet baru jika belum ada."""
    clean_name = resolve_wallet_name(name)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO wallets (name, balance) VALUES (?, ?);", (clean_name, initial_balance))
        conn.commit()
        wallet_id = cursor.lastrowid
        conn.close()
        return {"id": wallet_id, "name": clean_name, "balance": initial_balance}
    except Exception:
        conn.close()
        return None

def delete_wallet(wallet_id: int) -> bool:
    """Menghapus dompet berdasarkan ID. Dompet default (Cash) tidak bisa dihapus."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wallets WHERE id = ?;", (wallet_id,))
    w = cursor.fetchone()
    if not w or w["name"].lower() == "cash":
        conn.close()
        return False

    # Alihkan transaksi yang ada di dompet ini ke Cash agar history tidak hilang
    cursor.execute("SELECT id FROM wallets WHERE LOWER(name) = 'cash' LIMIT 1;")
    cash_wallet = cursor.fetchone()
    if cash_wallet:
        cursor.execute("UPDATE transactions SET wallet_id = ? WHERE wallet_id = ?;", (cash_wallet["id"], wallet_id))

    cursor.execute("DELETE FROM wallets WHERE id = ?;", (wallet_id,))
    conn.commit()
    conn.close()
    return True

def set_wallet_balance(wallet_id: int, new_balance: float) -> bool:
    """Mengubah / mengoreksi saldo dompet secara manual."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE wallets SET balance = ? WHERE id = ?;", (new_balance, wallet_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def detect_category(description: str, tx_type: str) -> str:
    """Deteksi otomatis kategori berdasarkan kata kunci di deskripsi transaksi."""
    desc_lower = description.lower()
    
    if tx_type == "IN":
        if any(w in desc_lower for w in ["gaji", "salary", "payday", "payroll", "honor", "upah", "slip"]):
            return "Gaji"
        if any(w in desc_lower for w in ["bonus", "thr", "hadiah", "reward", "tips", "angpao", "giveaway"]):
            return "Bonus & Hadiah"
        if any(w in desc_lower for w in ["dividen", "saham", "crypto", "profit", "cuan", "bunga", "reksadana", "investasi"]):
            return "Investasi"
        return "Pemasukan Lain"
    
    # OUT categories
    if any(w in desc_lower for w in [
        "kopi", "coffee", "makan", "lunch", "dinner", "sarapan", "nasi", "mie", "bakso",
        "ayam", "sate", "resto", "cafe", "kafe", "jajan", "snack", "roti", "haus", "teh", "minum"
    ]):
        return "Makanan & Minuman"
    
    if any(w in desc_lower for w in [
        "indomaret", "alfamart", "supermarket", "pasar", "sayur", "sabun", "shampoo",
        "odol", "tisu", "minyak", "beras", "belanja", "hypermart", "superindo"
    ]):
        return "Belanja Bulanan"
    
    if any(w in desc_lower for w in [
        "bensin", "pertalite", "pertamax", "solar", "spbu", "grab", "gojek", "ojol",
        "maxim", "parkir", "tol", "kereta", "krl", "mrt", "bus", "tiket"
    ]):
        return "Transportasi"
    
    if any(w in desc_lower for w in [
        "paylater", "spaylater", "gopaylater", "kredivo", "akulaku", "indodana",
        "kartu kredit", "credit card", "cc", "cicilan", "angsuran", "kpr", "leasing",
        "pinjol", "pinjaman", "pay later", "utang", "hutang"
    ]):
        return "Cicilan & Hutang"

    if any(w in desc_lower for w in [
        "tagihan", "listrik", "pln", "air", "pdam", "gas", "wifi", "indihome", "biznet", "myrepublic",
        "firstmedia", "pulsa", "kuota", "paket data", "bpjs", "iuran", "kontrakan", "kos", "sewa",
        "pajak", "pbb", "stnk", "asuransi", "ipl", "maintenance", "langganan", "subscription", "bill"
    ]):
        return "Utilitas & Tagihan"
    
    if any(w in desc_lower for w in [
        "game", "steam", "topup", "mlbb", "genshin", "ff", "bioskop", "cinema",
        "xxi", "nonton", "netflix", "spotify", "youtube", "konser", "hobi"
    ]):
        return "Hiburan & Hobi"
    
    if any(w in desc_lower for w in [
        "obat", "dokter", "apotek", "vitamin", "klinik", "rs", "rumah sakit",
        "periksa", "panadol", "bodrex"
    ]):
        return "Kesehatan"
        
    return "Umum"

def add_transaction(
    wallet_id: int,
    tx_type: str,
    amount: float,
    category: str,
    description: str = "",
    date_str: str = None
) -> dict:
    """
    Menyimpan transaksi ke tabel transactions dan memperbarui saldo dompet terkait.
    tx_type: 'IN' atau 'OUT'
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Pastikan wallet valid, jika tidak pakai wallet default
    cursor.execute("SELECT * FROM wallets WHERE id = ?;", (wallet_id,))
    wallet = cursor.fetchone()
    if not wallet:
        cursor.execute("SELECT * FROM wallets ORDER BY id ASC LIMIT 1;")
        wallet = cursor.fetchone()
        wallet_id = wallet["id"]

    # Simpan transaksi
    if date_str:
        cursor.execute("""
            INSERT INTO transactions (wallet_id, type, amount, category, description, date)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (wallet_id, tx_type, amount, category, description, date_str))
    else:
        cursor.execute("""
            INSERT INTO transactions (wallet_id, type, amount, category, description)
            VALUES (?, ?, ?, ?, ?);
        """, (wallet_id, tx_type, amount, category, description))

    tx_id = cursor.lastrowid

    # Update saldo dompet
    if tx_type == "IN":
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE id = ?;", (amount, wallet_id))
    else:
        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE id = ?;", (amount, wallet_id))

    # Ambil saldo terbaru dompet
    cursor.execute("SELECT * FROM wallets WHERE id = ?;", (wallet_id,))
    updated_wallet = cursor.fetchone()

    conn.commit()
    conn.close()

    return {
        "id": tx_id,
        "wallet_id": wallet_id,
        "wallet_name": updated_wallet["name"],
        "type": tx_type,
        "amount": amount,
        "category": category,
        "description": description,
        "new_balance": updated_wallet["balance"]
    }

def get_monthly_rekap(year: int = None, month: int = None) -> dict:
    """
    Menghitung total pemasukan, pengeluaran, dan net cash flow untuk bulan tertentu.
    Jika tidak ditentukan, menggunakan bulan dan tahun saat ini.
    """
    now = datetime.datetime.now()
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month

    # Format YYYY-MM
    month_prefix = f"{target_year:04d}-{target_month:02d}"

    conn = get_db_connection()
    cursor = conn.cursor()

    # Query total pemasukan & pengeluaran
    cursor.execute("""
        SELECT 
            type,
            COALESCE(SUM(amount), 0) as total,
            COUNT(*) as count
        FROM transactions 
        WHERE strftime('%Y-%m', date) = ?
        GROUP BY type;
    """, (month_prefix,))
    
    totals = {"IN": 0.0, "OUT": 0.0, "count_in": 0, "count_out": 0}
    for row in cursor.fetchall():
        if row["type"] == "IN":
            totals["IN"] = float(row["total"])
            totals["count_in"] = int(row["count"])
        elif row["type"] == "OUT":
            totals["OUT"] = float(row["total"])
            totals["count_out"] = int(row["count"])

    # Query rincian pengeluaran per kategori
    cursor.execute("""
        SELECT 
            category,
            SUM(amount) as total,
            COUNT(*) as count
        FROM transactions
        WHERE strftime('%Y-%m', date) = ? AND type = 'OUT'
        GROUP BY category
        ORDER BY total DESC;
    """, (month_prefix,))
    out_categories = [dict(row) for row in cursor.fetchall()]

    # Query rincian pemasukan per kategori
    cursor.execute("""
        SELECT 
            category,
            SUM(amount) as total,
            COUNT(*) as count
        FROM transactions
        WHERE strftime('%Y-%m', date) = ? AND type = 'IN'
        GROUP BY category
        ORDER BY total DESC;
    """, (month_prefix,))
    in_categories = [dict(row) for row in cursor.fetchall()]

    conn.close()

    total_in = totals["IN"]
    total_out = totals["OUT"]
    net_flow = total_in - total_out

    return {
        "year": target_year,
        "month": target_month,
        "month_name": now.strftime("%B") if (year is None and month is None) else f"Bulan {target_month:02d}",
        "total_in": total_in,
        "total_out": total_out,
        "net_flow": net_flow,
        "count_in": totals["count_in"],
        "count_out": totals["count_out"],
        "out_categories": out_categories,
        "in_categories": in_categories
    }

def delete_transaction(tx_id: int) -> bool:
    """Menghapus transaksi berdasarkan ID dan mengembalikan saldo dompet."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE id = ?;", (tx_id,))
    tx = cursor.fetchone()
    if not tx:
        conn.close()
        return False
    
    wallet_id = tx["wallet_id"]
    tx_type = tx["type"]
    amount = tx["amount"]

    # Kembalikan saldo dompet
    if tx_type == "IN":
        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE id = ?;", (amount, wallet_id))
    else:
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE id = ?;", (amount, wallet_id))

    cursor.execute("DELETE FROM transactions WHERE id = ?;", (tx_id,))
    conn.commit()
    conn.close()
    return True

def switch_transaction_wallet(tx_id: int):
    """
    Memindahkan transaksi ke dompet lain (misal dari Cash ke Jago atau sebaliknya),
    menyesuaikan saldo kedua dompet, dan mengembalikan info dompet baru.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE id = ?;", (tx_id,))
    tx = cursor.fetchone()
    if not tx:
        conn.close()
        return None
    
    current_wallet_id = tx["wallet_id"]
    tx_type = tx["type"]
    amount = tx["amount"]

    cursor.execute("SELECT * FROM wallets ORDER BY id ASC;")
    all_wallets = cursor.fetchall()
    if len(all_wallets) < 2:
        conn.close()
        return None

    # Cari dompet tujuan berikutnya yang berbeda dengan dompet saat ini
    next_wallet = None
    for w in all_wallets:
        if w["id"] != current_wallet_id:
            next_wallet = w
            break

    if not next_wallet:
        conn.close()
        return None

    new_wallet_id = next_wallet["id"]

    # Revert saldo dompet lama
    if tx_type == "IN":
        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE id = ?;", (amount, current_wallet_id))
    else:
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE id = ?;", (amount, current_wallet_id))

    # Apply saldo ke dompet baru
    if tx_type == "IN":
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE id = ?;", (amount, new_wallet_id))
    else:
        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE id = ?;", (amount, new_wallet_id))

    # Update transaksi
    cursor.execute("UPDATE transactions SET wallet_id = ? WHERE id = ?;", (new_wallet_id, tx_id))
    
    # Ambil saldo terbaru dompet baru
    cursor.execute("SELECT balance FROM wallets WHERE id = ?;", (new_wallet_id,))
    new_balance = cursor.fetchone()["balance"]

    conn.commit()
    conn.close()

    return {
        "new_wallet_id": new_wallet_id,
        "new_wallet_name": next_wallet["name"],
        "new_balance": new_balance
    }

def toggle_transaction_type(tx_id: int):
    """
    Mengubah tipe transaksi antara IN (Pemasukan) dan OUT (Pengeluaran),
    menyesuaikan saldo dompet terkait, dan mengembalikan info transaksi baru.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions WHERE id = ?;", (tx_id,))
    tx = cursor.fetchone()
    if not tx:
        conn.close()
        return None

    wallet_id = tx["wallet_id"]
    current_type = tx["type"]
    amount = tx["amount"]
    desc = tx["description"] or ""

    if current_type == "OUT":
        new_type = "IN"
        # Menghapus efek OUT (+amount) dan menambah efek IN (+amount) = + 2 * amount
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE id = ?;", (amount * 2, wallet_id))
        new_category = detect_category(desc, "IN")
    else:
        new_type = "OUT"
        # Menghapus efek IN (-amount) dan menambah efek OUT (-amount) = - 2 * amount
        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE id = ?;", (amount * 2, wallet_id))
        new_category = detect_category(desc, "OUT")

    cursor.execute("""
        UPDATE transactions 
        SET type = ?, category = ? 
        WHERE id = ?;
    """, (new_type, new_category, tx_id))

    cursor.execute("SELECT balance, name FROM wallets WHERE id = ?;", (wallet_id,))
    w = cursor.fetchone()
    new_balance = w["balance"]
    wallet_name = w["name"]

    conn.commit()
    conn.close()

    return {
        "tx_id": tx_id,
        "new_type": new_type,
        "new_category": new_category,
        "amount": amount,
        "wallet_name": wallet_name,
        "new_balance": new_balance,
        "description": desc
    }

def get_recent_transactions(limit: int = 10) -> list:
    """Mengambil transaksi terbaru dengan join tabel wallets untuk mendapatkan nama dompet."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            t.id,
            t.wallet_id,
            w.name as wallet_name,
            t.type,
            t.amount,
            t.category,
            t.description,
            t.date
        FROM transactions t
        LEFT JOIN wallets w ON t.wallet_id = w.id
        ORDER BY t.date DESC, t.id DESC
        LIMIT ?;
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_transactions_for_export() -> list:
    """Mengambil seluruh data transaksi untuk keperluan ekspor file."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            t.id,
            t.date,
            w.name as wallet_name,
            t.type,
            t.amount,
            t.category,
            COALESCE(t.description, '') as description
        FROM transactions t
        LEFT JOIN wallets w ON t.wallet_id = w.id
        ORDER BY t.date ASC, t.id ASC;
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# --- API KEY MANAGEMENT (GEMINI MULTI-KEY POOL) ---

def mask_api_key(key: str) -> str:
    """Sensor API key untuk keamanan tampilan di chat Telegram."""
    if not key:
        return "None"
    k = key.strip()
    if len(k) <= 10:
        return f"{k[:3]}...{k[-2:]}"
    return f"{k[:6]}...{k[-4:]}"

def get_all_api_keys() -> list[dict]:
    """Mengambil seluruh daftar API key di database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM api_keys ORDER BY id ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_active_api_keys() -> list[dict]:
    """Mengambil API key yang aktif, diurutkan berdasarkan fail_count terendah."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM api_keys WHERE is_active = 1 ORDER BY fail_count ASC, id ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_api_key(key_value: str, label: str = "") -> dict | None:
    """Menambahkan API key baru ke database pool."""
    cleaned = key_value.strip()
    if not cleaned:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO api_keys (key_value, label, is_active, fail_count)
            VALUES (?, ?, 1, 0);
        """, (cleaned, label or f"Key #{datetime.datetime.now().strftime('%m%d')}"))
        conn.commit()
        new_id = cursor.lastrowid
        cursor.execute("SELECT * FROM api_keys WHERE id = ?;", (new_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        conn.close()
        return None

def get_api_key_by_id(key_id: int) -> dict | None:
    """Mengambil detail satu API key berdasarkan ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM api_keys WHERE id = ?;", (key_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_api_key(key_id: int) -> bool:
    """Menghapus API key dari pool."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM api_keys WHERE id = ?;", (key_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def record_api_key_usage(key_id: int, success: bool):
    """Mencatat penggunaan API key (sukses reset fail_count, gagal increment fail_count)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if success:
        cursor.execute("""
            UPDATE api_keys 
            SET last_used = CURRENT_TIMESTAMP, fail_count = 0 
            WHERE id = ?;
        """, (key_id,))
    else:
        cursor.execute("""
            UPDATE api_keys 
            SET fail_count = fail_count + 1 
            WHERE id = ?;
        """, (key_id,))
    conn.commit()
    conn.close()

def reset_database(preserve_api_keys: bool = True) -> dict:
    """
    Mereset database keuangan:
    - Menghapus semua riwayat transaksi
    - Mengembalikan saldo dompet bawaan (Cash & Jago) ke 0, menghapus dompet tambahan
    - Mereset fail_count API Key ke kondisi prima
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM transactions;")
    tx_count = cursor.fetchone()[0]

    # 1. Hapus semua riwayat transaksi
    cursor.execute("DELETE FROM transactions;")
    try:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'transactions';")
    except Exception:
        pass

    # 2. Reset dompet ke default (Cash: 0, Jago: 0)
    cursor.execute("DELETE FROM wallets WHERE name NOT IN ('Cash', 'Jago');")
    cursor.execute("UPDATE wallets SET balance = 0;")
    cursor.execute("SELECT COUNT(*) FROM wallets;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO wallets (name, balance) VALUES ('Cash', 0), ('Jago', 0);")

    # 3. Reset status API Keys ke kondisi prima
    if preserve_api_keys:
        cursor.execute("UPDATE api_keys SET fail_count = 0, last_used = NULL, is_active = 1;")
    else:
        cursor.execute("DELETE FROM api_keys;")

    conn.commit()
    conn.close()

    return {
        "deleted_transactions": tx_count,
        "wallets": ["Cash", "Jago"],
        "api_keys_preserved": preserve_api_keys
    }
