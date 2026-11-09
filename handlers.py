import os
import re
import io
import csv
import json
import asyncio
import logging
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)

from google import genai
from google.genai import types

import models
from excel_generator import create_financial_excel_report

logger = logging.getLogger(__name__)
router = Router()

# Regex untuk mendeteksi pencatatan kilat:
# Contoh format:
# -25000 kopi
# - 25k kopi susu
# - 1.5jt beli monitor
# +1500000 gaji
# + 500k bonus project
QUICK_ENTRY_PATTERN = re.compile(
    r"^([+-])\s*([0-9.,]+(?:\s*(?:k|rb|ribu|jt|juta|m)\b)?)\s*(.*)$",
    re.IGNORECASE
)

def escape_md(text: str) -> str:
    """Escape karakter khusus Markdown V1 untuk mencegah error parse entities."""
    if not text:
        return ""
    for ch in ["_", "*", "`", "["]:
        text = str(text).replace(ch, f"\\{ch}")
    return text

def parse_amount(raw_str: str) -> float | None:
    """Mengonversi string nominal (termasuk suffix k, rb, jt, titik/koma) menjadi float."""
    if not raw_str:
        return None
    s = raw_str.strip().lower()
    
    multiplier = 1.0
    if re.search(r'(jt|juta|m)$', s):
        multiplier = 1_000_000.0
        s = re.sub(r'(jt|juta|m)$', '', s).strip()
    elif re.search(r'(k|rb|ribu)$', s):
        multiplier = 1_000.0
        s = re.sub(r'(k|rb|ribu)$', '', s).strip()

    # Format angka lokal Indonesia:
    # Jika terdapat titik dan koma (contoh: 1.500,50 atau 1,500.50)
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    # Jika hanya ada titik dan merupakan pemisah ribuan (contoh: 25.000)
    elif '.' in s and multiplier == 1.0 and len(s.split('.')[-1]) == 3:
        s = s.replace('.', '')
    # Jika ada koma sebagai desimal (contoh: 1,5 jt)
    elif ',' in s:
        s = s.replace(',', '.')

    try:
        val = float(s) * multiplier
        return val if val > 0 else None
    except ValueError:
        return None

def parse_quick_entry(text: str):
    """
    Mengecek apakah pesan teks merupakan pencatatan transaksi:
    - Default otomatis PENGELUARAN (OUT) jika tanpa tanda (contoh: 'kopi susu 25k', 'makan siang 35.000', '25k kopi')
    - Pengeluaran eksplisit dengan minus '-' (contoh: '-25k kopi', '-25000 kopi')
    - Pemasukan eksplisit dengan plus '+' (contoh: '+1500000 gaji', '+ 500k bonus')
    """
    s = text.strip()
    if not s:
        return None

    tx_type = "OUT"  # Default otomatis pengeluaran agar pengguna tidak perlu repot mengetik '-'
    if s.startswith("+"):
        tx_type = "IN"
        s = s[1:].strip()
    elif s.startswith("-"):
        tx_type = "OUT"
        s = s[1:].strip()

    tokens = s.split()
    if not tokens:
        return None

    amt_idx = -1
    amount = None

    # Cari token nominal dari belakang ke depan (prioritaskan token dengan suffix k/rb/jt atau format titik ribuan)
    for i in range(len(tokens) - 1, -1, -1):
        clean_tok = tokens[i].strip(",;:()[]")
        a = parse_amount(clean_tok)
        if a and a >= 100:
            if re.search(r'(k|rb|ribu|jt|juta|m|\.)', clean_tok.lower()) or a >= 500:
                amt_idx = i
                amount = a
                break

    # Jika belum ditemukan, periksa token angka murni (minimal 500)
    if amt_idx == -1:
        for i in range(len(tokens) - 1, -1, -1):
            clean_tok = tokens[i].strip(",;:()[]")
            a = parse_amount(clean_tok)
            if a and a >= 500:
                amt_idx = i
                amount = a
                break

    if amount is None or amt_idx == -1:
        return None

    desc_tokens = [tok for i, tok in enumerate(tokens) if i != amt_idx]
    description = " ".join(desc_tokens).strip()
    if not description:
        description = "Pengeluaran" if tx_type == "OUT" else "Pemasukan"

    return tx_type, amount, description

# Pointer rotasi round-robin API key
_rr_key_index = 0

def get_active_keys_pool() -> list[dict]:
    """Mengambil daftar API key aktif dari database, fallback ke .env jika belum ada di database."""
    keys = models.get_active_api_keys()
    if not keys:
        env_raw = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
        if env_raw:
            for k in env_raw.split(","):
                cleaned = k.strip()
                if cleaned and cleaned != "masukkan_api_key_gemini_disini":
                    models.add_api_key(cleaned, label="Default (.env)")
            keys = models.get_active_api_keys()
    return keys

def sync_gemini_ocr(image_bytes: bytes) -> dict:
    """
    Memanggil Google GenAI SDK untuk membaca struk belanja dengan:
    1. Multi-Key Round-Robin & Auto Failover (jika kena 429 / kuota habis, otomatis ganti key berikutnya).
    2. Multi-Model Fallback (gemini-3.5-flash-lite -> gemini-3.1-flash-lite -> gemini-3.8-flash).
    """
    global _rr_key_index
    keys = get_active_keys_pool()
    if not keys:
        raise RuntimeError(
            "Tidak ada Gemini API Key yang aktif.\n"
            "Silakan tambahkan API key dari Google AI Studio dengan cara ketik:\n"
            "`+api [api_key_kamu]`"
        )

    # Urutkan kunci berdasarkan Round-Robin
    n_keys = len(keys)
    start_idx = _rr_key_index % n_keys
    _rr_key_index = (_rr_key_index + 1) % n_keys
    ordered_keys = keys[start_idx:] + keys[:start_idx]

    prompt = (
        "Analisis gambar ini (bisa berupa struk belanja, nota kasir, slip gaji, bukti transfer masuk/keluar, mutasi bank, atau invoice pembayaran) "
        "dan ekstrak datanya ke format JSON murni dengan spesifikasi key berikut:\n"
        "- tipe: tentukan tipe transaksi, pilih salah satu: "
        "  - 'IN' jika ini dokumen pemasukan uang, slip gaji, bukti transfer dana masuk/diterima, invoice terbayar, atau mutasi kredit.\n"
        "  - 'OUT' jika ini dokumen pengeluaran uang, struk belanja kasir, nota pembelian, pembayaran tagihan/cicilan, atau transfer dana keluar.\n"
        "- merchant: nama toko, restoran, nama perusahaan/instansi pemberi gaji, atau pengirim/penerima dana (string, contoh: 'PT SINAR JAYA KONTRAK', 'Indomaret', default 'Pihak Terkait' jika tidak tertera jelas)\n"
        "- total: nominal total bersih transaksi berupa angka murni (integer atau float) tanpa titik, koma, atau simbol mata uang. Khusus slip gaji, ambil 'TOTAL DITERIMA' / Take Home Pay (contoh: 4575000)\n"
        "- kategori: kategori transaksi yang paling cocok:\n"
        "  - Jika tipe 'IN': pilih salah satu dari ['Gaji', 'Bonus & Hadiah', 'Investasi', 'Pemasukan Lain']\n"
        "  - Jika tipe 'OUT': pilih salah satu dari ['Makanan & Minuman', 'Belanja Bulanan', 'Transportasi', 'Utilitas & Tagihan', 'Cicilan & Hutang', 'Hiburan & Hobi', 'Kesehatan', 'Umum']\n"
        "- metode_pembayaran: metode pembayaran atau nama bank / e-wallet jika tertera (contoh: 'Transfer Bank', 'QRIS', 'Tunai', 'BCA', 'Jago', atau 'Unknown')\n"
        "- items: list rincian komponen transaksi (untuk slip gaji: komponen pendapatan dan potongan; untuk struk: nama barang belanjaan). Setiap item memiliki:\n"
        "  - name: nama item / komponen rincian (string)\n"
        "  - price: nominal item (angka integer/float, jika potongan bisa bernilai minus atau positif)\n"
        "  - qty: kuantitas (integer/float, default 1)\n\n"
        "Kembalikan HANYA JSON murni yang valid tanpa format markdown tambahan."
    )

    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash"]
    last_error = None
    response = None
    success_key_id = None
    success_key_masked = None
    success_model = None

    for key_info in ordered_keys:
        k_val = key_info["key_value"]
        k_id = key_info.get("id")
        k_masked = models.mask_api_key(k_val)

        try:
            client = genai.Client(api_key=k_val)
        except Exception as e:
            logger.warning(f"Gagal inisialisasi client Gemini untuk Key {k_masked}: {e}")
            if k_id:
                models.record_api_key_usage(k_id, success=False)
            continue

        key_failed = False
        for m in models_to_try:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                if response and response.text:
                    success_key_id = k_id
                    success_key_masked = k_masked
                    success_model = m
                    break
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                logger.warning(f"Key {k_masked} gagal pada model {m}: {e}")
                
                # Failover ke key berikutnya jika kena rate limit / quota 429 atau key invalid
                if any(kw in err_str for kw in ["429", "quota", "resource_exhausted", "rate", "api_key_invalid", "400"]):
                    logger.warning(f"Key {k_masked} kena limit/invalid ({err_str[:60]}). Failover ke key berikutnya...")
                    key_failed = True
                    break

        if response and response.text:
            break

        if key_failed or not response:
            if k_id:
                models.record_api_key_usage(k_id, success=False)

    if not response or not response.text:
        raise RuntimeError(
            f"Semua API Key dalam pool ({n_keys} key) sedang limit atau gagal. "
            f"Silakan tambah key cadangan via `/api` atau coba beberapa saat lagi.\n"
            f"Detail error terakhir: {last_error}"
        )

    if success_key_id:
        models.record_api_key_usage(success_key_id, success=True)
        
    logger.info(f"OCR struk sukses diproses dengan Key {success_key_masked} (Model: {success_model})")

    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?", "", raw_text)
        raw_text = re.sub(r"```$", "", raw_text).strip()

    return json.loads(raw_text)

