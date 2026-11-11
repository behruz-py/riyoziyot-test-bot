"""Majburiy kanallarga obunani tekshirish."""
from __future__ import annotations

import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from . import db
from .config import SUB_CACHE_TTL

log = logging.getLogger(__name__)

_channels_cache: list | None = None
_ok_until: dict[int, float] = {}  # user_id -> obuna tasdiqlangan vaqt tugashi

# /start havolasi bilan kelib, obuna yoki ro'yxatdan o'tishda to'xtab qolganlar uchun
PENDING_START: dict[int, str] = {}


async def get_channels() -> list:
    global _channels_cache
    if _channels_cache is None:
        _channels_cache = list(await db.get_channels())
    return _channels_cache


def invalidate() -> None:
    """Kanallar ro'yxati o'zgarganda chaqiriladi."""
    global _channels_cache
    _channels_cache = None
    _ok_until.clear()


async def missing_channels(bot: Bot, user_id: int, force: bool = False) -> list:
    """Foydalanuvchi obuna bo'lmagan kanallar ro'yxati."""
    channels = await get_channels()
    if not channels:
        return []
    now = time.monotonic()
    if not force and _ok_until.get(user_id, 0) > now:
        return []
    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["chat_id"], user_id)
        except TelegramAPIError as e:
            # Bot kanalda admin emas yoki kanal o'chirilgan: botni ishdan chiqarmaslik uchun o'tkazib yuboramiz
            log.warning("Kanalni tekshirib bo'lmadi (%s, %s): %s", ch["title"], ch["chat_id"], e)
            continue
        status = member.status
        if status in ("left", "kicked") or (status == "restricted" and not getattr(member, "is_member", False)):
            missing.append(ch)
    if missing:
        _ok_until.pop(user_id, None)
    else:
        if len(_ok_until) > 50_000:
            _ok_until.clear()
        _ok_until[user_id] = now + SUB_CACHE_TTL
    return missing
