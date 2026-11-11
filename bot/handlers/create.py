"""Test yaratish: 1) nom -> 2) kalit -> 3) ball tizimi -> 4) muddat -> tasdiqlash."""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, keyparser as kp, moderation, services
from ..config import MAX_TITLE_LEN, is_admin
from ..keyboards import BTN_BACK, BTN_CREATE, NO_PREVIEW, flow_kb, home_btn, main_menu

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
    "🔑 <b>2-qadam (4 tadan): javoblar kaliti</b>\n\n"
    "Testning <b>to'g'ri javoblarini</b> bitta xabarda yuboring.\n\n"
    "<b>Variantli (A–F) savollar:</b>\n"
    "<code>abcdabcdab</code> yoki <code>1a2b3c4d</code>\n\n"
    "<b>Ochiq (yozma) javobli savollar ham bo'lsa</b> — har bir javob yangi qatordan:\n"
    "<code>1. a\n2. c\n3. 12.5\n4. x=2</code>\n\n"
    "<i>• Bitta harf (a–f) — variantli savol, boshqa qiymat — ochiq javob deb olinadi\n"
    "• Ochiq savolda bir nechta to'g'ri javob: </i><code>0.5|1/2</code>\n"
    "<i>• Ochiq javoblarda katta-kichik harf va bo'shliq farq qilmaydi, sonlar qiymati bo'yicha "
    "solishtiriladi (0,5 = 0.50 = 1/2)</i>"
)

DEADLINE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="♾ Muddatsiz — o'zim yakunlayman", callback_data="cr:d:0")],
    [InlineKeyboardButton(text="1 soat", callback_data="cr:d:60"),
     InlineKeyboardButton(text="3 soat", callback_data="cr:d:180"),
     InlineKeyboardButton(text="12 soat", callback_data="cr:d:720")],
    [InlineKeyboardButton(text="1 kun", callback_data="cr:d:1440"),
     InlineKeyboardButton(text="3 kun", callback_data="cr:d:4320"),
     InlineKeyboardButton(text="1 hafta", callback_data="cr:d:10080")],
])

POINTS_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✅ Har bir savol 1 ball", callback_data="cr:p:std")],
    [InlineKeyboardButton(text="⚖️ Savollarga alohida ball berish", callback_data="cr:p:custom")],
])


# ---------------------------------------------------------------- qadamlar
async def start_create(bot: Bot, state: FSMContext, user) -> None:
    uid = user["id"]
    if not is_admin(uid) and await db.count_tests_by_owner(uid) >= MAX_TESTS_PER_USER:
        await bot.send_message(
            uid,
            f"⚠️ Sizda {MAX_TESTS_PER_USER} ta test bor — bu eng ko'p ruxsat etilgan son.\n\n"
            "Yangi test yaratish uchun «📚 Mening testlarim» bo'limida eskilaridan o'chiring.",
            reply_markup=main_menu(uid),
        )
        return
    await state.set_state(Create.title)
    await state.set_data({})
    await _ask_title(bot, uid)


async def _ask_title(bot: Bot, user_id: int) -> None:
    await bot.send_message(
        user_id,
        "📝 <b>1-qadam (4 tadan): test nomi</b>\n\n"
        "Testga nom bering — o'quvchilar uni shu nom bilan ko'radi.\n"
        "<i>Masalan: Algebra 9-sinf, 2-nazorat ishi</i>",
        reply_markup=flow_kb(placeholder="Test nomi"),
    )


