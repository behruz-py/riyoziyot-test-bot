"""Test yaratish: nom -> kalit -> [ball tizimi] -> [muddat] -> tasdiqlash.

Qavsdagi qadamlar admin paneldagi funksiyalar yoqilgan bo'lsagina ko'rsatiladi (features.py)."""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, features, keyparser as kp, moderation, services
from ..config import MAX_TITLE_LEN, is_admin
from ..keyboards import BTN_BACK, BTN_CREATE, NO_PREVIEW, cancel_kb, flow_kb, home_btn, main_menu

router = Router(name="create")
router.message.filter(F.chat.type == "private")

MAX_TESTS_PER_USER = 100


MAX_NOTE_LEN = 500


class PostNote(StatesGroup):
    text = State()


class Create(StatesGroup):
    title = State()
    key = State()
    points = State()
    deadline = State()
    confirm = State()


KEY_EXAMPLES_OPEN = (
    "\n\n<b>Ochiq (yozma) javobli savollar ham bo'lsa</b> — har bir javob yangi qatordan:\n"
    "<code>1. A\n2. C\n3. 12.5\n4. x=2</code>\n"
    "<i>• Bitta harf (A–D) — variantli savol, boshqa qiymat — ochiq javob deb olinadi\n"
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
CONTINUE_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➡️ Davom etish", callback_data="cr:p:std")],
])


# ---------------------------------------------------------------- qadamlar (soni yoqilgan funksiyalarga bog'liq)
def _steps() -> list[str]:
    steps = ["title", "key"]
    if features.on("custom_points"):
        steps.append("points")
    if features.on("deadline"):
        steps.append("deadline")
    return steps


def _step(name: str) -> str:
    steps = _steps()
    return f"{steps.index(name) + 1}-qadam ({len(steps)} tadan)" if name in steps else "Qadam"


def key_help() -> str:
    open_ok = features.on("open_questions")
    return (
        f"🔑 <b>{_step('key')}: javoblar kaliti</b>\n\n"
        "Testning <b>to'g'ri javoblarini</b> bitta xabarda yuboring — har bir savol uchun bitta harf: "
        "<b>A, B, C yoki D</b>.\n\n"
        "Namuna:\n<code>1A2B3C4D5A…</code>  yoki  <code>ABCDA…</code>\n\n"
        "<i>• Katta yoki kichik harf bilan yozish farq qilmaydi\n"
        "• Bo'shliq va yangi qatorlar ham mumkin: </i><code>1A 2B 3C</code>\n"
        "<i>• Savollar ko'p bo'lsa, xabarni bo'laklab emas, bittada yuboring (200 tagacha)</i>"
        + (KEY_EXAMPLES_OPEN if open_ok else "")
    )


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
        f"📝 <b>{_step('title')}: test nomi</b>\n\n"
        "Testga nom bering — o'quvchilar uni shu nom bilan ko'radi.\n"
        "<i>Masalan: Algebra 9-sinf, 2-nazorat ishi</i>",
        reply_markup=flow_kb(placeholder="Test nomi"),
    )


async def _show_key_step(bot: Bot, user_id: int, state: FSMContext) -> None:
    """Kalit qadami: kalit hali kiritilmagan bo'lsa so'raydi, kiritilgan bo'lsa ko'rsatib, keyingi qadamni taklif qiladi."""
    await state.set_state(Create.key)
    questions = (await state.get_data()).get("questions")
    if not questions:
        await bot.send_message(user_id, key_help(), reply_markup=flow_kb(placeholder="Javoblar kaliti"))
        return
    lines = [
        f"✅ <b>Kalit qabul qilindi:</b> {services.questions_count(questions, noun=True)}",
        "",
        *services.key_preview(questions),
        "",
        "☝️ Kalitni ko'zdan kechiring. Xato bo'lsa — to'g'rilab, <b>qaytadan yuboring</b>.",
        "",
    ]
    if features.on("custom_points"):
        lines += [f"⚖️ <b>{_step('points')}: ball tizimi</b>", "Hammasi to'g'ri bo'lsa, ball tizimini tanlang 👇"]
        markup = POINTS_KB
    else:
        lines.append("Hammasi to'g'ri bo'lsa, davom eting 👇")
        markup = CONTINUE_KB
    await services.send_long(bot, user_id, lines, reply_markup=markup)


