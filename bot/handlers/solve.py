"""Javob yuborish, natija, reyting, sertifikat."""
from __future__ import annotations

import asyncio
import json
import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import certs, db, features, keyparser as kp, services
from ..config import is_admin
from ..keyboards import (
    BTN_BACK, BTN_CHECK, BTN_MY_RESULTS, BTN_RATING, cancel_kb, flow_kb, home_btn, main_menu, pager,
)

router = Router(name="solve")
router.message.filter(F.chat.type == "private")

QUICK_RE = re.compile(r"^\s*(\d{4,8})\s*\*\s*(\S.*)$", re.S)
CODE_RE = re.compile(r"^\s*\d{4,8}\s*$")
PAGE = 8
RATING_TOP = 20

# Bir foydalanuvchining bir vaqtda ikki marta yuborishidan himoya
_submitting: set[tuple[int, int]] = set()


class Solve(StatesGroup):
    code = State()
    answers = State()
    confirm = State()


class RatingSt(StatesGroup):
    code = State()


def answer_guide(questions: list[dict]) -> str:
    open_nums = [str(i) for i, q in enumerate(questions, start=1) if q["t"] == "o"]
    if not open_nums:
        return (
            "✍️ <b>Javoblaringizni bitta xabarda yuboring</b>\n"
            "Namuna: <code>1A2B3C4D…</code> yoki <code>ABCDABCD…</code>\n"
            "Javob bermaydigan savolga <code>-</code> qo'ying."
        )
    return (
        "✍️ <b>Javoblaringizni bitta xabarda, har birini yangi qatordan yuboring</b>\n"
        "<code>1. A\n2. C\n3. 12.5</code>\n"
        f"Ochiq (yozma) javobli savollar: <b>{', '.join(open_nums)}</b>\n"
        "Javob bermaydigan savolga <code>-</code> qo'ying."
    )


async def ask_code(bot: Bot, user_id: int, state: FSMContext) -> None:
    await state.set_state(Solve.code)
    await bot.send_message(
        user_id,
        "✅ <b>Javobni tekshirish</b>\n\n"
        "🔢 O'qituvchingiz bergan <b>test kodini</b> yuboring.\n\n"
        "💡 <i>Tezkor usul: kod va javoblarni birga yuborish mumkin — </i><code>12345*1A2B3C4D</code>",
        reply_markup=flow_kb(placeholder="Test kodi"),
    )


async def _ask_answers(bot: Bot, user_id: int, state: FSMContext, test) -> None:
    questions = services.questions_of(test)
    await state.set_state(Solve.answers)
    await state.set_data({"test_id": test["id"]})
    info = [
        f"📋 <b>{escape(test['title'])}</b>",
        f"🔢 Kod: <code>{test['code']}</code>",
        f"❓ Savollar soni: <b>{len(questions)}</b> ta",
    ]
    if services.points_on():
        info.append(f"💯 Ball: {services.points_summary(questions)}")
    if test["deadline"]:
        info.append(f"⏰ Muddat: <b>{services.to_local(test['deadline'])}</b> gacha")
    await bot.send_message(
        user_id,
        "\n".join(info) + "\n\n"
        + f"{answer_guide(questions)}\n\n"
        + ("<i>Yuborishdan oldin javoblaringizni ko'rib chiqish imkoni beriladi.</i>"
           if features.on("confirm_submit") else
           "❗️ Javobni faqat <b>bir marta</b> yuborish mumkin — yuborishdan oldin tekshirib oling."),
        reply_markup=flow_kb(placeholder="Javoblaringiz"),
    )


