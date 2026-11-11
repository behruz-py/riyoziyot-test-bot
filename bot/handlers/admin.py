"""Admin panel: statistika, xabar tarqatish, majburiy kanallar, bloklash."""
from __future__ import annotations

import asyncio
import logging
import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from datetime import datetime, timedelta

from .. import db, keyparser as kp, moderation, services, subscription
from ..config import ADMIN_IDS, TZ, is_admin
from ..keyboards import BTN_ADMIN, NO_PREVIEW, cancel_kb, home_btn, main_menu

log = logging.getLogger(__name__)

router = Router(name="admin")
router.message.filter(F.chat.type == "private", F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.data.startswith("adm:"), F.from_user.id.in_(ADMIN_IDS))


class Admin(StatesGroup):
    broadcast = State()
    channel = State()
    block = State()
    badword = State()


PANEL_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📊 Statistika", callback_data="adm:stats")],
    [InlineKeyboardButton(text="📢 Xabar tarqatish", callback_data="adm:bc")],
    [InlineKeyboardButton(text="📡 Majburiy kanallar", callback_data="adm:ch")],
    [InlineKeyboardButton(text="🚫 Bloklash / blokdan chiqarish", callback_data="adm:block")],
    [InlineKeyboardButton(text="🧹 Taqiqlangan so'zlar", callback_data="adm:words")],
    [home_btn()],
])
PANEL_TEXT = "🛠 <b>Admin panel</b>\n\nKerakli bo'limni tanlang 👇"
BACK_TO_PANEL = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm:panel")]]
)


@router.message(Command("admin"))
@router.message(F.text == BTN_ADMIN)
async def panel(message: Message) -> None:
    await message.answer(PANEL_TEXT, reply_markup=PANEL_KB)


@router.callback_query(F.data == "adm:panel")
async def panel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await services.edit_or_send(callback, PANEL_TEXT, PANEL_KB)
    await callback.answer()


# ---------------------------------------------------------------- statistika
def _stats_kb(current: str) -> InlineKeyboardMarkup:
    tabs = [("adm:stats", "📊 Umumiy"), ("adm:stats:week", "📈 7 kun"), ("adm:stats:top", "🏆 Eng faollar")]
    kb = InlineKeyboardBuilder()
    kb.row(*[
        InlineKeyboardButton(text=("• " + title + " •") if data == current else title, callback_data=data)
        for data, title in tabs
    ])
    kb.row(InlineKeyboardButton(text="📥 Foydalanuvchilar ro'yxati (Excel)", callback_data="adm:users_xl"))
    kb.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data=current),
           InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm:panel"))
    return kb.as_markup()


def _now_label() -> str:
    return datetime.now(TZ).strftime("%d.%m.%Y %H:%M")


@router.callback_query(F.data == "adm:stats")
async def stats(callback: CallbackQuery) -> None:
    s = await db.stats(services.local_day_start(0), services.local_day_start(6), services.local_day_start(29))
    avg = kp.fmt_num(round(s["avg_percent"], 1)) if s["avg_percent"] is not None else "—"
    text = (
        f"📊 <b>Statistika</b> · {_now_label()}\n\n"
        f"👥 <b>Foydalanuvchilar: {s['users']}</b>\n"
        f"   ro'yxatdan o'tgan: {s['registered']} · botni to'xtatgan: {s['stopped']} · "
        f"bloklangan: {s['blocked']}\n"
        f"   🆕 Yangi: bugun <b>+{s['users_new_d']}</b> · 7 kun <b>+{s['users_new_w']}</b> · "
        f"30 kun <b>+{s['users_new_m']}</b>\n"
        f"   🔥 Faol: bugun <b>{s['users_seen_d']}</b> · 7 kun <b>{s['users_seen_w']}</b> · "
        f"30 kun <b>{s['users_seen_m']}</b>\n\n"
        f"📋 <b>Testlar: {s['tests']}</b>\n"
        f"   faol: {s['active_tests']} · yakunlangan: {s['tests'] - s['active_tests']} · "
        f"mualliflar: {s['authors']}\n"
        f"   🆕 Yangi: bugun <b>+{s['tests_new_d']}</b> · 7 kun <b>+{s['tests_new_w']}</b> · "
        f"30 kun <b>+{s['tests_new_m']}</b>\n\n"
        f"✅ <b>Yuborilgan javoblar: {s['subs']}</b>\n"
        f"   ishtirokchilar: {s['solvers']} · o'rtacha natija: {avg}% · reytingdan chiqarilgan: {s['hidden']}\n"
        f"   🆕 Yangi: bugun <b>+{s['subs_new_d']}</b> · 7 kun <b>+{s['subs_new_w']}</b> · "
        f"30 kun <b>+{s['subs_new_m']}</b>\n\n"
        f"📡 Majburiy kanallar: {s['channels']}\n\n"
        "<i>«Bugun» — Toshkent vaqti bilan soat 00:00 dan. «Faol» — shu davrda botga kamida bir marta "
        "yozgan foydalanuvchilar.</i>"
    )
    await services.edit_or_send(callback, text, _stats_kb("adm:stats"))
    await callback.answer()


