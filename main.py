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

    # 4. Registrasi Router handlers
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