# --- COMMAND HANDLERS ---

@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message):
    welcome_text = (
        "💡 *Panduan & Format Cepat (Cheatsheet)*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ *1. Catat Arus Kas (Sat-Set)*\n"
        "• Pengeluaran: Cukup ketik nama & nominal (Otomatis tanpa tanda minus!)\n"
        "  Contoh: `kopi susu 25k` / `makan siang 35.000` / `25k kopi`\n"
        "• Dompet spesifik: `kopi susu 25k jago` / `bensin 50rb jago` / `jajan 25k gpy`\n"
        "• Pemasukan: Wajib gunakan tanda plus `+` (contoh: `+1.5jt gaji` / `+500k bonus`)\n"
        "• Foto Struk: Kirim foto struk (bisa tambah caption `jago`)\n\n"
        "💳 *2. Shortcut Dompet & Saldo*\n"
        "• Tambah: `+dompet gpy 50k` (atau `+dompet ovo`)\n"
        "• Hapus: `-dompet gpy`\n"
        "• Set Saldo: `saldo gpy 100k` atau `saldo jago 2.5jt`\n"
        "• Transfer: `tf gpy 30k` atau `tf 50k jago gpy`\n\n"
        "🔑 *3. Shortcut Multi API Key (Gemini)*\n"
        "• Tambah: `+api [key]` (Pesan terhapus otomatis demi privasi)\n"
        "• Hapus: `-api [id]` (contoh: `-api 2`)\n"
        "• Cek & Tes: `/api`\n\n"
        "📊 *4. Daftar Perintah Menu*\n"
        "• /saldo — Cek rincian saldo & akun\n"
        "• /rekap — Ringkasan arus kas bulanan\n"
        "• /transaksi — Riwayat transaksi terakhir\n"
        "• /export — Unduh file laporan Excel (.xlsx)\n"
        "• /api — Kelola pool multi-key Gemini\n"
        "• /reset — Reset seluruh database (Kembali seperti baru)\n"
        "• /id — Cek ID Telegram Anda (untuk kunci proteksi bot)\n"
        "• /help — Menampilkan panduan ini\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 _Ketik langsung perintah di atas di chat kapan saja!_ 🚀"
    )
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())

def get_wallet_icon(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["gopay", "gpy"]):
        return "🟢"
    if any(k in n for k in ["ovo"]):
        return "🟣"
    if any(k in n for k in ["dana"]):
        return "🔵"
    if any(k in n for k in ["shopee", "spay"]):
        return "🟠"
    if any(k in n for k in ["jago", "bca", "mandiri", "bri", "bni", "cimb", "bank", "seabank"]):
        return "🏦"
    if any(k in n for k in ["bibit", "bybit", "crypto", "saham", "pintu"]):
        return "📈"
    return "💵"

def parse_fast_transfer(text: str):
    """Mendeteksi perintah transfer cepat, contoh: tf 30k jg gpy, tf gpy 30k, tf 50k gpy"""
    s = text.strip()
    lower_s = s.lower()
    if not (lower_s.startswith("tf ") or lower_s.startswith("/tf ") or lower_s.startswith("/transfer ")):
        return None
        
    parts = s.split()[1:]
    if not parts:
        return None

    amt_idx = -1
    amount = None
    for i, p in enumerate(parts):
        a = parse_amount(p)
        if a and a > 0:
            amt_idx = i
            amount = a
            break
            
    if not amount:
        return None
        
    other_tokens = [p for i, p in enumerate(parts) if i != amt_idx]
    
    if len(other_tokens) >= 2:
        return other_tokens[0], other_tokens[1], amount
    elif len(other_tokens) == 1:
        return "auto", other_tokens[0], amount
        
    return None

@router.message(Command("saldo"))
@router.message(Command("dompet"))
async def cmd_saldo(message: Message):
    wallets = models.get_all_wallets()
    if not wallets:
        await message.answer("⚠️ Belum ada data dompet terdaftar.")
        return
    
    total_balance = sum(w["balance"] for w in wallets)
    
    lines = ["💳 *Status Saldo & Dompet Kamu*", "━━━━━━━━━━━━━━━━━━━━"]
    for w in wallets:
        icon = get_wallet_icon(w["name"])
        lines.append(f"{icon} *{w['name']}:* `{models.format_rupiah(w['balance'])}`")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💰 *Total Seluruh Saldo:* `{models.format_rupiah(total_balance)}`")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Tambah Dompet", callback_data="wallet_add_guide"),
            InlineKeyboardButton(text="🗑️ Hapus Dompet", callback_data="wallet_del_menu")
        ],
        [
            InlineKeyboardButton(text="🔄 Refresh Saldo", callback_data="wallet_refresh")
        ]
    ])

    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)

