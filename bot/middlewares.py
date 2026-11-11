from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import db, subscription
from .config import is_admin
from .keyboards import MENU_BUTTONS, subscribe_kb

SUB_TEXT = (
    "🔒 Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo'ling, "
    "so'ng <b>«✅ Obuna bo'ldim»</b> tugmasini bosing:"
)


class UserMiddleware(BaseMiddleware):
    """Foydalanuvchini ro'yxatga oladi, bloklanganlarni to'xtatadi, menyu tugmasi bosilganda holatni tozalaydi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        chat = data.get("event_chat")
        if tg_user is None or tg_user.is_bot or chat is None or chat.type != "private":
            return None
        user = await db.touch_user(tg_user.id, tg_user.username, tg_user.full_name)
        if user["is_blocked"] and not is_admin(tg_user.id):
            return None
        data["user"] = user

        state = data.get("state")
        if isinstance(event, Message) and event.text and state is not None:
            if event.text in MENU_BUTTONS or event.text.startswith("/"):
                await state.clear()
                data["raw_state"] = None
        return await handler(event, data)


class SubscriptionMiddleware(BaseMiddleware):
    """Majburiy kanallarga obuna bo'lmaganlarni o'tkazmaydi."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data["user"]
        uid = user["id"]
        if is_admin(uid):
            return await handler(event, data)

        is_check = isinstance(event, CallbackQuery) and event.data == "check_sub"
        missing = await subscription.missing_channels(data["bot"], uid, force=is_check)
        if not missing:
            return await handler(event, data)

        if isinstance(event, Message):
            if event.text and event.text.startswith("/start "):
                subscription.PENDING_START[uid] = event.text.split(maxsplit=1)[1].strip()
            await event.answer(SUB_TEXT, reply_markup=subscribe_kb(missing))
        elif isinstance(event, CallbackQuery):
            if is_check:
                await event.answer("❗️ Siz hali barcha kanallarga obuna bo'lmadingiz.", show_alert=True)
                if event.message:
                    try:
                        await event.message.edit_reply_markup(reply_markup=subscribe_kb(missing))
                    except Exception:
                        pass
            else:
                await event.answer("Avval kanal(lar)ga obuna bo'ling.", show_alert=True)
                if event.message:
                    await event.message.answer(SUB_TEXT, reply_markup=subscribe_kb(missing))
        return None
