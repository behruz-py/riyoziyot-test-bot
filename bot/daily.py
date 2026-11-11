"""Kunlik avtomatik ishlar: adminlarga hisobot va bazaning zaxira nusxasi."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from . import backup, config, db, keyparser as kp, services

log = logging.getLogger(__name__)

SETTING_KEY = "daily_sent"  # oxirgi yuborilgan kun (mahalliy sana) - qayta ishga tushganda takrorlanmasligi uchun


async def report_text() -> str:
    s = await db.stats(services.local_day_start(0), services.local_day_start(6), services.local_day_start(29))
    avg = kp.fmt_num(round(s["avg_percent"], 1)) if s["avg_percent"] is not None else "—"
    return (
        f"🗓 <b>Kunlik hisobot</b> · {datetime.now(config.TZ):%d.%m.%Y %H:%M}\n\n"
        "<b>Bugun:</b>\n"
        f"👥 Yangi foydalanuvchilar: <b>+{s['users_new_d']}</b>\n"
        f"🔥 Faol foydalanuvchilar: <b>{s['users_seen_d']}</b>\n"
        f"📋 Yaratilgan testlar: <b>+{s['tests_new_d']}</b>\n"
        f"✅ Yuborilgan javoblar: <b>+{s['subs_new_d']}</b>\n\n"
        "<b>Oxirgi 7 kun:</b>\n"
        f"👥 +{s['users_new_w']} foydalanuvchi · 🔥 {s['users_seen_w']} faol · "
        f"📋 +{s['tests_new_w']} test · ✅ +{s['subs_new_w']} javob\n\n"
        "<b>Jami:</b>\n"
        f"👥 {s['users']} foydalanuvchi · 📋 {s['tests']} test (faol: {s['active_tests']}) · "
        f"✅ {s['subs']} javob · o'rtacha natija {avg}%"
    )


async def backup_file() -> tuple[BufferedInputFile, str]:
    """Zaxira fayli va uning izohi."""
    data = await backup.dump()
    counts = backup.summary(data)
    name = f"zaxira_{datetime.now(config.TZ):%Y-%m-%d_%H-%M}.json.gz"
    caption = (
        "💾 <b>Bazaning zaxira nusxasi</b>\n\n"
        f"👥 {counts['users']} foydalanuvchi · 📋 {counts['tests']} test · ✅ {counts['submissions']} javob\n"
        f"Hajmi: {len(data) / 1024:.1f} KB\n\n"
        "<i>Faylni saqlab qo'ying — baza buzilsa, shu nusxadan tiklanadi. "
        "Unda foydalanuvchilar ma'lumoti bor: boshqalarga bermang.</i>"
    )
    return BufferedInputFile(data, filename=name), caption


async def send_daily(bot: Bot) -> None:
    text = await report_text()
    document, caption = await backup_file()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📊 Batafsil statistika", callback_data="adm:stats")]]
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
            await bot.send_document(admin_id, document, caption=caption)
        except TelegramAPIError as e:
            log.warning("Kunlik hisobot adminga yuborilmadi (%s): %s", admin_id, e)


async def daily_loop(bot: Bot, interval: float = 60) -> None:
    """Har kuni DAILY_HOUR dan keyin bir marta hisobot va zaxira yuboradi.

    Server o'sha payt uxlab qolgan bo'lsa - uyg'ongach yuboradi. Bazaga kuniga bir marta murojaat qilinadi.
    """
    sent_for: str | None = None
    while True:
        try:
            now = datetime.now(config.TZ)
            today = f"{now:%Y-%m-%d}"
            if config.DAILY_HOUR >= 0 and now.hour >= config.DAILY_HOUR and sent_for != today:
                if await db.get_setting(SETTING_KEY) != today:
                    await db.set_setting(SETTING_KEY, today)  # avval belgilaymiz: xato bo'lsa ham takror yubormaydi
                    await send_daily(bot)
                sent_for = today
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Kunlik hisobotda xatolik")
        await asyncio.sleep(interval)
