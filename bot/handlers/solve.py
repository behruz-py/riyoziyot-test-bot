"""Javob yuborish, natija, reyting, sertifikat."""
from __future__ import annotations

import asyncio
import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, keyparser as kp, services
from ..config import is_admin
from ..keyboards import BTN_CHECK, BTN_MY_RESULTS, BTN_RATING, cancel_kb, main_menu, pager

router = Router(name="solve")
router.message.filter(F.chat.type == "private")

QUICK_RE = re.compile(r"^\s*(\d{4,8})\s*\*\s*(\S.*)$", re.S)
PAGE = 8
RATING_TOP = 20

# Bir foydalanuvchining bir vaqtda ikki marta yuborishidan himoya
_submitting: set[tuple[int, int]] = set()


class Solve(StatesGroup):
    code = State()
    answers = State()


class RatingSt(StatesGroup):
    code = State()


def answer_guide(questions: list[dict]) -> str:
    open_nums = [str(i) for i, q in enumerate(questions, start=1) if q["t"] == "o"]
    if not open_nums:
        return (
            "✍️ Javoblaringizni bitta xabarda yuboring.\n"
            "Namuna: <code>abcdabcd…</code> yoki <code>1a2b3c4d…</code>\n"
            "Javob bermaydigan savolingizga <code>-</code> qo'ying."
        )
    return (
        "✍️ Bu testda <b>ochiq (yozma) javobli</b> savollar bor: " + ", ".join(open_nums) + "\n"
        "Javoblarni bitta xabarda, <b>har birini yangi qatordan</b> yuboring:\n"
        "<code>1. a\n2. c\n3. 12.5</code>\n"
        "Javob bermaydigan savolingizga <code>-</code> qo'ying."
    )


async def open_test(bot: Bot, state: FSMContext, user, code: str) -> None:
    """Kod bo'yicha testni ochadi va javob kutish holatiga o'tadi."""
    uid = user["id"]
    test = await db.get_test_by_code(code)
    if test is None:
        await bot.send_message(uid, f"❌ <code>{escape(code)}</code> kodli test topilmadi. Kodni tekshirib, qayta yuboring.")
        return
    sub = await db.get_submission(test["id"], uid)
    if sub is not None:
        await state.clear()
        await bot.send_message(uid, "ℹ️ Siz bu testga avval javob yuborgansiz. Natijangiz:", reply_markup=main_menu(uid))
        await services.show_result(bot, uid, test, sub)
        return
    if test["owner_id"] == uid:
        await state.clear()
        await bot.send_message(
            uid, "ℹ️ Bu o'zingiz yaratgan test. Uni «📚 Mening testlarim» bo'limida boshqarasiz.",
            reply_markup=main_menu(uid),
        )
        return
    if not services.is_open(test):
        await state.clear()
        await bot.send_message(
            uid, f"🔴 <b>{escape(test['title'])}</b> testi yakunlangan, javoblar qabul qilinmaydi.",
            reply_markup=main_menu(uid),
        )
        return

    questions = services.questions_of(test)
    await state.set_state(Solve.answers)
    await state.update_data(test_id=test["id"])
    deadline = f"\n⏰ Muddat: <b>{services.to_local(test['deadline'])}</b> gacha" if test["deadline"] else ""
    await bot.send_message(
        uid,
        f"📋 <b>{escape(test['title'])}</b>\n"
        f"🔢 Kod: <code>{test['code']}</code>\n"
        f"❓ Savollar soni: <b>{len(questions)}</b> ta\n"
        f"💯 Ball: {services.points_summary(questions)}{deadline}\n\n"
        f"{answer_guide(questions)}\n\n"
        "❗️ Javobni faqat <b>bir marta</b> yuborish mumkin — yuborishdan oldin tekshirib oling.",
        reply_markup=cancel_kb(),
    )


