import asyncio
import logging
import os
import sys
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeAllPrivateChats

from database import init_db
from handlers import router
from middlewares import WhitelistMiddleware, get_allowed_telegram_ids

# Konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("FinanceBot")

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="saldo", description="💳 Cek Saldo & Kelola Dompet"),
        BotCommand(command="rekap", description="📊 Rekap Arus Kas Bulanan"),
        BotCommand(command="transaksi", description="📝 Transaksi Terakhir"),
        BotCommand(command="export", description="📊 Unduh Laporan Excel (.xlsx)"),
        BotCommand(command="api", description="🔑 Kelola Multi Gemini API Key"),
        BotCommand(command="reset", description="⚠️ Reset Semua Data Database"),
        BotCommand(command="id", description="🆔 Cek Telegram ID Saya"),
        BotCommand(command="help", description="💡 Panduan & Format Cepat")
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    logger.info("Tombol menu bot Telegram berhasil didaftarkan ke semua scope!")

async def main():
    # Load konfigurasi dari file .env
    load_dotenv()
    
    # 1. Inisialisasi Database SQLite
    logger.info("Menginisialisasi database SQLite...")
    init_db()

    # 2. Ambil token Telegram dari .env
    telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not telegram_token or telegram_token == "masukkan_token_botfather_disini":
        sep = "=" * 60
        logger.error(
            f"\n{sep}\n"
            "❌ TELEGRAM_TOKEN BELUM DIISI!\n"
            "Silakan buka file '.env' dan masukkan token bot Anda dari @BotFather.\n"
            "Contoh di .env:\n"
            "TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz\n"
            f"{sep}"
        )
        sys.exit(1)

    if not gemini_key or gemini_key == "masukkan_api_key_gemini_disini":
        logger.warning(
            "⚠️ PERINGATAN: GEMINI_API_KEY belum diisi atau masih menggunakan placeholder.\n"
            "Fitur OCR scan struk tidak akan aktif hingga Anda mengisi API key Gemini di file .env."
        )

    # 3. Inisialisasi Bot & Dispatcher
    bot = Bot(
        token=telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher()

    # 4. Registrasi Outer Middleware untuk Proteksi Akses (Whitelist ID Telegram)
    allowed_ids = get_allowed_telegram_ids()
    if allowed_ids:
        logger.info(f"🔒 Proteksi Whitelist Aktif! Bot hanya dapat diakses oleh Telegram ID: {allowed_ids}")
    else:
        logger.warning(
            "⚠️ PERINGATAN KEAMANAN: ALLOWED_TELEGRAM_IDS belum diatur di .env!\n"
            "Bot saat ini terbuka untuk umum. Ketik /id di bot untuk mengetahui ID Telegram Anda dan pasang di .env."
        )

    whitelist_mw = WhitelistMiddleware(allowed_ids)
    dp.message.outer_middleware(whitelist_mw)
    dp.callback_query.outer_middleware(whitelist_mw)

    # 5. Registrasi Router handlers
    dp.include_router(router)

    logger.info("Bot Telegram Keuangan Pribadi siap dijalankan! Menghapus webhook lama...")
    await bot.delete_webhook(drop_pending_updates=True)
    await set_bot_commands(bot)

    logger.info("Memulai polling pesan...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot dihentikan oleh pengguna.")