@router.callback_query(F.data == "adm:stats:week")
async def stats_week(callback: CallbackQuery) -> None:
    days = 7
    bounds = [services.local_day_start(i) for i in range(days - 1, -2, -1)]  # 6 kun oldin ... ertaga
    users = await db.daily_counts("users", "joined_at", bounds)
    subs = await db.daily_counts("submissions", "submitted_at", bounds)
    tests = await db.daily_counts("tests", "created_at", bounds)
    today = datetime.now(TZ).date()
    peak = max(subs) or 1
    rows = ["Kun    Yangi  Test  Javob", "─" * 34]
    for i in range(days):
        day = today - timedelta(days=days - 1 - i)
        bar = "▇" * round(subs[i] * 8 / peak)
        rows.append(f"{day:%d.%m}  {users[i]:>5} {tests[i]:>5} {subs[i]:>6}  {bar}")
    rows += ["─" * 34, f"Jami   {sum(users):>5} {sum(tests):>5} {sum(subs):>6}"]
    text = (
        f"📈 <b>Oxirgi 7 kun</b> · {_now_label()}\n\n"
        "<pre>" + "\n".join(rows) + "</pre>\n\n"
        "<i>Yangi — qo'shilgan foydalanuvchilar · Test — yaratilgan testlar · Javob — yuborilgan javoblar. "
        "Ustunchalar javoblar sonini ko'rsatadi.</i>"
    )
    await services.edit_or_send(callback, text, _stats_kb("adm:stats:week"))
    await callback.answer()


@router.callback_query(F.data == "adm:stats:top")
async def stats_top(callback: CallbackQuery) -> None:
    lines = [f"🏆 <b>Eng faollar</b> · {_now_label()}", "", "📋 <b>Eng ko'p ishtirokchili testlar</b>"]
    tests = [t for t in await db.top_tests(5) if t["participants"]]
    for i, t in enumerate(tests, start=1):
        mark = "🟢" if t["is_active"] else "🔴"
        lines.append(f"{i}. {mark} {escape(t['title'][:40])} (<code>{t['code']}</code>) — <b>{t['participants']}</b> nafar")
    if not tests:
        lines.append("Hozircha ma'lumot yo'q.")
    lines += ["", "👨‍🏫 <b>Eng faol mualliflar</b>"]
    authors = await db.top_authors(5)
    for i, a in enumerate(authors, start=1):
        name = escape(a["full_name"] or f"ID {a['id']}")
        lines.append(f"{i}. {name} — {a['tests']} ta test, <b>{a['participants']}</b> ishtirokchi")
    if not authors:
        lines.append("Hozircha ma'lumot yo'q.")
    lines += ["", "🧑‍🎓 <b>Eng ko'p test ishlaganlar</b>"]
    solvers = await db.top_solvers(5)
    for i, u in enumerate(solvers, start=1):
        name = escape(u["full_name"] or f"ID {u['id']}")
        lines.append(f"{i}. {name} — <b>{u['solved']}</b> ta test, o'rtacha {kp.fmt_num(round(u['avg_percent'], 1))}%")
    if not solvers:
        lines.append("Hozircha ma'lumot yo'q.")
    await services.edit_or_send(callback, "\n".join(lines), _stats_kb("adm:stats:top"))
    await callback.answer()


@router.callback_query(F.data == "adm:users_xl")
async def users_excel(callback: CallbackQuery) -> None:
    await callback.answer("📥 Ro'yxat tayyorlanmoqda…")
    await callback.bot.send_chat_action(callback.from_user.id, "upload_document")
    from ..excel import build_users_report

    users = [dict(u) for u in await db.users_export()]
    data = await asyncio.to_thread(build_users_report, users)
    await callback.bot.send_document(
        callback.from_user.id,
        BufferedInputFile(data, filename=f"foydalanuvchilar_{datetime.now(TZ):%Y-%m-%d}.xlsx"),
        caption=f"📥 Foydalanuvchilar ro'yxati — {len(users)} nafar",
    )


