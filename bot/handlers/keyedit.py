"""Test kalitini va ballarini tahrirlash, barcha natijalarni qayta hisoblash.

Oqim: test sahifasi -> «✏️ Kalitni tahrirlash» -> (ayrim savollar | butun kalit | ballar)
      -> o'zgarishlar va ta'sirini ko'rish -> saqlash (ixtiyoriy: ishtirokchilarga xabar).
"""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, features, keyparser as kp, services
from ..config import is_admin
from ..keyboards import cancel_kb, main_menu

router = Router(name="keyedit")
router.message.filter(F.chat.type == "private")

MAX_DIFF_LINES = 40


class KeyEdit(StatesGroup):
    fix = State()
    full = State()
    points = State()
    confirm = State()


KIND_STATES = {"fix": KeyEdit.fix, "full": KeyEdit.full, "points": KeyEdit.points}


async def _load(bot: Bot, user, test_id: int):
    """Testni qaytaradi (faqat muallif yoki admin uchun), aks holda foydalanuvchiga tushuntiradi."""
    if not features.on("key_edit"):
        await bot.send_message(user["id"], features.OFF_TEXT, reply_markup=main_menu(user["id"]))
        return None
    test = await db.get_test(test_id)
    if test is None:
        await bot.send_message(user["id"], "❌ Test topilmadi — o'chirilgan bo'lishi mumkin.",
                               reply_markup=main_menu(user["id"]))
        return None
    if test["owner_id"] != user["id"] and not is_admin(user["id"]):
        return None
    return test


def _back_kb(test_id: int, extra: list[InlineKeyboardButton] | None = None) -> InlineKeyboardMarkup:
    rows = [extra] if extra else []
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"t:ed:{test_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------- menyu
async def _menu(callback: CallbackQuery, state: FSMContext, user, test_id: int) -> None:
    await state.clear()
    test = await _load(callback.bot, user, test_id)
    if test is None:
        await callback.answer("Bu test sizga tegishli emas.", show_alert=True)
        return
    questions = services.questions_of(test)
    participants = await db.count_participants(test["id"])
    lines = [
        f"✏️ <b>Kalitni tahrirlash</b> — {escape(test['title'])}",
        "",
        "<b>Hozirgi kalit:</b>",
        *services.key_preview(questions),
    ]
    if services.points_on():
        lines += ["", f"💯 Ball: {services.points_summary(questions)}"]
    if participants:
        lines.append(
            f"👥 Javob yuborganlar: <b>{participants}</b> nafar — saqlaganingizdan keyin ularning barcha natijalari, "
            "reyting va sertifikatlari <b>avtomatik qayta hisoblanadi</b>."
        )
    lines += ["", "Nimani o'zgartirasiz?"]
    tid = test["id"]
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎯 Ayrim savollarni tuzatish", callback_data=f"t:edk:fix:{tid}"))
    kb.row(InlineKeyboardButton(text="🔁 Butun kalitni qayta kiritish", callback_data=f"t:edk:full:{tid}"))
    if features.on("points"):
        kb.row(InlineKeyboardButton(text="⚖️ Ballarni o'zgartirish", callback_data=f"t:edk:points:{tid}"))
    kb.row(InlineKeyboardButton(text="⬅️ Testga qaytish", callback_data=f"t:v:{tid}"))
    await callback.answer()
    await services.send_long(callback.bot, user["id"], lines, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("t:ed:"))
async def edit_menu(callback: CallbackQuery, state: FSMContext, user) -> None:
    await _menu(callback, state, user, int(callback.data.split(":")[2]))


async def _ask(bot: Bot, user_id: int, state: FSMContext, test, kind: str) -> None:
    n = len(services.questions_of(test))
    tid = test["id"]
    await state.set_state(KIND_STATES[kind])
    await state.set_data({"test_id": tid, "kind": kind})
    if kind == "fix":
        text = (
            "🎯 <b>Ayrim savollarni tuzatish</b>\n\n"
            "Har bir tuzatishni <b>savol raqami va yangi to'g'ri javob</b> ko'rinishida yuboring. "
            "Bir nechta bo'lsa — har birini yangi qatordan:\n"
            "<code>5 B\n12 D\n17 A</code>\n\n"
            f"<i>Testda {n} ta savol bor. Ko'rsatilmagan savollar o'zgarmaydi"
            + (", ballar saqlanadi.</i>" if services.points_on() else ".</i>")
        )
        markup = _back_kb(tid)
    elif kind == "full":
        text = (
            "🔁 <b>Butun kalitni qayta kiritish</b>\n\n"
            f"Barcha <b>{n} ta</b> savolning to'g'ri javobini test yaratishdagi kabi yuboring:\n"
            "<code>1A2B3C4D…</code> yoki <code>ABCD…</code>\n\n"
            "<i>Savollar soni o'zgarmasligi kerak — ishtirokchilar javoblari shu savollarga bog'langan."
            + (" Ballar saqlanadi.</i>" if services.points_on() else "</i>")
        )
        markup = _back_kb(tid)
    else:
        text = (
            "⚖️ <b>Ballarni o'zgartirish</b>\n\n"
            "Ballarni <code>savollar: ball</code> ko'rinishida yuboring:\n"
            "<code>1-10: 1.1; 11-20: 2.1; 21-30: 3.1</code>\n\n"
            f"<i>Testda {n} ta savol bor. Ko'rsatilmagan savollar 1 balldan hisoblanadi.</i>"
        )
        markup = _back_kb(tid, [InlineKeyboardButton(text="✅ Hamma savol 1 ball", callback_data=f"t:edp1:{tid}")])
    await bot.send_message(user_id, "✏️ Tahrirlash rejimi", reply_markup=cancel_kb())
    await bot.send_message(user_id, text, reply_markup=markup)