async def _unavailable(bot: Bot, state: FSMContext, user, test) -> bool:
    """Testga javob yuborib bo'lmaydigan holatlarni tushuntiradi. True - javob qabul qilinmaydi."""
    uid = user["id"]
    sub = await db.get_submission(test["id"], uid)
    if sub is not None:
        await state.clear()
        await bot.send_message(
            uid, "ℹ️ Siz bu testga avval javob yuborgansiz. Mana natijangiz 👇", reply_markup=main_menu(uid)
        )
        await services.show_result(bot, uid, test, sub)
        return True
    if test["owner_id"] == uid:
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Testni boshqarish", callback_data=f"t:v:{test['id']}")],
        ])
        await bot.send_message(uid, "🏠 Asosiy menyu", reply_markup=main_menu(uid))
        await bot.send_message(
            uid, "ℹ️ Bu o'zingiz yaratgan test — unga javob yubora olmaysiz.\nNatijalarni ko'rish uchun 👇",
            reply_markup=kb,
        )
        return True
    if not services.is_open(test):
        await state.clear()
        await bot.send_message(
            uid,
            f"🔴 <b>{escape(test['title'])}</b> testi yakunlangan — javoblar endi qabul qilinmaydi.",
            reply_markup=main_menu(uid),
        )
        return True
    return False


async def open_test(bot: Bot, state: FSMContext, user, code: str) -> None:
    """Kod bo'yicha testni ochadi va javob kutish holatiga o'tadi."""
    uid = user["id"]
    test = await db.get_test_by_code(code)
    if test is None:
        await state.set_state(Solve.code)
        await bot.send_message(
            uid,
            f"❌ <code>{escape(code)}</code> kodli test topilmadi.\n\n"
            "Kodni tekshirib, qaytadan yuboring yoki «❌ Bekor qilish»ni bosing.",
            reply_markup=flow_kb(placeholder="Test kodi"),
        )
        return
    if await _unavailable(bot, state, user, test):
        return
    await _ask_answers(bot, uid, state, test)


async def preview_answers(bot: Bot, state: FSMContext, user, test, text: str) -> None:
    """Javoblarni o'qiydi va yuborishdan oldin tasdiqlash oynasini ko'rsatadi."""
    uid = user["id"]
    if await _unavailable(bot, state, user, test):
        return
    questions = services.questions_of(test)
    try:
        answers = kp.parse_answers(text)
        error = kp.validate_answers(questions, answers)
    except kp.ParseError as e:
        error = str(e)
    if error:
        await state.set_state(Solve.answers)
        await state.set_data({"test_id": test["id"]})
        await bot.send_message(
            uid, f"⚠️ {error}\n\n{answer_guide(questions)}\n\nQaytadan yuboring 👇",
            reply_markup=flow_kb(placeholder="Javoblaringiz"),
        )
        return

    if not features.on("confirm_submit"):
        await submit(bot, state, user, test, answers)
        return
    await state.set_state(Solve.confirm)
    await state.set_data({"test_id": test["id"], "answers": answers})
    skipped = sum(1 for a in answers if a == kp.SKIP)
    lines = [
        "🔎 <b>Javoblaringizni tekshiring</b>",
        f"📋 {escape(test['title'])}",
        "",
        *services.answers_preview(answers),
        "",
    ]
    if skipped:
        lines.append(f"⚪️ Javobsiz qoldirilgan savollar: <b>{skipped}</b> ta")
    lines.append("❗️ «Yuborish» bosilgach, javoblarni o'zgartirib bo'lmaydi.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yuborish", callback_data="sv:ok"),
        InlineKeyboardButton(text="✏️ Tuzatish", callback_data="sv:edit"),
    ]])
    await services.send_long(bot, uid, lines, reply_markup=kb)


async def submit(bot: Bot, state: FSMContext, user, test, answers: list[str]) -> None:
    uid = user["id"]
    key = (test["id"], uid)
    if key in _submitting:
        return
    _submitting.add(key)
    try:
        if await _unavailable(bot, state, user, test):
            return
        async with services.test_lock(test["id"]):
            # Kalit shu orada tahrirlangan bo'lishi mumkin - baholashdan oldin testni qayta o'qiymiz
            test = await db.get_test(test["id"])
            if test is None:
                await state.clear()
                await bot.send_message(uid, "❌ Test topilmadi — muallif uni o'chirgan.", reply_markup=main_menu(uid))
                return
            questions = services.questions_of(test)
            if kp.validate_answers(questions, answers) is not None:
                await _ask_answers(bot, uid, state, test)
                return
            res = kp.grade(questions, answers)
            await db.add_submission(
                test["id"], uid, user["full_name"], answers, res["correct"], res["score"], res["max_score"]
            )
        await state.clear()
        sub = await db.get_submission(test["id"], uid)
        await bot.send_message(uid, "✅ <b>Javoblaringiz qabul qilindi!</b> Natijangiz 👇", reply_markup=main_menu(uid))
        await services.show_result(bot, uid, test, sub)
    finally:
        _submitting.discard(key)