# ---------------------------------------------------------------- xabar tarqatish
@router.callback_query(F.data == "adm:bc")
async def bc_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Admin.broadcast)
    await callback.bot.send_message(
        callback.from_user.id,
        "📢 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring "
        "(matn, rasm, video — istalgan turdagi bitta xabar).",
        reply_markup=cancel_kb(),
    )


@router.message(Admin.broadcast)
async def bc_message(message: Message, state: FSMContext) -> None:
    await state.clear()
    count = len(await db.all_user_ids())
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✅ Yuborish ({count} kishi)", callback_data=f"adm:bcgo:{message.message_id}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm:bcno"),
    ]])
    await message.reply("Yuqoridagi xabar barcha foydalanuvchilarga yuborilsinmi?", reply_markup=kb)
    await message.answer("👆 Tasdiqlang yoki bekor qiling.", reply_markup=main_menu(message.from_user.id))


@router.callback_query(F.data == "adm:bcno")
async def bc_cancel(callback: CallbackQuery) -> None:
    await services.edit_or_send(callback, "❌ Xabar tarqatish bekor qilindi.", BACK_TO_PANEL)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:bcgo:"))
async def bc_go(callback: CallbackQuery) -> None:
    message_id = int(callback.data.split(":")[2])
    await services.edit_or_send(callback, "⏳ Xabar tarqatish boshlandi. Tugagach hisobot yuboraman.")
    await callback.answer()
    services.spawn(_broadcast(callback.bot, callback.from_user.id, message_id))


async def _broadcast(bot: Bot, admin_id: int, message_id: int) -> None:
    sent = blocked = failed = 0
    for uid in await db.all_user_ids():
        for attempt in range(2):
            try:
                await bot.copy_message(uid, admin_id, message_id)
                sent += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                if attempt == 1:
                    failed += 1
            except TelegramForbiddenError:
                blocked += 1
                await db.set_inactive(uid)
                break
            except TelegramAPIError as e:
                failed += 1
                log.warning("Tarqatishda xato (%s): %s", uid, e)
                break
        await asyncio.sleep(0.05)
    try:
        await bot.send_message(
            admin_id,
            f"📢 <b>Tarqatish yakunlandi</b>\n\n✅ Yetkazildi: {sent}\n🚫 Botni bloklagan: {blocked}\n⚠️ Xato: {failed}",
        )
    except TelegramAPIError:
        pass