@router.message(Command("rekap"))
async def cmd_rekap(message: Message):
    rekap = models.get_monthly_rekap()
    
    net_icon = "📈" if rekap["net_flow"] >= 0 else "📉"
    net_sign = "+" if rekap["net_flow"] > 0 else ""
    net_str = f"{net_sign}{models.format_rupiah(rekap['net_flow'])}"
    
    lines = [
        f"📊 *Rekap Keuangan {rekap['month_name']} {rekap['year']}*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🟢 *Total Pemasukan:* `{models.format_rupiah(rekap['total_in'])}` ({rekap['count_in']} tx)",
        f"🔴 *Total Pengeluaran:* `{models.format_rupiah(rekap['total_out'])}` ({rekap['count_out']} tx)",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⚖️ *Arus Kas Bersih (Net Flow):* `{net_str}` {net_icon}",
        ""
    ]

    if rekap["out_categories"]:
        lines.append("🔻 *Rincian Pengeluaran:*")
        for cat in rekap["out_categories"]:
            lines.append(f" • {cat['category']}: `{models.format_rupiah(cat['total'])}` ({cat['count']}x)")
        lines.append("")

    if rekap["in_categories"]:
        lines.append("🔺 *Rincian Pemasukan:*")
        for cat in rekap["in_categories"]:
            lines.append(f" • {cat['category']}: `{models.format_rupiah(cat['total'])}` ({cat['count']}x)")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 _Ketik /saldo untuk cek saldo dompet saat ini._")

    await message.answer("\n".join(lines), parse_mode="Markdown")

@router.message(Command("transfer"))
async def cmd_transfer(message: Message):
    # Format: /transfer [nominal] [dari] [ke]
    args = message.text.split()[1:]
    if len(args) < 3:
        await message.reply(
            "ℹ️ *Format Transfer Antar Dompet:*\n"
            "`/transfer [nominal] [dari] [ke]`\n\n"
            "Contoh:\n"
            "• `/transfer 100k jago cash` (Tarik tunai dari Bank Jago ke Cash)\n"
            "• `/transfer 50000 cash jago` (Setor tunai ke Bank Jago)",
            parse_mode="Markdown"
        )
        return
        
    amount = parse_amount(args[0])
    from_name = args[1]
    to_name = args[2]
    
    if not amount or amount <= 0:
        await message.reply("⚠️ Nominal transfer tidak valid.", parse_mode="Markdown")
        return
        
    from_wallet = models.get_wallet_by_name(from_name)
    to_wallet = models.get_wallet_by_name(to_name)
    
    if not from_wallet or not to_wallet:
        await message.reply("⚠️ Dompet asal atau tujuan tidak ditemukan. Cek `/saldo` untuk melihat daftar dompet yang ada.", parse_mode="Markdown")
        return
        
    if from_wallet["id"] == to_wallet["id"]:
        await message.reply("⚠️ Dompet asal dan tujuan tidak boleh sama.", parse_mode="Markdown")
        return

    # Catat mutasi keluar dan masuk
    tx_out = models.add_transaction(
        wallet_id=from_wallet["id"],
        tx_type="OUT",
        amount=amount,
        category="Transfer Keluar",
        description=f"Transfer ke {to_wallet['name']}"
    )
    tx_in = models.add_transaction(
        wallet_id=to_wallet["id"],
        tx_type="IN",
        amount=amount,
        category="Transfer Masuk",
        description=f"Transfer dari {from_wallet['name']}"
    )
    
    reply = (
        "🔄 *Transfer Antar Dompet Berhasil!*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Nominal:* `{models.format_rupiah(amount)}`\n"
        f"📤 *Dari:* {from_wallet['name']} (Sisa: `{models.format_rupiah(tx_out['new_balance'])}`)\n"
        f"📥 *Ke:* {to_wallet['name']} (Saldo: `{models.format_rupiah(tx_in['new_balance'])}`)\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await message.reply(reply, parse_mode="Markdown")

@router.message(Command("transaksi"))
async def cmd_transaksi(message: Message):
    txs = models.get_recent_transactions(limit=6)
    if not txs:
        await message.answer("📭 Belum ada riwayat transaksi yang tersimpan.")
        return
    
    lines = ["📝 *Riwayat Transaksi Terbaru*", "━━━━━━━━━━━━━━━━━━━━"]
    for t in txs:
        icon = "🔴 -" if t["type"] == "OUT" else "🟢 +"
        date_display = t["date"][:16] if t["date"] else "-"
        lines.append(
            f"{icon} *{models.format_rupiah(t['amount'])}* [{t['category']}]\n"
            f"   💬 _{t['description'] or '-'}_ | 💳 {t['wallet_name']} | 🕒 {date_display}"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 _Gunakan /rekap untuk melihat ringkasan bulanan._")

    await message.answer("\n".join(lines), parse_mode="Markdown")

@router.message(Command("export"))
async def cmd_export(message: Message):
    status_msg = await message.answer("⏳ *Sedang menyusun laporan Excel profesional...*", parse_mode="Markdown")
    
    txs = models.get_all_transactions_for_export()
    wallets = models.get_all_wallets()

    try:
        excel_bytes = await asyncio.to_thread(create_financial_excel_report, wallets, txs)
        now_str = datetime.now().strftime("%Y%m%d_%H%M")
        file = BufferedInputFile(excel_bytes, filename=f"Laporan_Keuangan_{now_str}.xlsx")

        total_tx = len(txs)
        caption = (
            "📊 *Laporan Keuangan Profesional Berhasil Dibuat!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 *Format:* Microsoft Excel (.xlsx)\n"
            f"📝 *Total Data:* {total_tx} Transaksi\n\n"
            "📑 *Isi Lembar Kerja (Sheets):*\n"
            " 1️⃣ *📊 Ringkasan Eksekutif:* KPI Cards, Portofolio Saldo, & Analisis Kategori.\n"
            " 2️⃣ *📝 Buku Kas Transaksi:* Detail ledger lengkap, auto-filter & format angka resmi.\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✨ _Dapat dibuka langsung di Excel, Google Sheets, atau WPS Office._"
        )
        await message.answer_document(document=file, caption=caption, parse_mode="Markdown")
        try:
            await status_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error generating Excel report: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ Gagal membuat laporan Excel. Silakan coba beberapa saat lagi.", parse_mode="Markdown")

# --- DATABASE RESET HANDLERS ---

@router.message(Command("reset"))
async def cmd_reset(message: Message):
    text = (
        "⚠️ *Konfirmasi Reset Database Keuangan*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Apakah Anda yakin ingin mengosongkan seluruh database keuangan?\n\n"
        "📋 *Dampak Reset:*\n"
        "• Seluruh riwayat transaksi (pemasukan & pengeluaran) akan dihapus permanen.\n"
        "• Saldo dompet *Cash* dan *Jago* akan dikembalikan ke *Rp 0*.\n"
        "• Dompet / e-wallet tambahan akan dihapus.\n"
        "• 🔑 *Pool API Key Gemini Anda tetap dipertahankan aman.*\n\n"
        "⚠️ _Tindakan ini tidak dapat dibatalkan!_"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔴 Ya, Reset Semua Data", callback_data="db_reset_confirm"),
            InlineKeyboardButton(text="🔙 Batalkan", callback_data="db_reset_cancel")
        ]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

@router.callback_query(F.data == "db_reset_confirm")
async def cb_db_reset_confirm(callback: CallbackQuery):
    try:
        res = models.reset_database(preserve_api_keys=True)
        reply_text = (
            "✅ *Database Berhasil Direset Total!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🗑️ *Transaksi Dihapus:* {res['deleted_transactions']} transaksi\n"
            "💳 *Status Dompet:* Cash (Rp 0) & Jago (Rp 0)\n"
            "🔑 *API Key Pool:* Tetap aktif & siap pakai\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🌱 _Database Anda kini bersih seperti baru. Siap mencatat transaksi baru!_ 🚀"
        )
        await callback.message.edit_text(reply_text, parse_mode="Markdown")
        await callback.answer("✅ Database berhasil dikosongkan!", show_alert=True)
    except Exception as e:
        logger.error(f"Error resetting database: {e}", exc_info=True)
        await callback.answer("⚠️ Gagal mereset database.", show_alert=True)

@router.callback_query(F.data == "db_reset_cancel")
async def cb_db_reset_cancel(callback: CallbackQuery):
    await callback.message.edit_text(
        "❌ *Reset Database Dibatalkan.*\n"
        "Data transaksi dan saldo dompet Anda tetap aman tanpa perubahan.",
        parse_mode="Markdown"
    )
    await callback.answer("Reset dibatalkan.", show_alert=False)

# --- API KEY MANAGEMENT (MULTI-KEY POOL) ---

def format_api_keys_message() -> tuple[str, InlineKeyboardMarkup]:
    keys = models.get_all_api_keys()
    lines = [
        "🔑 *Gemini API Key Pool (Multi-Key)*",
        "━━━━━━━━━━━━━━━━━━━━"
    ]
    if not keys:
        lines.append("⚠️ _Belum ada API Key yang tersimpan._")
        lines.append("Ketik: `+api [api_key_kamu]` untuk menambahkan.")
    else:
        for idx, k in enumerate(keys, 1):
            masked = models.mask_api_key(k["key_value"])
            status_icon = "🟢 Aktif" if k["is_active"] else "🔴 Nonaktif"
            fails = k.get("fail_count", 0)
            fail_str = f" | ⚠️ Fail: {fails}x" if fails > 0 else ""
            label = f" ({k['label']})" if k.get("label") else ""
            lines.append(f"{idx}. *Key #{k['id']}*: `{masked}`{label}")
            lines.append(f"   └ Status: {status_icon}{fail_str}")
            
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"⚡ *Total:* {len(keys)} API Key terdaftar")
    lines.append("💡 *Rotasi:* Round-Robin + Auto Failover (Anti-Limit 🚀)")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Tambah API Key", callback_data="api_add_guide"),
            InlineKeyboardButton(text="🗑️ Hapus Key", callback_data="api_del_menu")
        ],
        [
            InlineKeyboardButton(text="🧪 Tes Semua Key", callback_data="api_test_all"),
            InlineKeyboardButton(text="🔄 Refresh", callback_data="api_refresh")
        ]
    ])
    return "\n".join(lines), keyboard