async def _current_test(bot: Bot, state: FSMContext, user):
    """Holatda saqlangan testni qaytaradi; topilmasa foydalanuvchini menyuga qaytaradi."""
    data = await state.get_data()
    test = await db.get_test(data.get("test_id") or 0)
    if test is None:
        await state.clear()
        await bot.send_message(
            user["id"], "❌ Test topilmadi — muallif uni o'chirgan bo'lishi mumkin.", reply_markup=main_menu(user["id"])
        )
    return test, data


# ---------------------------------------------------------------- javob yuborish
@router.message(F.text == BTN_CHECK)
async def check_menu(message: Message, state: FSMContext, user) -> None:
    await ask_code(message.bot, user["id"], state)


@router.callback_query(F.data == "go:check")
async def check_cb(callback: CallbackQuery, state: FSMContext, user) -> None:
    await callback.answer()
    await state.clear()
    await ask_code(callback.bot, user["id"], state)


@router.message(Solve.code, F.text == BTN_BACK)
async def code_back(message: Message, state: FSMContext, user) -> None:
    from .start import send_menu

    await state.clear()
    await send_menu(message.bot, user["id"])


@router.message(Solve.answers, F.text == BTN_BACK)
async def answers_back(message: Message, state: FSMContext, user) -> None:
    await ask_code(message.bot, user["id"], state)


@router.message(Solve.confirm, F.text == BTN_BACK)
async def confirm_back(message: Message, state: FSMContext, user) -> None:
    test, _ = await _current_test(message.bot, state, user)
    if test is not None:
        await _ask_answers(message.bot, user["id"], state, test)


async def _quick(message: Message, state: FSMContext, user) -> bool:
    m = QUICK_RE.match(message.text)
    if not m:
        return False
    test = await db.get_test_by_code(m.group(1))
    if test is None:
        await open_test(message.bot, state, user, m.group(1))  # "topilmadi" xabari
        return True
    await preview_answers(message.bot, state, user, test, m.group(2))
    return True


@router.message(Solve.code, F.text)
async def got_code(message: Message, state: FSMContext, user) -> None:
    if await _quick(message, state, user):
        return
    code = message.text.strip()
    if not code.isdigit():
        await message.answer(
            "⚠️ Test kodi faqat raqamlardan iborat (masalan: <code>48213</code>).\n\nQaytadan yuboring 👇"
        )
        return
    await open_test(message.bot, state, user, code)


@router.message(StateFilter(Solve.answers, Solve.confirm), F.text)
async def got_answers(message: Message, state: FSMContext, user) -> None:
    test, _ = await _current_test(message.bot, state, user)
    if test is None:
        return
    text = message.text
    m = QUICK_RE.match(text)
    if m and m.group(1) == test["code"]:
        text = m.group(2)
    await preview_answers(message.bot, state, user, test, text)


@router.callback_query(Solve.confirm, F.data == "sv:ok")
async def confirm_ok(callback: CallbackQuery, state: FSMContext, user) -> None:
    test, data = await _current_test(callback.bot, state, user)
    await callback.answer()
    if test is None:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await submit(callback.bot, state, user, test, data.get("answers") or [])


@router.callback_query(Solve.confirm, F.data == "sv:edit")
async def confirm_edit(callback: CallbackQuery, state: FSMContext, user) -> None:
    test, _ = await _current_test(callback.bot, state, user)
    await callback.answer()
    if test is None:
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _ask_answers(callback.bot, user["id"], state, test)


@router.message(StateFilter(None), F.text.func(lambda t: bool(t) and QUICK_RE.match(t) is not None))
async def quick_submit(message: Message, state: FSMContext, user) -> None:
    await _quick(message, state, user)


@router.message(StateFilter(None), F.text.func(lambda t: bool(t) and CODE_RE.match(t) is not None))
async def bare_code(message: Message, state: FSMContext, user) -> None:
    # Menyudan tashqarida yuborilgan raqam - test kodi deb qabul qilinadi
    await open_test(message.bot, state, user, message.text.strip())