# ---------------------------------------------------------------- majburiy kanallar
async def _channels_view():
    channels = await db.get_channels()
    kb = InlineKeyboardBuilder()
    lines = ["📡 <b>Majburiy obuna kanallari</b>", ""]
    if not channels:
        lines.append("Hozircha kanal qo'shilmagan — botdan obunasiz foydalanish mumkin.")
    for i, ch in enumerate(channels, start=1):
        lines.append(f"{i}. <a href=\"{escape(ch['url'])}\">{escape(ch['title'])}</a> (<code>{ch['chat_id']}</code>)")
        kb.row(InlineKeyboardButton(text=f"🗑 {ch['title'][:40]}", callback_data=f"adm:chdel:{ch['id']}"))
    kb.row(InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="adm:chadd"))
    kb.row(InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm:panel"))
    return "\n".join(lines), kb.as_markup()


@router.callback_query(F.data == "adm:ch")
async def channels(callback: CallbackQuery) -> None:
    text, kb = await _channels_view()
    await services.edit_or_send(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:chdel:"))
async def channel_delete(callback: CallbackQuery) -> None:
    await db.delete_channel(int(callback.data.split(":")[2]))
    subscription.invalidate()
    text, kb = await _channels_view()
    await services.edit_or_send(callback, text, kb)
    await callback.answer("Kanal ro'yxatdan o'chirildi.")


@router.callback_query(F.data == "adm:chadd")
async def channel_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Admin.channel)
    await callback.bot.send_message(
        callback.from_user.id,
        "➕ <b>Kanal qo'shish</b>\n\n"
        "1️⃣ Avval botni kanalga <b>administrator</b> qilib qo'shing.\n"
        "2️⃣ So'ng quyidagilardan birini yuboring:\n"
        "• kanal username'i: <code>@kanal_nomi</code>\n"
        "• kanaldan istalgan postni <b>forward</b> qiling (yopiq kanal uchun qulay)\n"
        "• kanal ID raqami: <code>-1001234567890</code>",
        reply_markup=cancel_kb(),
    )


def _channel_ref(message: Message) -> int | str | None:
    origin = getattr(message, "forward_origin", None)
    chat = getattr(origin, "chat", None)
    if chat is not None:
        return chat.id
    text = (message.text or "").strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    m = re.fullmatch(r"(?:https?://)?t\.me/([A-Za-z]\w{3,})/?", text) or re.fullmatch(r"@?([A-Za-z]\w{3,})", text)
    return f"@{m.group(1)}" if m else None


@router.message(Admin.channel)
async def channel_add_got(message: Message, state: FSMContext) -> None:
    ref = _channel_ref(message)
    if ref is None:
        await message.answer("⚠️ Tushunmadim. @username, kanal ID yoki kanaldan forward qilingan post yuboring:")
        return
    bot = message.bot
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
    except TelegramAPIError:
        await message.answer(
            "⚠️ Kanal topilmadi yoki bot unga qo'shilmagan. Botni kanalga administrator qilib, qaytadan yuboring:"
        )
        return
    if chat.type not in ("channel", "supergroup"):
        await message.answer("⚠️ Bu kanal yoki guruh emas. Qaytadan yuboring:")
        return
    if me.status != "administrator":
        await message.answer("⚠️ Bot bu kanalda administrator emas. Admin qilib, qaytadan yuboring:")
        return
    if chat.username:
        url = f"https://t.me/{chat.username}"
    else:
        url = chat.invite_link
        if not url:
            try:
                url = await bot.export_chat_invite_link(chat.id)
            except TelegramAPIError:
                await message.answer(
                    "⚠️ Yopiq kanal uchun botga «Foydalanuvchilarni havola orqali taklif qilish» huquqini bering "
                    "va qaytadan yuboring:"
                )
                return
    await db.add_channel(chat.id, chat.title or str(chat.id), url)
    subscription.invalidate()
    await state.clear()
    await message.answer(f"✅ <b>{escape(chat.title or '')}</b> qo'shildi.", reply_markup=main_menu(message.from_user.id))
    text, kb = await _channels_view()
    await message.answer(text, reply_markup=kb, link_preview_options=NO_PREVIEW)


# ---------------------------------------------------------------- bloklash
@router.callback_query(F.data == "adm:block")
async def block_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Admin.block)
    await callback.bot.send_message(
        callback.from_user.id,
        "🚫 Foydalanuvchining <b>ID raqamini</b> yuboring.\n\n"
        "• Bloklanmagan bo'lsa — <b>bloklanadi</b>: botdan foydalana olmaydi va barcha reytinglardan yo'qoladi\n"
        "• Bloklangan bo'lsa — <b>blokdan chiqariladi</b> va natijalari qaytadi\n\n"
        "<i>ID ni test muallifi «👥 Ishtirokchilar» bo'limida yoki shikoyat xabarida ko'radi.</i>",
        reply_markup=cancel_kb(),
    )