async def process_submission(bot: Bot, state: FSMContext, user, test, text: str) -> None:
    uid = user["id"]
    key = (test["id"], uid)
    if key in _submitting:
        return
    _submitting.add(key)
    try:
        if test["owner_id"] == uid:
            await state.clear()
            await bot.send_message(uid, "ℹ️ O'zingiz yaratgan testga javob yubora olmaysiz.", reply_markup=main_menu(uid))
            return
        if not services.is_open(test):
            await state.clear()
            await bot.send_message(uid, "🔴 Test yakunlangan, javoblar qabul qilinmaydi.", reply_markup=main_menu(uid))
            return
        existing = await db.get_submission(test["id"], uid)
        if existing is not None:
            await state.clear()
            await bot.send_message(uid, "ℹ️ Siz bu testga avval javob yuborgansiz. Natijangiz:", reply_markup=main_menu(uid))
            await services.show_result(bot, uid, test, existing)
            return

        questions = services.questions_of(test)
        try:
            answers = kp.parse_answers(text)
            error = kp.validate_answers(questions, answers)
        except kp.ParseError as e:
            error = str(e)
        if error:
            await bot.send_message(uid, f"⚠️ {error}\n\n{answer_guide(questions)}\n\nQaytadan yuboring:")
            return

        res = kp.grade(questions, answers)
        saved = await db.add_submission(
            test["id"], uid, user["full_name"], answers, res["correct"], res["score"], res["max_score"]
        )
        await state.clear()
        sub = await db.get_submission(test["id"], uid)
        await bot.send_message(
            uid, "✅ Javoblaringiz qabul qilindi!" if saved else "ℹ️ Javobingiz avval qabul qilingan.",
            reply_markup=main_menu(uid),
        )
        await services.show_result(bot, uid, test, sub)
    finally:
        _submitting.discard(key)


# ---------------------------------------------------------------- javob yuborish
@router.message(F.text == BTN_CHECK)
async def ask_code(message: Message, state: FSMContext) -> None:
    await state.set_state(Solve.code)
    await message.answer(
        "🔢 <b>Test kodini</b> yuboring.\n\n"
        "💡 Tezkor usul: kod va javoblarni birga yuborish mumkin — <code>12345*abcdabcd</code>",
        reply_markup=cancel_kb(),
    )


async def _quick(message: Message, state: FSMContext, user) -> bool:
    m = QUICK_RE.match(message.text)
    if not m:
        return False
    test = await db.get_test_by_code(m.group(1))
    if test is None:
        await message.answer(f"❌ <code>{m.group(1)}</code> kodli test topilmadi.")
        return True
    await process_submission(message.bot, state, user, test, m.group(2))
    return True


@router.message(Solve.code, F.text)
async def got_code(message: Message, state: FSMContext, user) -> None:
    if await _quick(message, state, user):
        return
    code = message.text.strip()
    if not code.isdigit():
        await message.answer("Test kodi faqat raqamlardan iborat. Qaytadan yuboring:")
        return
    await open_test(message.bot, state, user, code)


@router.message(Solve.answers, F.text)
async def got_answers(message: Message, state: FSMContext, user) -> None:
    data = await state.get_data()
    test = await db.get_test(data.get("test_id", 0))
    if test is None:
        await state.clear()
        await message.answer("❌ Test topilmadi (o'chirilgan bo'lishi mumkin).", reply_markup=main_menu(user["id"]))
        return
    text = message.text
    m = QUICK_RE.match(text)
    if m and m.group(1) == test["code"]:
        text = m.group(2)
    await process_submission(message.bot, state, user, test, text)


@router.message(StateFilter(None), F.text.func(lambda t: QUICK_RE.match(t) is not None))
async def quick_submit(message: Message, state: FSMContext, user) -> None:
    await _quick(message, state, user)


# ---------------------------------------------------------------- natijalarim
async def _results_page(user_id: int, page: int):
    total = await db.count_submissions_by_user(user_id)
    if total == 0:
        return "📊 Siz hali birorta testga javob yubormagansiz.", None
    pages = (total + PAGE - 1) // PAGE
    page = max(0, min(page, pages - 1))
    kb = InlineKeyboardBuilder()
    for s in await db.submissions_by_user(user_id, PAGE, page * PAGE):
        kb.row(InlineKeyboardButton(
            text=f"{s['title'][:35]} — {kp.fmt_num(s['score'])}/{kp.fmt_num(s['max_score'])}",
            callback_data=f"res:{s['test_id']}",
        ))
    row = pager("myres", page, pages)
    if row:
        kb.row(*row)
    return f"📊 <b>Natijalarim</b> (jami {total} ta test). Batafsil ko'rish uchun tanlang:", kb.as_markup()


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
        await callback.answer("Natija topilmadi (test o'chirilgan bo'lishi mumkin).", show_alert=True)
        return
    await callback.answer()
    await services.show_result(callback.bot, user["id"], test, sub)