async def _show_key_step(bot: Bot, user_id: int, state: FSMContext) -> None:
    """2-qadam: kalit hali kiritilmagan bo'lsa so'raydi, kiritilgan bo'lsa ko'rsatib, 3-qadamni taklif qiladi."""
    await state.set_state(Create.key)
    questions = (await state.get_data()).get("questions")
    if not questions:
        await bot.send_message(user_id, KEY_HELP, reply_markup=flow_kb(placeholder="Javoblar kaliti"))
        return
    closed = sum(1 for q in questions if q["t"] == "c")
    lines = [
        f"✅ <b>Kalit qabul qilindi:</b> {len(questions)} ta savol "
        f"(variantli: {closed}, ochiq: {len(questions) - closed})",
        "",
        *services.key_preview(questions),
        "",
        "☝️ Kalitni ko'zdan kechiring. Xato bo'lsa — to'g'rilab, <b>qaytadan yuboring</b>.",
        "",
        "⚖️ <b>3-qadam (4 tadan): ball tizimi</b>",
        "Hammasi to'g'ri bo'lsa, ball tizimini tanlang 👇",
    ]
    await services.send_long(bot, user_id, lines, reply_markup=POINTS_KB)


async def _ask_points(bot: Bot, user_id: int, state: FSMContext) -> None:
    await state.set_state(Create.points)
    n = len((await state.get_data())["questions"])
    await bot.send_message(
        user_id,
        "⚖️ <b>3-qadam (4 tadan): savollar bali</b>\n\n"
        "Ballarni <code>savollar: ball</code> ko'rinishida yuboring.\n\n"
        "Namuna:\n<code>1-10: 1.1; 11-20: 2.1; 21-30: 3.1</code>\n"
        "Bitta savol uchun: <code>5: 2.5</code>\n\n"
        f"<i>Testda {n} ta savol bor. Ko'rsatilmagan savollar 1 balldan hisoblanadi. "
        "Kasr ballarda nuqta ishlating (2.5).</i>",
        reply_markup=flow_kb(placeholder="1-10: 1.1; 11-20: 2.1"),
    )


async def _ask_deadline(bot: Bot, user_id: int, state: FSMContext) -> None:
    await state.set_state(Create.deadline)
    await bot.send_message(
        user_id,
        "⏰ <b>4-qadam (4 tadan): javob qabul qilish muddati</b>\n\n"
        "Tugmalardan birini tanlang yoki aniq tugash vaqtini yozing:\n"
        "<code>25.12.2026 18:00</code>\n\n"
        "<i>Muddat tugagach test o'zi yakunlanadi: sizga hisobot, ishtirokchilarga yakuniy natija boradi. "
        "Muddatsiz testni istalgan payt o'zingiz yakunlaysiz.</i>",
        reply_markup=DEADLINE_KB,
    )


async def _ask_confirm(bot: Bot, user_id: int, state: FSMContext, deadline: str | None) -> None:
    await state.update_data(deadline=deadline)
    await state.set_state(Create.confirm)
    data = await state.get_data()
    questions = data["questions"]
    closed = sum(1 for q in questions if q["t"] == "c")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Testni yaratish", callback_data="cr:ok")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="cr:back"),
         InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cr:cancel")],
    ])
    await bot.send_message(
        user_id,
        "🔎 <b>Hammasi to'g'rimi?</b>\n\n"
        f"📋 Nomi: <b>{escape(data['title'])}</b>\n"
        f"❓ Savollar: <b>{len(questions)}</b> ta (variantli: {closed}, ochiq: {len(questions) - closed})\n"
        f"💯 Ball: {services.points_summary(questions)}\n"
        f"⏰ Muddat: <b>{services.to_local(deadline) + ' gacha' if deadline else 'belgilanmagan'}</b>\n\n"
        "To'g'ri bo'lsa, <b>«✅ Testni yaratish»</b>ni bosing.",
        reply_markup=kb,
    )


# ---------------------------------------------------------------- boshlash
@router.message(F.text == BTN_CREATE)
async def create_menu(message: Message, state: FSMContext, user) -> None:
    await start_create(message.bot, state, user)


@router.callback_query(F.data == "go:create")
async def create_cb(callback: CallbackQuery, state: FSMContext, user) -> None:
    await callback.answer()
    await state.clear()
    await start_create(callback.bot, state, user)


