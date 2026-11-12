"""Spam (juda tez xabar yuborish)dan himoya.

Bitta foydalanuvchi LIMIT dan ko'p xabar/tugma bosishni PERIOD soniyada qilsa, u vaqtincha to'xtatiladi:
birinchi marta 10 soniya, qisqa vaqtda takrorlasa 1 daqiqa, keyin 5 daqiqa. To'xtatilgan payt xabarlari
e'tiborsiz qoldiriladi (bazaga murojaat ham qilinmaydi), unga faqat bir marta ogohlantirish yuboriladi.
Adminlar cheklanmaydi. Albom (bir nechta rasm birga) bitta xabar hisoblanadi.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import config

LIMIT = config.FLOOD_LIMIT     # shuncha hodisa...
PERIOD = config.FLOOD_PERIOD   # ...shuncha soniya ichida - chegaradan oshdi
PENALTIES = (10, 60, 300)      # ketma-ket buzilishlar uchun to'xtatish muddati (soniya)
PENALTY_RESET = 600            # shuncha soniya tinch tursa, jazo darajasi nolga qaytadi

clock: Callable[[], float] = time.monotonic  # sinovlarda almashtiriladi


class _State:
    __slots__ = ("events", "blocked_until", "level", "last_violation", "warned", "albums")

    def __init__(self) -> None:
        self.events: deque[float] = deque()
        self.blocked_until = 0.0
        self.level = 0
        self.last_violation = -PENALTY_RESET
        self.warned = False
        self.albums: deque[str] = deque(maxlen=5)


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self._users: dict[int, _State] = {}
        self._seen = 0

    def _cleanup(self, now: float) -> None:
        stale = [
            uid for uid, st in self._users.items()
            if st.blocked_until < now and (not st.events or now - st.events[-1] > PENALTY_RESET)
        ]
        for uid in stale:
            del self._users[uid]

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or config.is_admin(user.id):
            return await handler(event, data)

        now = clock()
        self._seen += 1
        if self._seen % 2000 == 0:
            self._cleanup(now)
        st = self._users.get(user.id)
        if st is None:
            st = self._users[user.id] = _State()

        if st.blocked_until > now:
            await self._notify(event, st, int(st.blocked_until - now) + 1)
            return None

        # Albomdagi har bir rasm alohida xabar bo'lib keladi - ularni bitta deb sanaymiz
        album = getattr(event, "media_group_id", None) if isinstance(event, Message) else None
        if album and album in st.albums:
            return await handler(event, data)
        if album:
            st.albums.append(album)

        st.events.append(now)
        while st.events and now - st.events[0] > PERIOD:
            st.events.popleft()
        if len(st.events) > LIMIT:
            if now - st.last_violation > PENALTY_RESET:
                st.level = 0
            penalty = PENALTIES[min(st.level, len(PENALTIES) - 1)]
            st.level += 1
            st.last_violation = now
            st.blocked_until = now + penalty
            st.events.clear()
            st.warned = False
            await self._notify(event, st, penalty)
            return None
        return await handler(event, data)

    @staticmethod
    async def _notify(event: TelegramObject, st: _State, seconds: int) -> None:
        wait = f"{seconds} soniya" if seconds < 60 else f"{(seconds + 59) // 60} daqiqa"
        try:
            if isinstance(event, CallbackQuery):
                # Tugma "aylanib" qolmasligi uchun har doim javob beramiz
                await event.answer(f"⏳ Juda tez bosyapsiz. {wait} kuting.", show_alert=not st.warned)
                st.warned = True
            elif isinstance(event, Message) and not st.warned:
                st.warned = True
                await event.answer(
                    f"⏳ <b>Juda tez xabar yuboryapsiz.</b>\n\n"
                    f"Bot {wait} davomida xabarlaringizga javob bermaydi. Keyin odatdagidek davom eting.\n"
                    "<i>Qayta takrorlansa, kutish vaqti uzayadi.</i>"
                )
        except Exception:
            pass