@router.callback_query(F.data.startswith("t:edk:"))
async def edit_kind(callback: CallbackQuery, state: FSMContext, user) -> None:
    _, _, kind, test_id = callback.data.split(":")
    test = await _load(callback.bot, user, int(test_id))
    if kind == "points" and not features.on("points"):
        await callback.answer(features.OFF_TEXT, show_alert=True)
        return
    if test is None or kind not in KIND_STATES:
        await callback.answer("Bu test sizga tegishli emas.", show_alert=True)
        return
    await callback.answer()
    await _ask(callback.bot, user["id"], state, test, kind)


# ---------------------------------------------------------------- ma'lumot qabul qilish
async def _current(message: Message, state: FSMContext, user):
    test = await _load(message.bot, user, (await state.get_data()).get("test_id") or 0)
    if test is None:
        await state.clear()
    return test


@router.message(KeyEdit.fix, F.text)
async def got_fix(message: Message, state: FSMContext, user) -> None:
    test = await _current(message, state, user)
    if test is None:
        return
    questions = services.questions_of(test)
    try:
        corrections = kp.parse_corrections(message.text, len(questions), allow_open=features.on("open_questions"))
    except kp.ParseError as e:
        await message.answer(f"⚠️ {e}\n\nQaytadan yuboring 👇")
        return
    await _preview(message.bot, user, state, test, kp.apply_answers(questions, corrections), "fix")


@router.message(KeyEdit.full, F.text)
async def got_full(message: Message, state: FSMContext, user) -> None:
    test = await _current(message, state, user)
    if test is None:
        return
    questions = services.questions_of(test)
    try:
        answers = kp.parse_answers(message.text)
        kp.build_questions(answers, allow_open=features.on("open_questions"))  # A-D va bo'sh javoblarni tekshirish
    except kp.ParseError as e:
        await message.answer(f"⚠️ {e}\n\nQaytadan yuboring 👇")
        return
    if len(answers) != len(questions):
        await message.answer(
            f"⚠️ Testda <b>{len(questions)}</b> ta savol bor, siz esa <b>{len(answers)}</b> ta javob yubordingiz.\n\n"
            "Savollar sonini o'zgartirib bo'lmaydi. Agar savollar soni boshqacha bo'lsa — yangi test yarating.\n\n"
            "Qaytadan yuboring 👇"
        )
        return
    new = kp.apply_answers(questions, {i: a for i, a in enumerate(answers, start=1)})
    await _preview(message.bot, user, state, test, new, "full")


@router.message(KeyEdit.points, F.text)
async def got_points(message: Message, state: FSMContext, user) -> None:
    test = await _current(message, state, user)
    if test is None:
        return
    questions = services.questions_of(test)
    try:
        points = kp.parse_points(message.text, len(questions))
    except kp.ParseError as e:
        await message.answer(f"⚠️ {e}\n\nQaytadan yuboring 👇")
        return
    await _preview(message.bot, user, state, test, [{**q, "p": p} for q, p in zip(questions, points)], "points")


@router.message(KeyEdit.confirm, F.text)
async def got_while_confirming(message: Message, state: FSMContext, user) -> None:
    """Ko'rib chiqish oynasida yangi qiymat yuborilsa - uni qabul qilib, qayta ko'rsatamiz."""
    data = await state.get_data()
    kind = data.get("kind")
    if kind not in KIND_STATES:
        await state.clear()
        return
    await state.set_state(KIND_STATES[kind])
    await state.set_data({"test_id": data.get("test_id"), "kind": kind})
    await {"fix": got_fix, "full": got_full, "points": got_points}[kind](message, state, user)


@router.callback_query(KeyEdit.points, F.data.startswith("t:edp1:"))
async def points_standard(callback: CallbackQuery, state: FSMContext, user) -> None:
    test = await _load(callback.bot, user, int(callback.data.split(":")[2]))
    if test is None:
        await callback.answer("Bu test sizga tegishli emas.", show_alert=True)
        return
    await callback.answer()
    new = [{**q, "p": 1.0} for q in services.questions_of(test)]
    await _preview(callback.bot, user, state, test, new, "points")