@router.message(Command("api"))
@router.message(Command("keys"))
async def cmd_api(message: Message):
    text, kb = format_api_keys_message()
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)

# --- PHOTO / RECEIPT AI OCR HANDLER ---

@router.message(F.photo | (F.document & F.document.mime_type.startswith("image/")))
async def handle_photo(message: Message, bot: Bot):
    active_keys = get_active_keys_pool()
    if not active_keys:
        await message.reply(
            "⚠️ *Fitur AI Vision Belum Memiliki API Key Aktif*\n"
            "Belum ada Gemini API Key yang terdaftar di sistem.\n\n"
            "Silakan tambahkan API key gratis dari Google AI Studio dengan cara mengetik:\n"
            "`+api [api_key_kamu]`",
            parse_mode="Markdown"
        )
        return

    status_msg = await message.reply("⏳ *Lagi mbaca struk denteni disit*", parse_mode="Markdown")

    try:
        # Unduh foto resolusi tertinggi atau dokumen gambar
        if message.photo:
            file_target = message.photo[-1]
        else:
            file_target = message.document

        photo_io = io.BytesIO()
        await bot.download(file_target, destination=photo_io)
        image_bytes = photo_io.getvalue()

        # Jalankan pemrosesan Gemini di background thread dengan multi-key round-robin & failover
        receipt_data = await asyncio.to_thread(sync_gemini_ocr, image_bytes)

        merchant = receipt_data.get("merchant") or receipt_data.get("toko") or "Toko/Merchant"
        raw_total = receipt_data.get("total") or receipt_data.get("total_belanja") or 0
        try:
            total_amount = float(raw_total)
        except (ValueError, TypeError):
            total_amount = 0.0

        items = receipt_data.get("items") or receipt_data.get("barang") or []
        if total_amount <= 0 and items:
            total_amount = sum(
                float(it.get("price") or it.get("harga") or it.get("total") or 0) *
                float(it.get("qty") or it.get("jumlah") or it.get("kuantitas") or 1)
                for it in items if isinstance(it, dict)
            )

        if total_amount <= 0:
            await status_msg.edit_text(
                "⚠️ *Gagal Mendeteksi Total Nominal:*\n"
                "AI tidak dapat menemukan nominal total pada dokumen/struk. Pastikan foto terlihat jelas dan coba kirim kembali.",
                parse_mode="Markdown"
            )
            return

        # 1. Deteksi dompet dari Caption pesan jika user menyertakan 'jago' atau 'cash'
        caption_text = (message.caption or "").strip()
        target_wallet = None

        if caption_text:
            for w in models.get_all_wallets():
                if w["name"].lower() in caption_text.lower():
                    target_wallet = w
                    break

        # 2. Jika tidak ada caption dompet, cek apakah struk/dokumen menyebutkan QRIS / Debit / Transfer
        if not target_wallet:
            payment_method = str(receipt_data.get("metode_pembayaran") or "").lower()
            if any(term in payment_method for term in ["qris", "debit", "transfer", "kartu", "card", "edc", "cashless", "bca", "jago"]):
                jago_wallet = models.get_wallet_by_name("Jago")
                if jago_wallet:
                    target_wallet = jago_wallet

        # 3. Fallback ke dompet bawaan (Cash)
        if not target_wallet:
            target_wallet = models.get_default_wallet()

        # 4. Tentukan Tipe Transaksi (IN vs OUT)
        caption_lower = caption_text.lower()
        has_income_hint = any(w in caption_lower for w in ["gaji", "salary", "bonus", "pemasukan", "income", "diterima", "masuk", "terima", "honor", "thr", "fee", "upah"]) or caption_text.startswith("+")
        has_expense_hint = any(w in caption_lower for w in ["beli", "bayar", "jajan", "belanja", "pengeluaran", "keluar", "struk"]) or caption_text.startswith("-")

        detected_type = str(receipt_data.get("tipe") or "").upper().strip()
        if has_income_hint:
            tx_type = "IN"
        elif has_expense_hint:
            tx_type = "OUT"
        elif detected_type in ["IN", "PEMASUKAN", "INCOME"]:
            tx_type = "IN"
        else:
            tx_type = "OUT"

        # 5. Kategori dan Deskripsi
        category = receipt_data.get("kategori") or ""
        if tx_type == "IN":
            valid_in_cats = ["Gaji", "Bonus & Hadiah", "Investasi", "Pemasukan Lain"]
            if category not in valid_in_cats:
                category = models.detect_category(f"{merchant} {caption_text}", "IN")
            desc = f"Pemasukan: {merchant}"
        else:
            valid_out_cats = [
                "Makanan & Minuman", "Belanja Bulanan", "Transportasi",
                "Utilitas & Tagihan", "Cicilan & Hutang", "Hiburan & Hobi", "Kesehatan", "Umum"
            ]
            if category not in valid_out_cats:
                category = models.detect_category(f"{merchant} {caption_text}", "OUT")
            desc = f"Struk: {merchant}"

        # 6. Simpan ke database
        tx = models.add_transaction(
            wallet_id=target_wallet["id"],
            tx_type=tx_type,
            amount=total_amount,
            category=category,
            description=desc
        )

        # 7. Susun daftar barang / komponen dengan proteksi karakter khusus Markdown
        items_text = ""
        if items and isinstance(items, list):
            items_lines = []
            for it in items[:8]:  # Tampilkan hingga 8 item agar chat rapi
                name = it.get("name") or it.get("nama") or it.get("item") or "Item"
                price = it.get("price") or it.get("harga") or it.get("total") or 0
                qty = it.get("qty") or it.get("jumlah") or it.get("kuantitas") or 1
                name_safe = escape_md(str(name))
                price_val = float(price)
                if price_val < 0:
                    price_str = f"-{models.format_rupiah(abs(price_val))}"
                else:
                    price_str = models.format_rupiah(price_val)
                items_lines.append(f" • {name_safe} ({qty}x) - {price_str}")
            if len(items) > 8:
                items_lines.append(f" • _...dan {len(items) - 8} komponen lainnya_")
            rincian_title = "📋 *Rincian Komponen:*" if tx_type == "IN" else "📋 *Rincian Barang:*"
            items_text = f"\n{rincian_title}\n" + "\n".join(items_lines) + "\n"

        merchant_safe = escape_md(str(merchant))
        category_safe = escape_md(str(category))
        wallet_safe = escape_md(str(tx['wallet_name']))

        if tx_type == "IN":
            header_title = "💵 *Pemasukan Berhasil Dibaca & Disimpan!*"
            entity_label = "🏢 *Sumber:*"
            total_label = "💰 *Total Masuk:*"
            status_note = "🟢 _Otomatis dicatat sebagai pemasukan._"
            toggle_label = "🔄 Ubah ke Pengeluaran"
        else:
            header_title = "🧾 *Struk Berhasil Dibaca & Disimpan!*"
            entity_label = "🏪 *Toko:*"
            total_label = "💰 *Total Belanja:*"
            status_note = "✅ _Otomatis dicatat sebagai pengeluaran._"
            toggle_label = "🔄 Ubah ke Pemasukan"

        response_text = (
            f"{header_title}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{entity_label} {merchant_safe}\n"
            f"📂 *Kategori:* {category_safe}\n"
            f"{total_label} `{models.format_rupiah(total_amount)}`\n"
            f"{items_text}"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💳 *Dompet:* {wallet_safe}\n"
            f"💵 *Sisa Saldo {wallet_safe}:* `{models.format_rupiah(tx['new_balance'])}`\n"
            f"{status_note}"
        )

        other_wallet_name = "Jago" if target_wallet["name"].lower() == "cash" else "Cash"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_label, callback_data=f"toggle_type_{tx['id']}"),
                InlineKeyboardButton(text=f"🔁 Pindah ke {other_wallet_name}", callback_data=f"switch_wallet_{tx['id']}")
            ],
            [
                InlineKeyboardButton(text="🗑️ Hapus Transaksi", callback_data=f"del_tx_{tx['id']}")
            ]
        ])

        await status_msg.edit_text(response_text, parse_mode="Markdown", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error handling receipt photo: {e}", exc_info=True)
        await status_msg.edit_text(
            "⚠️ *Gagal Membaca Struk:*\n"
            "Terjadi kesalahan saat memproses gambar dengan AI. Pastikan foto struk tegak, terang, dan tidak buram, lalu coba kirimkan kembali.",
            parse_mode="Markdown"
        )

# --- SMART TEXT PARSING HANDLER ---

@router.message(F.text)
async def handle_text(message: Message):
    text = message.text.strip()

    # 0. Jika user menekan tombol keyboard lama, respon dan hapus keyboard dari layar
    if text in ["💳 Cek Saldo", "💳 Saldo & Dompet", "💳 Saldo"]:
        await message.answer("Menghapus menu keyboard...", reply_markup=ReplyKeyboardRemove())
        await cmd_saldo(message)
        return
    if text == "📊 Rekap Bulanan":
        await message.answer("Menghapus menu keyboard...", reply_markup=ReplyKeyboardRemove())
        await cmd_rekap(message)
        return
    if text == "📝 Transaksi Terakhir":
        await message.answer("Menghapus menu keyboard...", reply_markup=ReplyKeyboardRemove())
        await cmd_transaksi(message)
        return
    if text == "📄 Export CSV":
        await message.answer("Menghapus menu keyboard...", reply_markup=ReplyKeyboardRemove())
        await cmd_export(message)
        return
    if text == "💡 Panduan Cepat":
        await cmd_start(message)
        return

    # 1. Cek perintah transfer cepat (contoh: tf 30k jg gpy, tf gpy 30k, tf 50k gpy)
    tf_data = parse_fast_transfer(text)
    if tf_data:
        from_raw, to_raw, amount = tf_data
        to_wallet = models.get_wallet_by_name(to_raw)
        if not to_wallet:
            await message.reply(f"⚠️ Dompet tujuan `{to_raw}` tidak ditemukan. Cek `/dompet` untuk melihat daftar dompet.", parse_mode="Markdown")
            return
            
        if from_raw == "auto":
            # Jika hanya sebut tujuan (misal: tf gpy 30k), otomatis ambil dari Jago (atau Cash jika Jago tujuan)
            if to_wallet["name"].lower() != "jago":
                from_wallet = models.get_wallet_by_name("Jago") or models.get_default_wallet()
            else:
                from_wallet = models.get_default_wallet()
        else:
            from_wallet = models.get_wallet_by_name(from_raw)
            
        if not from_wallet:
            await message.reply(f"⚠️ Dompet asal `{from_raw}` tidak ditemukan.", parse_mode="Markdown")
            return
            
        if from_wallet["id"] == to_wallet["id"]:
            await message.reply("⚠️ Dompet asal dan tujuan tidak boleh sama.", parse_mode="Markdown")
            return
            
        tx_out = models.add_transaction(
            wallet_id=from_wallet["id"],
            tx_type="OUT",
            amount=amount,
            category="Transfer Keluar",
            description=f"Transfer ke {to_wallet['name']}"
        )
        tx_in = models.add_transaction(
            wallet_id=to_wallet["id"],
            tx_type="IN",
            amount=amount,
            category="Transfer Masuk",
            description=f"Transfer dari {from_wallet['name']}"
        )
        
        reply = (
            "🔄 *Transfer Antar Dompet Berhasil!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Nominal:* `{models.format_rupiah(amount)}`\n"
            f"📤 *Dari:* {from_wallet['name']} (Sisa: `{models.format_rupiah(tx_out['new_balance'])}`)\n"
            f"📥 *Ke:* {to_wallet['name']} (Saldo: `{models.format_rupiah(tx_in['new_balance'])}`)\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        await message.reply(reply, parse_mode="Markdown")
        return

    # 2. Cek tambah dompet cepat (contoh: +dompet gpy 50k atau +dompet ovo)
    m_add = re.match(r'^\+dompet\s+([a-zA-Z0-9_\-]+)(?:\s+(.*))?$', text, re.IGNORECASE)
    if m_add:
        raw_name, raw_bal = m_add.groups()
        canonical_name = models.resolve_wallet_name(raw_name)
        existing = models.get_wallet_by_name(raw_name)
        if existing:
            await message.reply(f"⚠️ Dompet *{existing['name']}* sudah terdaftar sebelumnya.", parse_mode="Markdown")
            return
            
        bal = parse_amount(raw_bal) if raw_bal else 0.0
        new_w = models.add_wallet(canonical_name, bal)
        if new_w:
            icon = get_wallet_icon(new_w["name"])
            reply = (
                "✅ *Dompet Baru Berhasil Ditambahkan!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{icon} *Nama Akun:* {new_w['name']}\n"
                f"💰 *Saldo Awal:* `{models.format_rupiah(new_w['balance'])}`\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 _Sekarang kamu bisa langsung catat:_ `-25k jajan {raw_name.lower()}`"
            )
            await message.reply(reply, parse_mode="Markdown")
        else:
            await message.reply("⚠️ Gagal menambahkan dompet baru.", parse_mode="Markdown")
        return

    # 3. Cek hapus dompet cepat (contoh: -dompet ovo)
    m_del = re.match(r'^\-dompet\s+([a-zA-Z0-9_\-]+)$', text, re.IGNORECASE)
    if m_del:
        raw_name = m_del.group(1)
        w = models.get_wallet_by_name(raw_name)
        if not w:
            await message.reply(f"⚠️ Dompet `{raw_name}` tidak ditemukan.", parse_mode="Markdown")
            return
        if w["name"].lower() == "cash":
            await message.reply("⚠️ Dompet utama *Cash* tidak dapat dihapus.", parse_mode="Markdown")
            return
            
        success = models.delete_wallet(w["id"])
        if success:
            await message.reply(f"🗑️ *Dompet Dihapus:*\nAkun *{w['name']}* telah berhasil dihapus dari sistem.", parse_mode="Markdown")
        else:
            await message.reply("⚠️ Gagal menghapus dompet.", parse_mode="Markdown")
        return

    # 4. Cek penyesuaian saldo cepat (contoh: saldo gpy 150k atau saldo jago 2.5jt)
    m_set = re.match(r'^saldo\s+([a-zA-Z0-9_\-]+)\s+([0-9.,]+(?:\s*(?:k|rb|ribu|jt|juta|m)\b)?)$', text, re.IGNORECASE)
    if m_set:
        raw_name, raw_amt = m_set.groups()
        w = models.get_wallet_by_name(raw_name)
        if not w:
            await message.reply(f"⚠️ Dompet `{raw_name}` tidak ditemukan.", parse_mode="Markdown")
            return
            
        new_bal = parse_amount(raw_amt)
        if new_bal is None:
            await message.reply("⚠️ Nominal saldo tidak valid.", parse_mode="Markdown")
            return
            
        success = models.set_wallet_balance(w["id"], new_bal)
        if success:
            icon = get_wallet_icon(w["name"])
            await message.reply(
                "✏️ *Saldo Berhasil Disesuaikan!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"{icon} *Dompet:* {w['name']}\n"
                f"💰 *Saldo Baru:* `{models.format_rupiah(new_bal)}`\n"
                "━━━━━━━━━━━━━━━━━━━━",
                parse_mode="Markdown"
            )
        else:
            await message.reply("⚠️ Gagal mengupdate saldo.", parse_mode="Markdown")
        return

    # 4b. Cek tambah API key cepat (contoh: +api AIzaSyB... atau +api AIzaSyB... cadangan)
    m_add_api = re.match(r'^\+api\s+(\S+)(?:\s+(.*))?$', text, re.IGNORECASE)
    if m_add_api:
        raw_key, raw_label = m_add_api.groups()
        # Hapus pesan user segera demi keamanan privasi
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Gagal menghapus pesan API key: {e}")

        status_msg = await message.answer("⏳ *Menguji API Key baru ke Google Gemini...*", parse_mode="Markdown")

        # Uji coba validitas API key
        try:
            client = genai.Client(api_key=raw_key)
            test_res = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3.5-flash-lite",
                contents="ping"
            )
            if not test_res or not test_res.text:
                raise ValueError("Respons kosong dari Gemini.")
        except Exception as e:
            err_msg = str(e)
            logger.warning(f"Validasi API key baru gagal: {e}")
            await status_msg.edit_text(
                f"❌ *API Key Tidak Valid atau Kuota Habis:*\n"
                f"`{escape_md(err_msg[:120])}`\n\n"
                "Pastikan API key aktif di Google AI Studio.",
                parse_mode="Markdown"
            )
            return

        # Simpan ke database
        label_text = raw_label.strip() if raw_label else "User Added"
        new_key = models.add_api_key(raw_key, label=label_text)
        if new_key:
            masked = models.mask_api_key(raw_key)
            total_active = len(models.get_active_api_keys())
            reply = (
                "✅ *Gemini API Key Berhasil Ditambahkan & Valid!*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🔑 *Key:* `{masked}`\n"
                f"🏷️ *Label:* {label_text}\n"
                f"🟢 *Status:* Aktif dalam Pool Rotasi\n"
                f"⚡ *Total Pool:* {total_active} Key Siap Pakai\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🛡️ _Pesan rahasia Anda telah dihapus otomatis demi keamanan._"
            )
            await status_msg.edit_text(reply, parse_mode="Markdown")
        else:
            await status_msg.edit_text(
                "⚠️ *API Key ini sudah pernah terdaftar sebelumnya.*",
                parse_mode="Markdown"
            )
        return

    # 4c. Cek hapus API key cepat (contoh: -api 2)
    m_del_api = re.match(r'^\-api\s+(\d+)$', text, re.IGNORECASE)
    if m_del_api:
        key_id = int(m_del_api.group(1))
        k = models.get_api_key_by_id(key_id)
        if not k:
            await message.reply(f"⚠️ API Key dengan ID #{key_id} tidak ditemukan. Cek `/api` untuk melihat daftar.", parse_mode="Markdown")
            return
            
        success = models.delete_api_key(key_id)
        if success:
            masked = models.mask_api_key(k["key_value"])
            await message.reply(
                f"🗑️ *API Key Dihapus:*\nKey #{key_id} (`{masked}`) telah dihapus dari pool rotasi.",
                parse_mode="Markdown"
            )
        else:
            await message.reply("⚠️ Gagal menghapus API key.", parse_mode="Markdown")
        return

    # 5. Cek apakah format teks kilat (+/- nominal catatan)
    parsed = parse_quick_entry(text)
    if parsed:
        tx_type, amount, raw_description = parsed
        
        # Deteksi dompet spesifik jika user menyebutkan 'jago' atau 'cash'
        target_wallet, description = models.extract_wallet_from_text(raw_description)

        # Deteksi kategori otomatis berdasarkan deskripsi
        category = models.detect_category(description, tx_type)

        tx = models.add_transaction(
            wallet_id=target_wallet["id"],
            tx_type=tx_type,
            amount=amount,
            category=category,
            description=description
        )

        type_label = "Pengeluaran 🔴" if tx_type == "OUT" else "Pemasukan 🟢"
        
        reply_text = (
            "✅ *Catatan Berhasil Disimpan!*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 *Tipe:* {type_label}\n"
            f"💰 *Nominal:* `{models.format_rupiah(amount)}`\n"
            f"📂 *Kategori:* {category}\n"
            f"📝 *Keterangan:* {description}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💳 *Dompet:* {tx['wallet_name']}\n"
            f"💵 *Sisa Saldo {tx['wallet_name']}:* `{models.format_rupiah(tx['new_balance'])}`"
        )
        other_wallet_name = "Jago" if target_wallet["name"].lower() == "cash" else "Cash"
        toggle_label = "🔄 Ubah ke Pemasukan" if tx_type == "OUT" else "🔄 Ubah ke Pengeluaran"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=toggle_label, callback_data=f"toggle_type_{tx['id']}"),
                InlineKeyboardButton(text=f"🔁 Pindah ke {other_wallet_name}", callback_data=f"switch_wallet_{tx['id']}")
            ],
            [
                InlineKeyboardButton(text="🗑️ Hapus Transaksi", callback_data=f"del_tx_{tx['id']}")
            ]
        ])
        await message.reply(reply_text, parse_mode="Markdown", reply_markup=keyboard)
        return

    # Jika teks bukan format kilat dan bukan command
    if not text.startswith("/"):
        help_prompt = (
            "💡 *Format Catat Cepat (Sat-Set):*\n"
            "• Pengeluaran: Cukup ketik nama & nominal (contoh: `kopi susu 25k`, `makan siang 35.000`, `bensin 50rb jago`)\n"
            "• Pemasukan: Wajib gunakan tanda plus `+` (contoh: `+1.5jt gaji`, `+500k bonus`)\n"
            "• Atau kirim *foto struk / slip gaji / bukti transfer* Anda langsung ke sini.\n\n"
            "Ketik /help untuk panduan lengkap atau /rekap untuk laporan bulanan."
        )
        await message.reply(help_prompt, parse_mode="Markdown")