# ---------------------------------------------------------------- «Orqaga» (matnli handlerlardan oldin turishi shart)
@router.message(Create.title, F.text == BTN_BACK)
async def back_from_title(message: Message, state: FSMContext, user) -> None:
    from .start import send_menu

    await state.clear()
    await send_menu(message.bot, user["id"])


@router.message(Create.key, F.text == BTN_BACK)
async def back_from_key(message: Message, state: FSMContext, user) -> None:
    await state.set_state(Create.title)
    await _ask_title(message.bot, user["id"])


@router.message(StateFilter(Create.points, Create.deadline), F.text == BTN_BACK)
async def back_to_key(message: Message, state: FSMContext, user) -> None:
    await _show_key_step(message.bot, user["id"], state)


@router.message(Create.confirm, F.text == BTN_BACK)
async def back_from_confirm(message: Message, state: FSMContext, user) -> None:
    await _ask_deadline(message.bot, user["id"], state)


@router.callback_query(Create.confirm, F.data == "cr:back")
async def back_from_confirm_cb(callback: CallbackQuery, state: FSMContext, user) -> None:
    await callback.answer()
    await _ask_deadline(callback.bot, user["id"], state)


# ---------------------------------------------------------------- ma'lumot qabul qilish
@router.message(Create.title, F.text)
async def got_title(message: Message, state: FSMContext, user) -> None:
    title = " ".join(message.text.split())
    if not (3 <= len(title) <= MAX_TITLE_LEN):
        await message.answer(
            f"⚠️ Test nomi 3–{MAX_TITLE_LEN} belgidan iborat bo'lishi kerak "
            f"(siz yuborgani: {len(title)} belgi).\n\nQaytadan yuboring 👇"
        )
        return
    if await moderation.is_bad(title):
        await message.answer(
            "⚠️ Bu nomni qabul qila olmaymiz — unda nomaqbul so'z bor.\n\nBoshqa nom yozing 👇"
        )
        return
    await state.update_data(title=title)
    await _show_key_step(message.bot, user["id"], state)


@router.message(Create.key, F.text)
async def got_key(message: Message, state: FSMContext, user) -> None:
    try:
        questions = kp.build_questions(kp.parse_answers(message.text))
    except kp.ParseError as e:
        await message.answer(f"⚠️ {e}\n\nKalitni to'g'rilab, qaytadan yuboring 👇")
        return
    await state.update_data(questions=questions)
    await _show_key_step(message.bot, user["id"], state)


@router.callback_query(Create.key, F.data == "cr:p:std")
async def points_std(callback: CallbackQuery, state: FSMContext, user) -> None:
    data = await state.get_data()
    if not data.get("questions"):
        await callback.answer("Avval javoblar kalitini yuboring.", show_alert=True)
        return
    for q in data["questions"]:
        q["p"] = 1.0
    await state.update_data(questions=data["questions"])
    await callback.answer()
    await _ask_deadline(callback.bot, user["id"], state)


@router.callback_query(Create.key, F.data == "cr:p:custom")
async def points_custom(callback: CallbackQuery, state: FSMContext, user) -> None:
    if not (await state.get_data()).get("questions"):
        await callback.answer("Avval javoblar kalitini yuboring.", show_alert=True)
        return
    await callback.answer()
    await _ask_points(callback.bot, user["id"], state)


@router.message(Create.points, F.text)
async def got_points(message: Message, state: FSMContext, user) -> None:
    data = await state.get_data()
    questions = data["questions"]
    try:
        points = kp.parse_points(message.text, len(questions))
    except kp.ParseError as e:
        await message.answer(f"⚠️ {e}\n\nQaytadan yuboring 👇")
        return
    for q, p in zip(questions, points):
        q["p"] = p
    await state.update_data(questions=questions)
    await message.answer(f"✅ Ballar saqlandi. Maksimal ball: <b>{kp.fmt_num(sum(points))}</b>")
    await _ask_deadline(message.bot, user["id"], state)