# ---------------------------------------------------------------- reyting
async def send_rating(bot: Bot, user, test) -> bool:
    """Reytingni yuboradi. Ruxsat bo'lmasa False."""
    uid = user["id"]
    sub = await db.get_submission(test["id"], uid)
    if sub is None and test["owner_id"] != uid and not is_admin(uid):
        return False
    total = await db.count_submissions(test["id"])
    subs = await db.submissions_ranked(test["id"], RATING_TOP)
    lines = services.ranking_lines(test, subs, total, me_id=uid)
    if sub is not None:
        rank = await db.rank_of(sub)
        if rank > RATING_TOP:
            lines += ["", f"👉 Sizning o'rningiz: <b>{rank} / {total}</b> — {kp.fmt_num(sub['score'])} ball"]
    await services.send_long(bot, uid, lines)
    return True


@router.callback_query(F.data.startswith("rating:"))
async def rating_cb(callback: CallbackQuery, user) -> None:
    test = await db.get_test(int(callback.data.split(":")[1]))
    if test is None:
        await callback.answer("Test topilmadi.", show_alert=True)
        return
    if not await send_rating(callback.bot, user, test):
        await callback.answer("Reytingni ko'rish uchun avval testda qatnashing.", show_alert=True)
        return
    await callback.answer()


@router.message(F.text == BTN_RATING)
async def rating_ask(message: Message, state: FSMContext) -> None:
    await state.set_state(RatingSt.code)
    await message.answer("🏆 Reytingini ko'rmoqchi bo'lgan <b>test kodini</b> yuboring:", reply_markup=cancel_kb())


@router.message(RatingSt.code, F.text)
async def rating_code(message: Message, state: FSMContext, user) -> None:
    test = await db.get_test_by_code(message.text.strip())
    if test is None:
        await message.answer("❌ Bunday kodli test topilmadi. Qaytadan yuboring:")
        return
    await state.clear()
    await message.answer("🏆 Reyting:", reply_markup=main_menu(user["id"]))
    if not await send_rating(message.bot, user, test):
        await message.answer("🔒 Reytingni faqat testda qatnashganlar ko'ra oladi.")


# ---------------------------------------------------------------- sertifikat
@router.callback_query(F.data.startswith("cert:"))
async def certificate_cb(callback: CallbackQuery, user) -> None:
    test = await db.get_test(int(callback.data.split(":")[1]))
    sub = await db.get_submission(test["id"], user["id"]) if test else None
    if sub is None:
        await callback.answer("Sertifikat faqat testda qatnashganlarga beriladi.", show_alert=True)
        return
    await callback.answer("🎓 Sertifikat tayyorlanmoqda…")
    from ..certificate import build_certificate

    finished = not services.is_open(test)
    data = await asyncio.to_thread(
        build_certificate,
        name=sub["full_name"],
        title=test["title"],
        code=test["code"],
        correct=sub["correct_count"],
        total_q=len(services.questions_of(test)),
        score=kp.fmt_num(sub["score"]),
        max_score=kp.fmt_num(sub["max_score"]),
        percent=services.percent(sub["score"], sub["max_score"]),
        rank=await db.rank_of(sub) if finished else None,
        participants=await db.count_submissions(test["id"]),
        date=services.to_local(sub["submitted_at"])[:10],
    )
    caption = "🎓 Sertifikatingiz tayyor!"
    if not finished:
        caption += "\n<i>Test yakunlangach, sertifikatni qayta olsangiz, unda egallagan o'rningiz ham yoziladi.</i>"
    await callback.bot.send_photo(
        user["id"], BufferedInputFile(data, filename=f"sertifikat_{test['code']}.png"), caption=caption
    )