@router.callback_query(F.data.startswith("toggle_type_"))
async def callback_toggle_type(callback: CallbackQuery):
    try:
        tx_id = int(callback.data.replace("toggle_type_", ""))
        res = models.toggle_transaction_type(tx_id)
        if res:
            new_type = res["new_type"]
            wallet_name = res["wallet_name"]
            other_wallet = "Cash" if wallet_name.lower() == "jago" else "Jago"

            if new_type == "IN":
                toggle_btn_text = "🔄 Ubah ke Pengeluaran"
                status_text = "🟢 _Otomatis dicatat sebagai pemasukan._"
                type_label = "Pemasukan 🟢"
            else:
                toggle_btn_text = "🔄 Ubah ke Pemasukan"
                status_text = "✅ _Otomatis dicatat sebagai pengeluaran._"
                type_label = "Pengeluaran 🔴"

            new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=toggle_btn_text, callback_data=f"toggle_type_{tx_id}"),
                    InlineKeyboardButton(text=f"🔁 Pindah ke {other_wallet}", callback_data=f"switch_wallet_{tx_id}")
                ],
                [
                    InlineKeyboardButton(text="🗑️ Hapus Transaksi", callback_data=f"del_tx_{tx_id}")
                ]
            ])

            if callback.message and callback.message.text:
                orig_text = callback.message.text
                lines = orig_text.split("\n")
                new_lines = []
                for line in lines:
                    if "Berhasil Dibaca & Disimpan!" in line:
                        if new_type == "IN":
                            new_lines.append("💵 *Pemasukan Berhasil Dibaca & Disimpan!*")
                        else:
                            new_lines.append("🧾 *Struk Berhasil Dibaca & Disimpan!*")
                    elif "📌 Tipe:" in line or "📌 *Tipe:*" in line:
                        new_lines.append(f"📌 *Tipe:* {type_label}")
                    elif "📂 Kategori:" in line or "📂 *Kategori:*" in line:
                        new_lines.append(f"📂 *Kategori:* {res['new_category']}")
                    elif "💰 Total" in line or "💰 *Total" in line:
                        prefix = "💰 *Total Masuk:*" if new_type == "IN" else "💰 *Total:*"
                        new_lines.append(f"{prefix} `{models.format_rupiah(res['amount'])}`")
                    elif "💵 Sisa Saldo" in line or "💵 *Sisa Saldo" in line:
                        new_lines.append(f"💵 *Sisa Saldo {wallet_name}:* `{models.format_rupiah(res['new_balance'])}`")
                    elif "Otomatis dicatat sebagai" in line:
                        new_lines.append(status_text)
                    else:
                        new_lines.append(line)

                await callback.message.edit_text("\n".join(new_lines), parse_mode="Markdown", reply_markup=new_keyboard)
                await callback.answer(f"✅ Diubah menjadi {type_label}!", show_alert=False)
        else:
            await callback.answer("⚠️ Transaksi tidak ditemukan.", show_alert=True)
    except Exception as e:
        logger.error(f"Error toggling transaction type: {e}", exc_info=True)
        await callback.answer("⚠️ Gagal mengubah tipe transaksi.", show_alert=True)

