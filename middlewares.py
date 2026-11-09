import logging
import os
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from aiogram.enums import ParseMode

logger = logging.getLogger("AuthMiddleware")

def get_allowed_telegram_ids() -> set[int]:
    """
    Mengambil daftar ID Telegram yang diizinkan dari variabel environment.
    Mendukung format koma untuk multi-ID (contoh: '12345678,87654321').
    Mendukung alias nama env: ALLOWED_TELEGRAM_IDS, TELEGRAM_ADMIN_ID, ADMIN_ID, TELEGRAM_USER_ID.
    """
    raw = (
        os.getenv("ALLOWED_TELEGRAM_IDS", "") or
        os.getenv("TELEGRAM_ADMIN_ID", "") or
        os.getenv("ADMIN_ID", "") or
        os.getenv("ADMIN_TELEGRAM_ID", "") or
        os.getenv("TELEGRAM_USER_ID", "")
    ).strip()

    allowed = set()
    if raw:
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned.isdigit():
                allowed.add(int(cleaned))
    return allowed

class WhitelistMiddleware(BaseMiddleware):
    """
    Middleware aiogram 3 untuk membatasi akses bot hanya kepada ID Telegram pemilik yang diizinkan.
    """
    def __init__(self, allowed_user_ids: set[int] | None = None):
        super().__init__()
        self.allowed_user_ids = allowed_user_ids if allowed_user_ids is not None else get_allowed_telegram_ids()

    def reload_ids(self):
        """Memuat ulang daftar ID dari environment."""
        self.allowed_user_ids = get_allowed_telegram_ids()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # 1. Selalu izinkan perintah /id atau /myid agar pengguna/pemilik bisa melihat ID Telegram-nya
        event_text = getattr(event, "text", None)
        if event_text:
            cmd = str(event_text).strip().lower()
            if cmd in ["/id", "/myid", "id", "myid"]:
                user = getattr(event, "from_user", None)
                uid = user.id if user else "Unknown"
                if hasattr(event, "reply"):
                    await event.reply(
                        f"🆔 *ID Telegram Anda:* `{uid}`\n\n"
                        "💡 *Cara Mengunci Bot:*\n"
                        "Salin ID di atas dan masukkan ke file `.env` (atau Variables di Railway):\n"
                        f"`ALLOWED_TELEGRAM_IDS={uid}`\n\n"
                        "_(Jika punya lebih dari 1 akun, pisahkan dengan koma: `ID1,ID2`)_",
                        parse_mode=ParseMode.MARKDOWN
                    )
                return

        # 2. Jika whitelist belum diatur sama sekali di .env / Railway, izinkan akses
        if not self.allowed_user_ids:
            return await handler(event, data)

        # 3. Cek apakah ID user ada di daftar whitelist
        user = getattr(event, "from_user", None)
        user_id = user.id if user else None

        if not user_id or user_id not in self.allowed_user_ids:
            username = f"@{user.username}" if user and getattr(user, "username", None) else "Tanpa Username"
            logger.warning(f"⛔ Akses Ditolak untuk Telegram ID: {user_id} ({username})")

            if hasattr(event, "reply"):
                await event.reply(
                    "⛔ *Akses Ditolak!*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "Bot pencatat keuangan ini bersifat *pribadi* dan hanya dapat diakses oleh pemiliknya.\n\n"
                    f"🆔 *ID Telegram Anda:* `{user_id}`\n\n"
                    "💡 _Jika Anda adalah pemilik bot, masukkan ID di atas ke variabel `ALLOWED_TELEGRAM_IDS` di file `.env` atau Railway Variables Anda._",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif hasattr(event, "answer"):
                await event.answer(
                    "⛔ Akses ditolak. Bot ini bersifat privat untuk pemiliknya.",
                    show_alert=True
                )
            return

        # User terdaftar di whitelist, lanjutkan ke handler
        return await handler(event, data)