async def _ask_points(bot: Bot, user_id: int, state: FSMContext) -> None:
    await state.set_state(Create.points)
    n = len((await state.get_data())["questions"])
    await bot.send_message(
        user_id,
        f"⚖️ <b>{_step('points')}: savollar bali</b>\n\n"
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
        f"⏰ <b>{_step('deadline')}: javob qabul qilish muddati</b>\n\n"
        "Tugmalardan birini tanlang yoki aniq tugash vaqtini yozing:\n"
        "<code>25.12.2026 18:00</code>\n\n"
        "<i>Muddat tugagach test o'zi yakunlanadi: sizga hisobot, ishtirokchilarga yakuniy natija boradi. "
        "Muddatsiz testni istalgan payt o'zingiz yakunlaysiz.</i>",
        reply_markup=DEADLINE_KB,
    )


async def _after_points(bot: Bot, user_id: int, state: FSMContext) -> None:
    """Ball qadamidan keyingi qadam: muddat (yoqilgan bo'lsa) yoki to'g'ridan-to'g'ri tasdiqlash."""
    if features.on("deadline"):
        await _ask_deadline(bot, user_id, state)
    else:
        await _ask_confirm(bot, user_id, state, None)


async def _back_from_confirm(bot: Bot, user_id: int, state: FSMContext) -> None:
    if features.on("deadline"):
        await _ask_deadline(bot, user_id, state)
    else:
        await _show_key_step(bot, user_id, state)


async def _ask_confirm(bot: Bot, user_id: int, state: FSMContext, deadline: str | None) -> None:
    await state.update_data(deadline=deadline)
    await state.set_state(Create.confirm)
    data = await state.get_data()
    questions = data["questions"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Testni yaratish", callback_data="cr:ok")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="cr:back"),
         InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cr:cancel")],
    ])
    lines = [
        "🔎 <b>Hammasi to'g'rimi?</b>",
        "",
        f"📋 Nomi: <b>{escape(data['title'])}</b>",
        f"❓ Savollar: <b>{services.questions_count(questions)}</b>",
        f"💯 Ball: {services.points_summary(questions)}",
    ]
    if features.on("deadline") or deadline:
        lines.append(f"⏰ Muddat: <b>{services.to_local(deadline) + ' gacha' if deadline else 'belgilanmagan'}</b>")
    lines += ["", "To'g'ri bo'lsa, <b>«✅ Testni yaratish»</b>ni bosing."]
    await bot.send_message(user_id, "\n".join(lines), reply_markup=kb)


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
    await _back_from_confirm(message.bot, user["id"], state)


@router.callback_query(Create.confirm, F.data == "cr:back")
async def back_from_confirm_cb(callback: CallbackQuery, state: FSMContext, user) -> None:
    await callback.answer()
    await _back_from_confirm(callback.bot, user["id"], state)


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
        questions = kp.build_questions(kp.parse_answers(message.text), allow_open=features.on("open_questions"))
    except kp.ParseError as e:
        await message.answer(f"⚠️ {e}\n\nKalitni to'g'rilab, qaytadan yuboring 👇")
        return
    await state.update_data(questions=questions)
    await _show_key_step(message.bot, user["id"], state)


@router.callback_query(Create.key, F.data.in_({"cr:p:std", "cr:p:custom"}))
async def points_choice(callback: CallbackQuery, state: FSMContext, user) -> None:
    data = await state.get_data()
    if not data.get("questions"):
        await callback.answer("Avval javoblar kalitini yuboring.", show_alert=True)
        return
    await callback.answer()
    if callback.data == "cr:p:custom" and features.on("custom_points"):
        await _ask_points(callback.bot, user["id"], state)
        return
    for q in data["questions"]:
        q["p"] = 1.0
    await state.update_data(questions=data["questions"])
    await _after_points(callback.bot, user["id"], state)


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
    await _after_points(message.bot, user["id"], state)


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