@router.callback_query(F.data.startswith("switch_wallet_"))
async def callback_switch_wallet(callback: CallbackQuery):
    try:
        tx_id = int(callback.data.replace("switch_wallet_", ""))
        res = models.switch_transaction_wallet(tx_id)
        if res:
            new_wallet = res["new_wallet_name"]
            next_target = "Cash" if new_wallet.lower() == "jago" else "Jago"
            
            # Periksa tipe transaksi untuk tombol toggle
            conn = models.get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT type FROM transactions WHERE id = ?;", (tx_id,))
            row = cur.fetchone()
            conn.close()

            curr_type = row["type"] if row else "OUT"
            toggle_label = "🔄 Ubah ke Pengeluaran" if curr_type == "IN" else "🔄 Ubah ke Pemasukan"

            new_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=toggle_label, callback_data=f"toggle_type_{tx_id}"),
                    InlineKeyboardButton(text=f"🔁 Pindah ke {next_target}", callback_data=f"switch_wallet_{tx_id}")
                ],
                [
                    InlineKeyboardButton(text="🗑️ Hapus Transaksi", callback_data=f"del_tx_{tx_id}")
                ]
            ])
            
            if callback.message and callback.message.text:
                orig_text = callback.message.text
                lines = orig_text.split("\n")
                new_lines = []
                for line in lines:
                    if "💳 Dompet:" in line or "💳 *Dompet:*" in line:
                        new_lines.append(f"💳 *Dompet:* {new_wallet}")
                    elif "💵 Sisa Saldo" in line or "💵 *Sisa Saldo" in line:
                        new_lines.append(f"💵 *Sisa Saldo {new_wallet}:* `{models.format_rupiah(res['new_balance'])}`")
                    else:
                        new_lines.append(line)
                
                await callback.message.edit_text("\n".join(new_lines), parse_mode="Markdown", reply_markup=new_keyboard)
                await callback.answer(f"✅ Berhasil dipindahkan ke {new_wallet}!", show_alert=False)
        else:
            await callback.answer("⚠️ Gagal memindahkan dompet atau transaksi tidak ditemukan.", show_alert=True)
    except Exception as e:
        logger.error(f"Error switching wallet: {e}", exc_info=True)
        await callback.answer("⚠️ Gagal memindahkan dompet.", show_alert=True)