@router.message(Admin.block, F.text)
async def block_toggle(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    target = await db.get_user(int(text)) if text.isdigit() else None
    if target is None:
        await message.answer("⚠️ Bunday ID li foydalanuvchi topilmadi. Qaytadan yuboring:")
        return
    if is_admin(target["id"]):
        await message.answer("⚠️ Adminni bloklab bo'lmaydi. Boshqa ID yuboring yoki «❌ Bekor qilish»ni bosing.")
        return
    blocked = not target["is_blocked"]
    await db.set_blocked(target["id"], blocked)
    if blocked:
        await db.hide_user_everywhere(target["id"])
    else:
        await db.unhide_user_everywhere(target["id"])
    await state.clear()
    name = escape(target["full_name"] or target["tg_name"] or str(target["id"]))
    await message.answer(
        f"{'🚫 Bloklandi' if blocked else '✅ Blokdan chiqarildi'}: <b>{name}</b> (<code>{target['id']}</code>)",
        reply_markup=main_menu(message.from_user.id),
    )
    await message.answer(PANEL_TEXT, reply_markup=PANEL_KB)


# ---------------------------------------------------------------- shikoyat bo'yicha choralar
def _target_id(callback: CallbackQuery) -> int:
    return int(callback.data.split(":")[2])


async def _close_report(callback: CallbackQuery, verdict: str) -> None:
    """Shikoyat xabaridagi tugmalarni olib tashlab, qarorni yozib qo'yadi."""
    original = getattr(callback.message, "html_text", None) or "📣 Shikoyat"
    await services.edit_or_send(callback, f"{original}\n\n{verdict}")


@router.callback_query(F.data.startswith("adm:ban:"))
async def report_ban(callback: CallbackQuery) -> None:
    target = _target_id(callback)
    if is_admin(target):
        await callback.answer("Adminni bloklab bo'lmaydi.", show_alert=True)
        return
    await db.set_blocked(target, True)
    await db.hide_user_everywhere(target)
    await callback.answer("Bloklandi.")
    await _close_report(callback, "🚫 <b>Bloklandi</b> — botdan foydalana olmaydi, barcha reytinglardan chiqarildi.")


@router.callback_query(F.data.startswith("adm:rename:"))
async def report_rename(callback: CallbackQuery) -> None:
    target = _target_id(callback)
    await db.anonymize_user(target, f"Ishtirokchi {str(target)[-4:]}")
    await callback.answer("Ismi bekor qilindi.")
    await _close_report(
        callback, "✏️ <b>Ismi bekor qilindi</b> — eski natijalarida ismi almashtirildi, qayta ro'yxatdan o'tadi."
    )
    try:
        await callback.bot.send_message(
            target,
            "⚠️ <b>Ismingiz bekor qilindi</b>\n\n"
            "U bot qoidalariga mos kelmadi. Davom etish uchun /start ni bosing va "
            "<b>haqiqiy ism va familiyangizni</b> kiriting.\n\n"
            "<i>Qoidabuzarlik takrorlansa, hisobingiz bloklanadi.</i>",
        )
    except TelegramAPIError:
        pass


@router.callback_query(F.data == "adm:ignore")
async def report_ignore(callback: CallbackQuery) -> None:
    await callback.answer()
    await _close_report(callback, "✅ <b>E'tiborsiz qoldirildi.</b>")


# ---------------------------------------------------------------- taqiqlangan so'zlar
async def _words_view():
    words = sorted(await moderation.custom_words())
    kb = InlineKeyboardBuilder()
    for word in words[:40]:
        kb.button(text=f"🗑 {word}", callback_data=f"adm:wdel:{word}")
    kb.adjust(2)
    kb.row(InlineKeyboardButton(text="➕ So'z qo'shish", callback_data="adm:wadd"))
    kb.row(InlineKeyboardButton(text="⬅️ Admin panel", callback_data="adm:panel"))
    text = (
        "🧹 <b>Taqiqlangan so'zlar</b>\n\n"
        "Bot ism-familiya va test nomlarida so'kinish so'zlarini o'zi aniqlaydi (ichki ro'yxat: o'zbek, rus, "
        "ingliz tillarida). Bu yerda <b>qo'shimcha</b> so'zlarni kiritishingiz mumkin.\n\n"
        + (f"Siz qo'shgan so'zlar: <b>{len(words)}</b> ta. O'chirish uchun so'zni bosing 👇" if words
           else "Hozircha qo'shimcha so'z kiritilmagan.")
    )
    return text, kb.as_markup()


@router.callback_query(F.data == "adm:words")
async def words(callback: CallbackQuery) -> None:
    text, kb = await _words_view()
    await services.edit_or_send(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("adm:wdel:"))
async def word_delete(callback: CallbackQuery) -> None:
    await moderation.remove_word(callback.data.split(":", 2)[2])
    text, kb = await _words_view()
    await services.edit_or_send(callback, text, kb)
    await callback.answer("So'z o'chirildi.")


@router.callback_query(F.data == "adm:wadd")
async def word_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Admin.badword)
    await callback.bot.send_message(
        callback.from_user.id,
        "➕ Taqiqlanadigan <b>so'zni</b> yuboring (bir nechta bo'lsa — bo'shliq bilan ajrating).\n\n"
        "<i>• Kirill yoki lotinda yozishingiz mumkin — ikkalasi ham ushlanadi\n"
        "• 4 harfdan uzun so'z boshqa so'z ichida kelsa ham ushlanadi, qisqalari — faqat alohida so'z bo'lganda\n"
        "• Ehtiyot bo'ling: ismlarda uchraydigan bo'g'inni qo'shsangiz, oddiy foydalanuvchilar ham "
        "ro'yxatdan o'ta olmay qoladi</i>",
        reply_markup=cancel_kb("So'z"),
    )


@router.message(Admin.badword, F.text)
async def word_add_got(message: Message, state: FSMContext) -> None:
    added = [w for w in [await moderation.add_word(raw) for raw in message.text.split()[:20]] if w]
    if not added:
        await message.answer("⚠️ So'z 2–30 harfdan iborat bo'lishi kerak. Qaytadan yuboring 👇")
        return
    await state.clear()
    await message.answer(
        "✅ Qo'shildi: " + ", ".join(f"<code>{w}</code>" for w in added),
        reply_markup=main_menu(message.from_user.id),
    )
    text, kb = await _words_view()
    await message.answer(text, reply_markup=kb)
