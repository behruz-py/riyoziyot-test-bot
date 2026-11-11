"""Test yaratish: nom -> kalit -> ball tizimi -> muddat -> tasdiqlash."""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, keyparser as kp, services
from ..config import MAX_TITLE_LEN, is_admin
from ..keyboards import BTN_CREATE, NO_PREVIEW, cancel_kb, main_menu

router = Router(name="create")
router.message.filter(F.chat.type == "private")

MAX_TESTS_PER_USER = 100


class Create(StatesGroup):
    title = State()
    key = State()
    points = State()
    deadline = State()
    confirm = State()


KEY_HELP = (
    "🔑 Endi <b>to'g'ri javoblar kalitini</b> yuboring.\n\n"
    "<b>Faqat variantli (A–F) savollar bo'lsa:</b>\n"
    "<code>abcdabcdab</code> yoki <code>1a2b3c4d</code>\n\n"
    "<b>Ochiq (yozma) javobli savollar ham bo'lsa</b> — har bir javob yangi qatordan:\n"
    "<code>1. a\n2. c\n3. 12.5\n4. x=2</code>\n"
    "Bitta harf (a–f) — variantli savol, boshqa har qanday qiymat — ochiq javob deb olinadi.\n"
    "Ochiq savolda bir nechta to'g'ri javob bo'lsa <code>|</code> bilan ajrating: <code>0.5|1/2</code>\n\n"
    "<i>Ochiq javoblar tekshirilganda katta-kichik harf va bo'shliqlar hisobga olinmaydi, "
    "sonlar qiymati bo'yicha solishtiriladi (0,5 = 0.50 = 1/2).</i>"
)

DEADLINE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="♾ Muddatsiz (o'zim yakunlayman)", callback_data="cr:d:0")],
    [InlineKeyboardButton(text="1 soat", callback_data="cr:d:60"),
     InlineKeyboardButton(text="3 soat", callback_data="cr:d:180"),
     InlineKeyboardButton(text="12 soat", callback_data="cr:d:720")],
    [InlineKeyboardButton(text="1 kun", callback_data="cr:d:1440"),
     InlineKeyboardButton(text="3 kun", callback_data="cr:d:4320"),
     InlineKeyboardButton(text="1 hafta", callback_data="cr:d:10080")],
])


@router.message(F.text == BTN_CREATE)
async def start_create(message: Message, state: FSMContext, user) -> None:
    if not is_admin(user["id"]) and await db.count_tests_by_owner(user["id"]) >= MAX_TESTS_PER_USER:
        await message.answer(
            f"Sizda {MAX_TESTS_PER_USER} ta test bor. Yangi test yaratish uchun eskilaridan o'chiring "
            "(«📚 Mening testlarim»)."
        )
        return
    await state.set_state(Create.title)
    await message.answer(
        "📝 <b>Yangi test</b>\n\nTest nomini yuboring (masalan: <i>Algebra 9-sinf, 2-nazorat ishi</i>):",
        reply_markup=cancel_kb(),
    )


@router.message(Create.title, F.text)
async def got_title(message: Message, state: FSMContext) -> None:
    title = " ".join(message.text.split())
    if not (3 <= len(title) <= MAX_TITLE_LEN):
        await message.answer(f"Test nomi 3–{MAX_TITLE_LEN} belgidan iborat bo'lishi kerak. Qaytadan yuboring:")
        return
    await state.update_data(title=title)
    await state.set_state(Create.key)
    await message.answer(KEY_HELP)


@router.message(Create.key, F.text)
async def got_key(message: Message, state: FSMContext) -> None:
    try:
        questions = kp.build_questions(kp.parse_answers(message.text))
    except kp.ParseError as e:
        await message.answer(f"⚠️ {e}\n\nKalitni qaytadan yuboring:")
        return
    await state.update_data(questions=questions)
    closed = sum(1 for q in questions if q["t"] == "c")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Har bir savol 1 ball", callback_data="cr:p:std")],
        [InlineKeyboardButton(text="⚖️ Savollarga alohida ball berish", callback_data="cr:p:custom")],
    ])
    lines = [
        f"✅ Kalit qabul qilindi: <b>{len(questions)}</b> ta savol "
        f"(variantli: {closed}, ochiq: {len(questions) - closed})",
        "",
        *services.key_preview(questions),
        "",
        "☝️ Kalitni tekshiring. Xato bo'lsa — to'g'rilab, qaytadan yuboring.",
        "To'g'ri bo'lsa, <b>ball tizimini</b> tanlang:",
    ]
    await services.send_long(message.bot, message.chat.id, lines, reply_markup=kb)


async def _ask_deadline(bot: Bot, chat_id: int, state: FSMContext) -> None:
    await state.set_state(Create.deadline)
    await bot.send_message(
        chat_id,
        "⏰ <b>Javoblar qabul qilish muddati</b>\n\n"
        "Quyidagilardan birini tanlang yoki aniq tugash vaqtini yozib yuboring:\n"
        "<code>25.12.2026 18:00</code>\n\n"
        "<i>Muddat tugagach test avtomatik yakunlanadi: sizga hisobot, ishtirokchilarga yakuniy "
        "natija yuboriladi. Muddatsiz testni istalgan payt o'zingiz yakunlaysiz.</i>",
        reply_markup=DEADLINE_KB,
    )


@router.callback_query(Create.key, F.data == "cr:p:std")
async def points_std(callback: CallbackQuery, state: FSMContext) -> None:
    if not (await state.get_data()).get("questions"):
        await callback.answer("Avval kalitni yuboring.", show_alert=True)
        return
    await callback.answer()
    await _ask_deadline(callback.bot, callback.from_user.id, state)