@router.callback_query(F.data.startswith("del_tx_"))
async def callback_delete_tx(callback: CallbackQuery):
    try:
        tx_id = int(callback.data.replace("del_tx_", ""))
        success = models.delete_transaction(tx_id)
        if success:
            await callback.answer("✅ Transaksi berhasil dihapus dan saldo telah dikembalikan!", show_alert=True)
            if callback.message:
                await callback.message.edit_text(
                    "❌ *Transaksi Ini Telah Dibatalkan & Dihapus.*\n"
                    "Saldo dompet Anda telah dikembalikan secara otomatis. 🔄",
                    parse_mode="Markdown"
                )
        else:
            await callback.answer("⚠️ Transaksi tidak ditemukan atau sudah dihapus sebelumnya.", show_alert=True)
    except Exception as e:
        logger.error(f"Error deleting transaction: {e}")
        await callback.answer("⚠️ Gagal menghapus transaksi.", show_alert=True)

# --- WALLET MANAGEMENT CALLBACKS ---

@router.callback_query(F.data == "wallet_del_menu")
async def cb_wallet_del_menu(callback: CallbackQuery):
    wallets = models.get_all_wallets()
    deletable = [w for w in wallets if w["name"].lower() != "cash"]
    if not deletable:
        await callback.answer("⚠️ Tidak ada dompet lain yang bisa dihapus (Cash adalah dompet utama).", show_alert=True)
        return

    buttons = []
    for w in deletable:
        icon = get_wallet_icon(w["name"])
        buttons.append([InlineKeyboardButton(text=f"🗑️ Hapus {icon} {w['name']}", callback_data=f"wallet_confirm_del_{w['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Batal", callback_data="wallet_refresh")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        "🗑️ *Pilih Dompet / E-Wallet yang Ingin Dihapus:*\n"
        "_Catatan: Transaksi lama dompet ini akan otomatis dialihkan ke Cash agar data tetap aman._",
        parse_mode="Markdown",
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("wallet_confirm_del_"))
async def cb_wallet_confirm_del(callback: CallbackQuery):
    try:
        w_id = int(callback.data.replace("wallet_confirm_del_", ""))
        success = models.delete_wallet(w_id)
        if success:
            await callback.answer("✅ Dompet berhasil dihapus!", show_alert=True)
        else:
            await callback.answer("⚠️ Gagal menghapus dompet.", show_alert=True)
        await cb_wallet_refresh(callback)
    except Exception as e:
        logger.error(f"Error deleting wallet via callback: {e}")
        await callback.answer("⚠️ Terjadi kesalahan.", show_alert=True)

@router.callback_query(F.data == "wallet_add_guide")
async def cb_wallet_add_guide(callback: CallbackQuery):
    guide_text = (
        "➕ *Cara Tambah Dompet / E-Wallet Kilat:*\n"
        "Cukup ketik langsung di chat pesan seperti ini:\n\n"
        "• `+dompet gpy 50k` (Tambah Gopay saldo 50rb)\n"
        "• `+dompet ovo 100k` (Tambah OVO saldo 100rb)\n"
        "• `+dompet dana` (Tambah DANA saldo 0)\n"
        "• `+dompet spay` (Tambah ShopeePay)\n\n"
        "💡 _Ketik sekarang di chat ya, Bro!_"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Kembali ke Daftar Saldo", callback_data="wallet_refresh")]
    ])
    await callback.message.edit_text(guide_text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "wallet_refresh")