# ---------------------------------------------------------------- natijalarim
async def _results_page(user_id: int, page: int):
    total = await db.count_submissions_by_user(user_id)
    kb = InlineKeyboardBuilder()
    if total == 0:
        kb.row(InlineKeyboardButton(text="✅ Javobni tekshirish", callback_data="go:check"))
        return (
            "📊 <b>Natijalarim</b>\n\nSiz hali birorta testga javob yubormagansiz.\n"
            "Test kodingiz bo'lsa, hoziroq tekshirib ko'ring 👇"
        ), kb.as_markup()
    pages = (total + PAGE - 1) // PAGE
    page = max(0, min(page, pages - 1))
    for s in await db.submissions_by_user(user_id, PAGE, page * PAGE):
        kb.row(InlineKeyboardButton(
            text=f"{s['title'][:35]} — " + (
                f"{kp.fmt_num(s['score'])}/{kp.fmt_num(s['max_score'])}" if services.points_on()
                else f"{s['correct_count']}/{len(json.loads(s['answers']))}"
            ),
            callback_data=f"res:{s['test_id']}",
        ))
    row = pager("myres", page, pages)
    if row:
        kb.row(*row)
    kb.row(home_btn())
    return f"📊 <b>Natijalarim</b> — jami {total} ta test\n\nBatafsil ko'rish uchun testni tanlang 👇", kb.as_markup()


@router.message(F.text == BTN_MY_RESULTS)
async def my_results(message: Message, user) -> None:
    text, kb = await _results_page(user["id"], 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("myres:"))
async def my_results_page(callback: CallbackQuery, user) -> None:
    text, kb = await _results_page(user["id"], int(callback.data.split(":")[1]))
    await services.edit_or_send(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("res:"))
async def result_detail(callback: CallbackQuery, user) -> None:
    test = await db.get_test(int(callback.data.split(":")[1]))
    sub = await db.get_submission(test["id"], user["id"]) if test else None
    if sub is None:
        await callback.answer("Natija topilmadi — test o'chirilgan bo'lishi mumkin.", show_alert=True)
        return
    await callback.answer()
    await services.show_result(callback.bot, user["id"], test, sub)


# ---------------------------------------------------------------- reyting
async def send_rating(bot: Bot, user, test, reply_markup=None) -> bool:
    """Reytingni yuboradi. Ruxsat bo'lmasa False."""
    uid = user["id"]
    sub = await db.get_submission(test["id"], uid)
    if sub is not None and (sub["is_hidden"] or not features.on("rating")):
        sub = None  # reytingdan chiqarilgan ishtirokchi (yoki reyting o'chiq) - ko'ra olmaydi
    if sub is None and test["owner_id"] != uid and not is_admin(uid):
        return False
    total = await db.count_submissions(test["id"])
    subs = await db.submissions_ranked(test["id"], RATING_TOP)
    lines = services.ranking_lines(test, subs, total, me_id=uid)
    if sub is not None:
        rank = await db.rank_of(sub)
        if rank > RATING_TOP:
            total_q = len(services.questions_of(test))
            lines += ["", f"👉 Sizning o'rningiz: <b>{rank} / {total}</b> — {services.short_result(sub, total_q)}"]
    await services.send_long(bot, uid, lines, reply_markup=reply_markup)
    return True


@router.callback_query(F.data.startswith("rating:"))
async def rating_cb(callback: CallbackQuery, state: FSMContext, user) -> None:
    test = await db.get_test(int(callback.data.split(":")[1]))
    if test is None:
        await callback.answer("Test topilmadi — o'chirilgan bo'lishi mumkin.", show_alert=True)
        return
    # Reyting bo'limidan kelgan bo'lsa, kod kutish holatini yopib, asosiy menyuni qaytaramiz
    from_menu = await state.get_state() == RatingSt.code.state
    if not await send_rating(callback.bot, user, test, main_menu(user["id"]) if from_menu else None):
        reason = "Reytingni faqat testda qatnashganlar ko'ra oladi."
        if not features.on("rating") and await db.get_submission(test["id"], user["id"]):
            reason = features.OFF_TEXT
        await callback.answer(reason, show_alert=True)
        return
    if from_menu:
        await state.clear()
    await callback.answer()