@router.callback_query(Create.key, F.data == "cr:p:custom")
async def points_custom(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("questions"):
        await callback.answer("Avval kalitni yuboring.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(Create.points)
    n = len(data["questions"])
    await callback.bot.send_message(
        callback.from_user.id,
        "⚖️ Ballarni <code>savollar: ball</code> ko'rinishida yuboring.\n\n"
        "Namuna:\n<code>1-10: 1.1; 11-20: 2.1; 21-30: 3.1</code>\n"
        "yoki bitta savol uchun: <code>5: 2.5</code>\n\n"
        f"Testda {n} ta savol bor. Ko'rsatilmagan savollar 1 balldan hisoblanadi.",
    )


@router.message(Create.points, F.text)
async def got_points(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    questions = data["questions"]
    try:
        points = kp.parse_points(message.text, len(questions))
    except kp.ParseError as e:
        await message.answer(f"⚠️ {e}\n\nQaytadan yuboring:")
        return
    for q, p in zip(questions, points):
        q["p"] = p
    await state.update_data(questions=questions)
    await message.answer(f"✅ Ballar saqlandi. Maksimal ball: <b>{kp.fmt_num(sum(points))}</b>")
    await _ask_deadline(message.bot, message.chat.id, state)


async def _ask_confirm(bot: Bot, chat_id: int, state: FSMContext, deadline: str | None) -> None:
    await state.update_data(deadline=deadline)
    await state.set_state(Create.confirm)
    data = await state.get_data()
    questions = data["questions"]
    closed = sum(1 for q in questions if q["t"] == "c")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yaratish", callback_data="cr:ok"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cr:cancel"),
    ]])
    await bot.send_message(
        chat_id,
        "🔎 <b>Tekshirib oling:</b>\n\n"
        f"📋 Nomi: <b>{escape(data['title'])}</b>\n"
        f"❓ Savollar: <b>{len(questions)}</b> ta (variantli: {closed}, ochiq: {len(questions) - closed})\n"
        f"💯 Ball: {services.points_summary(questions)}\n"
        f"⏰ Muddat: <b>{services.to_local(deadline) + ' gacha' if deadline else 'belgilanmagan'}</b>",
        reply_markup=kb,
    )


@router.callback_query(Create.deadline, F.data.startswith("cr:d:"))
async def deadline_preset(callback: CallbackQuery, state: FSMContext) -> None:
    minutes = int(callback.data.split(":")[2])
    await callback.answer()
    await _ask_confirm(callback.bot, callback.from_user.id, state, services.deadline_in(minutes) if minutes else None)


@router.message(Create.deadline, F.text)
async def deadline_custom(message: Message, state: FSMContext) -> None:
    deadline = services.parse_local_deadline(message.text)
    if deadline is None:
        await message.answer("⚠️ Format noto'g'ri. Namuna: <code>25.12.2026 18:00</code>\nQaytadan yuboring:")
        return
    if deadline <= services.deadline_in(1):
        await message.answer("⚠️ Muddat kelajakdagi vaqt bo'lishi kerak. Qaytadan yuboring:")
        return
    if deadline > services.deadline_in(366 * 24 * 60):
        await message.answer("⚠️ Muddat 1 yildan oshmasligi kerak. Qaytadan yuboring:")
        return
    await _ask_confirm(message.bot, message.chat.id, state, deadline)


@router.callback_query(Create.confirm, F.data == "cr:cancel")
async def create_cancel(callback: CallbackQuery, state: FSMContext, user) -> None:
    await state.clear()
    await callback.answer()
    await services.edit_or_send(callback, "❌ Test yaratish bekor qilindi.")
    await callback.bot.send_message(user["id"], "🏠 Asosiy menyu", reply_markup=main_menu(user["id"]))


def share_text(test, bot_username: str) -> str:
    """O'quvchilarga tarqatish uchun tayyor matn."""
    questions = services.questions_of(test)
    deadline = f"\n⏰ Muddat: {services.to_local(test['deadline'])} gacha" if test["deadline"] else ""
    return (
        f"📋 <b>{escape(test['title'])}</b>\n"
        f"❓ Savollar soni: {len(questions)} ta{deadline}\n\n"
        f"🔢 Test kodi: <code>{test['code']}</code>\n\n"
        f"Javoblarni yuborish: 👉 https://t.me/{bot_username}?start=test_{test['code']}"
    )


@router.callback_query(Create.confirm, F.data == "cr:ok")
async def create_ok(callback: CallbackQuery, state: FSMContext, user) -> None:
    data = await state.get_data()
    await state.clear()
    deadline = data.get("deadline")
    if deadline and deadline <= db.now_utc():
        await callback.answer("Muddat o'tib ketdi. Testni qaytadan yarating.", show_alert=True)
        return
    test = await db.create_test(user["id"], data["title"], data["questions"], deadline)
    services.deadlines_changed()
    await callback.answer("Test yaratildi!")
    await services.edit_or_send(callback, "✅ Tasdiqlandi.")
    me = await callback.bot.me()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⚙️ Testni boshqarish", callback_data=f"t:v:{test['id']}"))
    await callback.bot.send_message(
        user["id"],
        f"🎉 <b>Test yaratildi!</b>\n\n🔢 Test kodi: <code>{test['code']}</code>\n\n"
        "Quyidagi xabarni o'quvchilaringizga yoki kanalingizga yuboring 👇",
        reply_markup=main_menu(user["id"]),
    )
    await callback.bot.send_message(
        user["id"], share_text(test, me.username), reply_markup=kb.as_markup(), link_preview_options=NO_PREVIEW
    )