# ---------------------------------------------------------------- ko'rib chiqish va saqlash
def _diff(old: list[dict], new: list[dict]) -> list[str]:
    lines = []
    for i, (a, b) in enumerate(zip(old, new), start=1):
        if (a["a"], a["t"]) != (b["a"], b["t"]):
            mark = " ✍️" if b["t"] == "o" else ""
            lines.append(
                f"{i}) <code>{escape(kp.fmt_answer(a['a']))}</code> → <b><code>{escape(kp.fmt_answer(b['a']))}</code></b>"
                f"{mark}"
            )
        if a["p"] != b["p"]:
            lines.append(f"{i}) ball: {kp.fmt_num(a['p'])} → <b>{kp.fmt_num(b['p'])}</b>")
    return lines


async def _preview(bot: Bot, user, state: FSMContext, test, new: list[dict], kind: str) -> None:
    uid = user["id"]
    old = services.questions_of(test)
    diff = _diff(old, new)
    if not diff:
        await bot.send_message(
            uid, "ℹ️ Hech narsa o'zgarmadi — yuborganingiz hozirgi kalit bilan bir xil.\n\n"
                 "Boshqa qiymat yuboring yoki «⬅️ Orqaga»ni bosing.",
            reply_markup=_back_kb(test["id"]),
        )
        return
    changes = services.regrade_preview(new, list(await db.submissions_all(test["id"])))
    visible = [c for c in changes if not c["hidden"]]
    up = sum(1 for c in visible if c["score"] > c["old_score"])
    down = sum(1 for c in visible if c["score"] < c["old_score"])

    await state.set_state(KeyEdit.confirm)
    await state.set_data({"test_id": test["id"], "kind": kind, "base": test["questions"], "new": new})

    lines = [f"🔎 <b>O'zgarishlarni tekshiring</b> — {escape(test['title'])}", ""]
    lines += diff[:MAX_DIFF_LINES]
    if len(diff) > MAX_DIFF_LINES:
        lines.append(f"… va yana {len(diff) - MAX_DIFF_LINES} ta o'zgarish")
    old_max, new_max = sum(q["p"] for q in old), sum(q["p"] for q in new)
    if old_max != new_max:
        lines += ["", f"💯 Maksimal ball: {kp.fmt_num(old_max)} → <b>{kp.fmt_num(new_max)}</b>"]
    lines.append("")
    participants = await db.count_participants(test["id"])
    word = "bali" if services.points_on() else "natijasi"
    if not participants:
        lines.append("👥 Hozircha javob yuborganlar yo'q — natijalarga ta'sir qilmaydi.")
    elif not changes:
        lines.append(f"👥 {participants} nafar ishtirokchining hech birining {word} o'zgarmaydi.")
    else:
        lines.append(
            f"👥 <b>{len(visible)}</b> nafar ishtirokchining {word} o'zgaradi: 📈 {up} ta oshadi, 📉 {down} ta kamayadi."
        )
        if not services.is_open(test):
            lines.append("🏅 Test yakunlangan — reytingdagi o'rinlar ham yangilanadi.")
    lines += ["", "❗️ Saqlangach, eski kalitga qaytib bo'lmaydi (faqat qayta tahrirlash orqali)."]

    tid = test["id"]
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ Saqlash", callback_data="ked:save"))
    if visible:
        kb.row(InlineKeyboardButton(text="✅ Saqlash va ishtirokchilarga xabar berish", callback_data="ked:notify"))
    kb.row(InlineKeyboardButton(text="✏️ Qayta kiritish", callback_data=f"t:edk:{kind}:{tid}"),
           InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"t:ed:{tid}"))
    await services.send_long(bot, uid, lines, reply_markup=kb.as_markup())


@router.callback_query(KeyEdit.confirm, F.data.in_({"ked:save", "ked:notify"}))
async def save(callback: CallbackQuery, state: FSMContext, user) -> None:
    from .mytests import _view

    data = await state.get_data()
    test = await _load(callback.bot, user, data.get("test_id") or 0)
    if test is None or not data.get("new"):
        await state.clear()
        await callback.answer("Bu test sizga tegishli emas.", show_alert=True)
        return
    if test["questions"] != data["base"]:
        await state.clear()
        await callback.answer()
        await callback.bot.send_message(
            user["id"],
            "⚠️ Bu orada kalit boshqa joydan o'zgartirildi. Eski ma'lumot ustiga yozmaslik uchun saqlanmadi.\n\n"
            "Tahrirlashni qaytadan boshlang.",
            reply_markup=_back_kb(test["id"]),
        )
        return
    await callback.answer("Saqlanmoqda…")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    changes = await services.apply_key(test["id"], data["new"])
    await state.clear()
    test = await db.get_test(test["id"])

    visible = [c for c in changes if not c["hidden"]]
    text = "✅ <b>Kalit saqlandi.</b>\n\n"
    text += (f"🔄 {len(changes)} ta natija qayta hisoblandi." if changes
             else "Ishtirokchilar natijalari o'zgarmadi.")
    notify = callback.data == "ked:notify" and visible
    if notify:
        text += f"\n📨 {len(visible)} nafar ishtirokchiga yangilangan natijasi yuborilmoqda."
        services.spawn(services.notify_regrade(callback.bot, test, visible))
    await callback.bot.send_message(user["id"], text, reply_markup=main_menu(user["id"]))
    view, kb = await _view(test)
    await callback.bot.send_message(user["id"], view, reply_markup=kb)