@router.message(F.text == BTN_RATING)
async def rating_ask(message: Message, state: FSMContext, user) -> None:
    if not features.on("rating"):
        await message.answer(features.OFF_TEXT, reply_markup=main_menu(user["id"]))
        return
    await state.set_state(RatingSt.code)
    tests = await db.recent_tests_for_user(user["id"], 8)
    kb = InlineKeyboardBuilder()
    for t in tests:
        mark = "📚" if t["owner_id"] == user["id"] else "✅"
        kb.row(InlineKeyboardButton(text=f"{mark} {t['title'][:38]} · {t['code']}", callback_data=f"rating:{t['id']}"))
    await message.answer("🏆 <b>Reyting</b>", reply_markup=cancel_kb("Test kodi"))
    if tests:
        await message.answer(
            "Qaysi test reytingini ko'rmoqchisiz?\n\n"
            "Ro'yxatdan tanlang yoki <b>test kodini</b> yuboring 👇\n"
            "<i>✅ — siz qatnashgan · 📚 — siz yaratgan</i>",
            reply_markup=kb.as_markup(),
        )
    else:
        await message.answer(
            "Reytingini ko'rmoqchi bo'lgan <b>test kodini</b> yuboring 👇\n\n"
            "<i>Reytingni faqat testda qatnashganlar va test muallifi ko'ra oladi.</i>"
        )


@router.message(RatingSt.code, F.text)
async def rating_code(message: Message, state: FSMContext, user) -> None:
    test = await db.get_test_by_code(message.text.strip())
    if test is None:
        await message.answer(
            "❌ Bunday kodli test topilmadi.\n\nKodni tekshirib, qaytadan yuboring yoki «❌ Bekor qilish»ni bosing."
        )
        return
    await state.clear()
    if not await send_rating(message.bot, user, test, main_menu(user["id"])):
        await message.answer(
            "🔒 Bu test reytingini faqat unda qatnashganlar ko'ra oladi.\n\n"
            f"Qatnashish uchun «✅ Javobni tekshirish» bo'limida <code>{test['code']}</code> kodini kiriting.",
            reply_markup=main_menu(user["id"]),
        )


# ---------------------------------------------------------------- sertifikat
@router.callback_query(F.data.startswith("cert:"))
async def certificate_cb(callback: CallbackQuery, user) -> None:
    test = await db.get_test(int(callback.data.split(":")[1]))
    sub = await db.get_submission(test["id"], user["id"]) if test else None
    if not features.on("certificate"):
        await callback.answer(features.OFF_TEXT, show_alert=True)
        return
    if sub is None:
        await callback.answer("Sertifikat faqat testda qatnashganlarga beriladi.", show_alert=True)
        return
    if sub["is_hidden"]:
        await callback.answer("Natijangiz reytingdan chiqarilgan — sertifikat berilmaydi.", show_alert=True)
        return
    await callback.answer("🎓 Sertifikat tayyorlanmoqda…")
    await callback.bot.send_chat_action(user["id"], "upload_photo")
    png, pdf, info = await certs.issue(callback.bot, test, sub)
    caption = f"🎓 <b>{info['title']}</b>\n№ <code>{info['number']}</code>"
    if not info["finished"]:
        caption += (
            "\n\n<i>Test hali yakunlanmagan. Yakunlangach qayta olsangiz, sertifikatda egallagan o'rningiz "
            "yoziladi, 1–3-o'rinlar esa diplom oladi.</i>"
        )
    await callback.bot.send_photo(user["id"], BufferedInputFile(png, filename=f"sertifikat_{test['code']}.png"),
                                  caption=caption)
    await callback.bot.send_document(
        user["id"],
        BufferedInputFile(pdf, filename=f"sertifikat_{info['number']}.pdf"),
        caption="📄 Chop etish uchun PDF nusxa.\n"
                "<i>Sertifikatdagi QR kod skanerlansa, bot uning haqiqiyligini tasdiqlaydi.</i>",
    )