# ---------------------------------------------------------------- o'quvchilar uchun tayyor post
async def build_post(bot: Bot, test) -> tuple[str, InlineKeyboardMarkup]:
    """Forward qilinadigan post: test haqida ma'lumot va «Javoblarni yuborish» tugmasi."""
    questions = services.questions_of(test)
    owner = await db.get_user(test["owner_id"])
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=test_{test['code']}"
    lines = [f"📝 <b>{escape(test['title'])}</b>", ""]
    if test["note"] and features.on("post_note"):
        lines += [escape(test["note"]), ""]
    lines.append(f"❓ Savollar soni: <b>{len(questions)} ta</b>")
    lines.append(f"💯 Ball: {services.points_summary(questions)}")
    if test["deadline"]:
        lines.append(f"⏰ Javoblar qabul qilinadi: <b>{services.to_local(test['deadline'])}</b> gacha")
    if owner and owner["full_name"]:
        lines.append(f"👨‍🏫 Muallif: {escape(owner['full_name'])}")
    lines += [
        "",
        f"🔢 Test kodi: <code>{test['code']}</code>",
        "",
        "📲 <b>Qanday qatnashiladi?</b>",
        f"Pastdagi tugmani bosing yoki @{me.username} ga test kodini yuboring. "
        "Javoblar namunasi: <code>1A2B3C4D…</code>",
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Javoblarni yuborish", url=link)]])
    return "\n".join(lines), kb


async def send_post(bot: Bot, user_id: int, test, created: bool = False) -> None:
    """Postni va uning ostida muallif uchun boshqaruv tugmalarini yuboradi."""
    text, kb = await build_post(bot, test)
    await bot.send_message(user_id, text, reply_markup=kb, link_preview_options=NO_PREVIEW)
    tid = test["id"]
    controls = InlineKeyboardBuilder()
    note_on = features.on("post_note")
    if note_on:
        controls.row(InlineKeyboardButton(text="✍️ Izohni o'zgartirish" if test["note"] else "✍️ Izoh qo'shish",
                                          callback_data=f"t:note:{tid}"))
    if note_on and test["note"]:
        controls.row(InlineKeyboardButton(text="🗑 Izohni olib tashlash", callback_data=f"t:notedel:{tid}"))
    controls.row(InlineKeyboardButton(text="⚙️ Testni boshqarish", callback_data=f"t:v:{tid}"))
    if created:
        controls.row(InlineKeyboardButton(text="➕ Yana test yaratish", callback_data="go:create"), home_btn())
    else:
        controls.row(home_btn())
    await bot.send_message(
        user_id,
        "👆 <b>O'quvchilar uchun tayyor post.</b>\n\n"
        "Uni o'quvchilaringizga yoki kanal/guruhingizga <b>forward</b> qiling — «✅ Javoblarni yuborish» "
        "tugmasi ham birga o'tadi: bosgan odamga bot darhol shu testni ochadi."
        + ("\n\n<i>Postga o'z izohingizni qo'shishingiz mumkin, masalan: «9-B sinf, 2-chorak nazorat ishi. "
           "Omad!»</i>" if note_on else ""),
        reply_markup=controls.as_markup(),
    )


async def _post_test(callback: CallbackQuery, user):
    test = await db.get_test(int(callback.data.split(":")[2]))
    if test is None:
        await callback.answer("Test topilmadi — o'chirilgan bo'lishi mumkin.", show_alert=True)
        return None
    if test["owner_id"] != user["id"] and not is_admin(user["id"]):
        await callback.answer("Bu test sizga tegishli emas.", show_alert=True)
        return None
    return test


@router.callback_query(F.data.startswith("t:post:"))
async def post_cb(callback: CallbackQuery, state: FSMContext, user) -> None:
    test = await _post_test(callback, user)
    if test is None:
        return
    await state.clear()
    await callback.answer()
    await send_post(callback.bot, user["id"], test)


@router.callback_query(F.data.startswith("t:note:"))
async def note_ask(callback: CallbackQuery, state: FSMContext, user) -> None:
    if not features.on("post_note"):
        await callback.answer(features.OFF_TEXT, show_alert=True)
        return
    test = await _post_test(callback, user)
    if test is None:
        return
    await callback.answer()
    await state.set_state(PostNote.text)
    await state.set_data({"test_id": test["id"]})
    current = f"\n\nHozirgi izoh:\n<i>{escape(test['note'])}</i>" if test["note"] else ""
    await callback.bot.send_message(
        user["id"],
        "✍️ <b>Postga izoh</b>\n\n"
        f"Postda test nomidan keyin chiqadigan matnni yuboring (ko'pi bilan {MAX_NOTE_LEN} belgi).\n"
        "<i>Masalan: 9-B sinf o'quvchilari, 2-chorak nazorat ishi. Javoblarni soat 18:00 gacha yuboring. "
        "Omad!</i>" + current,
        reply_markup=cancel_kb("Izoh matni"),
    )
    await callback.bot.send_message(
        user["id"], "Yoki postga qayting 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ Postga qaytish", callback_data=f"t:post:{test['id']}"),
        ]]),
    )