async def cb_wallet_refresh(callback: CallbackQuery):
    wallets = models.get_all_wallets()
    total_balance = sum(w["balance"] for w in wallets)
    lines = ["💳 *Status Saldo & Dompet Kamu*", "━━━━━━━━━━━━━━━━━━━━"]
    for w in wallets:
        icon = get_wallet_icon(w["name"])
        lines.append(f"{icon} *{w['name']}:* `{models.format_rupiah(w['balance'])}`")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💰 *Total Seluruh Saldo:* `{models.format_rupiah(total_balance)}`")

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Tambah Dompet", callback_data="wallet_add_guide"),
            InlineKeyboardButton(text="🗑️ Hapus Dompet", callback_data="wallet_del_menu")
        ],
        [
            InlineKeyboardButton(text="🔄 Refresh Saldo", callback_data="wallet_refresh")
        ]
    ])
    try:
        await callback.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)
    except Exception:
        pass
    await callback.answer("🔄 Saldo diperbarui!", show_alert=False)

# --- API KEY MANAGEMENT CALLBACKS ---

@router.callback_query(F.data == "api_add_guide")
async def cb_api_add_guide(callback: CallbackQuery):
    guide_text = (
        "➕ *Cara Tambah Gemini API Key:*\n\n"
        "Cukup ketik langsung di chat format berikut:\n"
        "`+api AIzaSyB...blablabla`\n\n"
        "🛡️ *Privasi Terjamin:* Pesan chat Anda yang berisi API key akan langsung dihapus oleh bot secara otomatis.\n"
        "🧪 *Validasi Otomatis:* Bot akan menguji key ke Google Gemini sebelum menyimpannya ke pool."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Kembali", callback_data="api_refresh")]
    ])
    await callback.message.edit_text(guide_text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "api_del_menu")
async def cb_api_del_menu(callback: CallbackQuery):
    keys = models.get_all_api_keys()
    if not keys:
        await callback.answer("⚠️ Belum ada API key untuk dihapus.", show_alert=True)
        return

    buttons = []
    for k in keys:
        masked = models.mask_api_key(k["key_value"])
        label = f" #{k['id']} ({masked})"
        buttons.append([InlineKeyboardButton(text=f"🗑️ Hapus{label}", callback_data=f"api_confirm_del_{k['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Batal", callback_data="api_refresh")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        "🗑️ *Pilih API Key yang Ingin Dihapus dari Pool:*",
        parse_mode="Markdown",
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("api_confirm_del_"))
async def cb_api_confirm_del(callback: CallbackQuery):
    try:
        k_id = int(callback.data.replace("api_confirm_del_", ""))
        success = models.delete_api_key(k_id)
        if success:
            await callback.answer(f"✅ API Key #{k_id} berhasil dihapus!", show_alert=True)
        else:
            await callback.answer("⚠️ Gagal menghapus API Key.", show_alert=True)
        text, kb = format_api_keys_message()
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logger.error(f"Error deleting api key: {e}")
        await callback.answer("⚠️ Terjadi kesalahan.", show_alert=True)

@router.callback_query(F.data == "api_test_all")
async def cb_api_test_all(callback: CallbackQuery):
    keys = models.get_all_api_keys()
    if not keys:
        await callback.answer("⚠️ Belum ada API Key terdaftar.", show_alert=True)
        return

    await callback.answer("⏳ Menguji semua API Key ke Google...", show_alert=False)
    lines = [
        "🧪 *Hasil Uji Coba API Key*",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    for idx, k in enumerate(keys, 1):
        masked = models.mask_api_key(k["key_value"])
        label = f" ({k['label']})" if k.get("label") else ""
        try:
            start_t = datetime.now()
            client = genai.Client(api_key=k["key_value"])
            # Ping Gemini
            res = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3.5-flash-lite",
                contents="ping"
            )
            elapsed = (datetime.now() - start_t).total_seconds()
            if res and res.text:
                models.record_api_key_usage(k["id"], success=True)
                lines.append(f"{idx}. `{masked}`{label}\n   └ 🟢 *Valid & Aktif* ({elapsed:.2f}s)")
            else:
                lines.append(f"{idx}. `{masked}`{label}\n   └ ⚠️ *Respons Kosong*")
        except Exception as e:
            err_short = str(e)[:60]
            models.record_api_key_usage(k["id"], success=False)
            lines.append(f"{idx}. `{masked}`{label}\n   └ 🔴 *Error:* {escape_md(err_short)}")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Kembali ke Pool", callback_data="api_refresh")]
    ])
    try:
        await callback.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

@router.callback_query(F.data == "api_refresh")
async def cb_api_refresh(callback: CallbackQuery):
    text, kb = format_api_keys_message()
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass
    await callback.answer("🔄 Pool diperbarui!", show_alert=False)

