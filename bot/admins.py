"""Adminlar ro'yxatini boshqarish.

Ikki xil admin bor:
  - bosh adminlar: .env / Render'dagi ADMIN_IDS. Bot ichidan o'chirib bo'lmaydi, faqat ular admin qo'shadi/o'chiradi.
  - oddiy adminlar: bot ichidan qo'shiladi, bazada (admins jadvali) saqlanadi.

config.ADMIN_IDS - barcha adminlarning "jonli" to'plami: filtrlar aynan shu obyektga qaraydi,
shuning uchun u almashtirilmaydi, faqat ichidagi qiymatlar o'zgartiriladi.
"""
from __future__ import annotations

from . import config, db


def is_super(user_id: int) -> bool:
    return user_id in config.SUPER_ADMIN_IDS


async def load() -> None:
    """Bot ishga tushganda bazadagi adminlarni xotiraga yuklaydi."""
    stored = {row["user_id"] for row in await db.get_admins()}
    config.ADMIN_IDS.clear()
    config.ADMIN_IDS.update(config.SUPER_ADMIN_IDS | stored)


async def add(user_id: int, added_by: int) -> None:
    await db.add_admin(user_id, added_by)
    config.ADMIN_IDS.add(user_id)


async def remove(user_id: int) -> bool:
    """Oddiy adminni o'chiradi. Bosh adminni o'chirib bo'lmaydi (False)."""
    if is_super(user_id):
        return False
    await db.remove_admin(user_id)
    config.ADMIN_IDS.discard(user_id)
    return True