@router.message(PostNote.text, F.text)
async def note_got(message: Message, state: FSMContext, user) -> None:
    test = await db.get_test((await state.get_data()).get("test_id") or 0)
    if test is None or (test["owner_id"] != user["id"] and not is_admin(user["id"])):
        await state.clear()
        await message.answer("❌ Test topilmadi.", reply_markup=main_menu(user["id"]))
        return
    note = "\n".join(" ".join(line.split()) for line in message.text.strip().splitlines()).strip()
    while "\n\n\n" in note:
        note = note.replace("\n\n\n", "\n\n")
    if len(note) > MAX_NOTE_LEN:
        await message.answer(
            f"⚠️ Izoh juda uzun: {len(note)} belgi (ko'pi bilan {MAX_NOTE_LEN}). Qisqartirib, qaytadan yuboring 👇"
        )
        return
    if len(note) < 2:
        await message.answer("⚠️ Izoh juda qisqa. Qaytadan yuboring 👇")
        return
    if await moderation.is_bad(note):
        await message.answer("⚠️ Izohda nomaqbul so'z bor. Boshqacha yozib, qaytadan yuboring 👇")
        return
    await db.set_note(test["id"], note)
    await state.clear()
    await message.answer("✅ Izoh saqlandi. Yangilangan post 👇", reply_markup=main_menu(user["id"]))
    await send_post(message.bot, user["id"], await db.get_test(test["id"]))


@router.callback_query(F.data.startswith("t:notedel:"))
async def note_delete(callback: CallbackQuery, state: FSMContext, user) -> None:
    test = await _post_test(callback, user)
    if test is None:
        return
    await state.clear()
    await db.set_note(test["id"], None)
    await callback.answer("Izoh olib tashlandi.")
    await send_post(callback.bot, user["id"], await db.get_test(test["id"]))


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
    await callback.bot.send_message(
        user["id"],
        f"🎉 <b>Test yaratildi!</b>\n\n🔢 Test kodi: <code>{test['code']}</code>\n\n"
        "<b>Endi nima qilinadi?</b>\n"
        "1. Pastdagi postni o'quvchilarga yoki kanalingizga forward qiling\n"
        "2. Natijalarni «📚 Mening testlarim» bo'limida kuzating\n"
        + ("3. Muddat tugagach test o'zi yakunlanadi" if deadline else "3. Tugatmoqchi bo'lganingizda testni yakunlang"),
        reply_markup=main_menu(user["id"]),
    )
    await send_post(callback.bot, user["id"], test, created=True)