@router.callback_query(Create.deadline, F.data.startswith("cr:d:"))
async def deadline_preset(callback: CallbackQuery, state: FSMContext, user) -> None:
    minutes = int(callback.data.split(":")[2])
    await callback.answer()
    await _ask_confirm(callback.bot, user["id"], state, services.deadline_in(minutes) if minutes else None)


@router.message(Create.deadline, F.text)
async def deadline_custom(message: Message, state: FSMContext, user) -> None:
    deadline = services.parse_local_deadline(message.text)
    if deadline is None:
        await message.answer(
            "⚠️ Sanani tushunmadim.\n\nShu ko'rinishda yozing: <code>25.12.2026 18:00</code>\n"
            "yoki yuqoridagi tugmalardan birini tanlang 👆"
        )
        return
    if deadline <= services.deadline_in(1):
        await message.answer("⚠️ Bu vaqt allaqachon o'tib ketgan. Kelajakdagi vaqtni yozing 👇")
        return
    if deadline > services.deadline_in(366 * 24 * 60):
        await message.answer("⚠️ Muddat 1 yildan oshmasligi kerak. Qaytadan yozing 👇")
        return
    await _ask_confirm(message.bot, user["id"], state, deadline)


# ---------------------------------------------------------------- yakun
@router.callback_query(Create.confirm, F.data == "cr:cancel")
async def create_cancel(callback: CallbackQuery, state: FSMContext, user) -> None:
    from .start import send_menu

    await state.clear()
    await callback.answer()
    await services.edit_or_send(callback, "❌ Test yaratish bekor qilindi.")
    await send_menu(callback.bot, user["id"])


def share_text(test, bot_username: str) -> str:
    """O'quvchilarga tarqatish uchun tayyor matn."""
    questions = services.questions_of(test)
    deadline = f"\n⏰ Muddat: {services.to_local(test['deadline'])} gacha" if test["deadline"] else ""
    return (
        f"📋 <b>{escape(test['title'])}</b>\n"
        f"❓ Savollar soni: {len(questions)} ta{deadline}\n\n"
        f"🔢 Test kodi: <code>{test['code']}</code>\n\n"
        f"Javoblarni yuborish 👉 https://t.me/{bot_username}?start=test_{test['code']}"
    )


@router.callback_query(Create.confirm, F.data == "cr:ok")
async def create_ok(callback: CallbackQuery, state: FSMContext, user) -> None:
    data = await state.get_data()
    deadline = data.get("deadline")
    if deadline and deadline <= db.now_utc():
        await callback.answer("Belgilangan muddat o'tib ketdi. Yangi muddat tanlang.", show_alert=True)
        await _ask_deadline(callback.bot, user["id"], state)
        return
    await state.clear()
    test = await db.create_test(user["id"], data["title"], data["questions"], deadline)
    services.deadlines_changed()
    await callback.answer("Test yaratildi!")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    me = await callback.bot.me()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⚙️ Testni boshqarish", callback_data=f"t:v:{test['id']}"))
    kb.row(InlineKeyboardButton(text="➕ Yana test yaratish", callback_data="go:create"), home_btn())
    await callback.bot.send_message(
        user["id"],
        f"🎉 <b>Test yaratildi!</b>\n\n🔢 Test kodi: <code>{test['code']}</code>\n\n"
        "<b>Endi nima qilinadi?</b>\n"
        "1. Pastdagi xabarni o'quvchilarga yoki kanalingizga yuboring\n"
        "2. Natijalarni «📚 Mening testlarim» bo'limida kuzating\n"
        + ("3. Muddat tugagach test o'zi yakunlanadi" if deadline else "3. Tugatmoqchi bo'lganingizda testni yakunlang"),
        reply_markup=main_menu(user["id"]),
    )
    await callback.bot.send_message(
        user["id"], share_text(test, me.username), reply_markup=kb.as_markup(), link_preview_options=NO_PREVIEW
    )
