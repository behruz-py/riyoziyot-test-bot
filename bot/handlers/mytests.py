"""Muallifning testlari: ro'yxat, natijalar, Excel, yakunlash, o'chirish."""
from __future__ import annotations

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, keyparser as kp, services
from ..config import is_admin
from ..keyboards import BTN_MY_TESTS, NO_PREVIEW, main_menu, pager
from .create import share_text

router = Router(name="mytests")
router.message.filter(F.chat.type == "private")

PAGE = 8


async def _list_page(user_id: int, page: int):
    total = await db.count_tests_by_owner(user_id)
    if total == 0:
        return "📚 Siz hali test yaratmagansiz. «➕ Test yaratish» tugmasini bosing.", None
    pages = (total + PAGE - 1) // PAGE
    page = max(0, min(page, pages - 1))
    kb = InlineKeyboardBuilder()
    for t in await db.tests_by_owner(user_id, PAGE, page * PAGE):
        mark = "🟢" if services.is_open(t) else "🔴"
        kb.row(InlineKeyboardButton(
            text=f"{mark} {t['title'][:30]} · {t['code']} · 👥 {t['participants']}",
            callback_data=f"t:v:{t['id']}",
        ))
    row = pager("mt", page, pages)
    if row:
        kb.row(*row)
    return f"📚 <b>Mening testlarim</b> (jami {total} ta)\n🟢 faol · 🔴 yakunlangan", kb.as_markup()


@router.message(F.text == BTN_MY_TESTS)
async def my_tests(message: Message, user) -> None:
    text, kb = await _list_page(user["id"], 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("mt:"))
async def my_tests_page(callback: CallbackQuery, user) -> None:
    text, kb = await _list_page(user["id"], int(callback.data.split(":")[1]))
    await services.edit_or_send(callback, text, kb)
    await callback.answer()


async def _owned_test(callback: CallbackQuery, user):
    """Callback ma'lumotidagi testni qaytaradi (faqat muallif yoki admin uchun)."""
    test = await db.get_test(int(callback.data.split(":")[2]))
    if test is None:
        await callback.answer("Test topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True)
        return None
    if test["owner_id"] != user["id"] and not is_admin(user["id"]):
        await callback.answer("Bu test sizga tegishli emas.", show_alert=True)
        return None
    return test


async def _view(test):
    questions = services.questions_of(test)
    closed = sum(1 for q in questions if q["t"] == "c")
    participants = await db.count_submissions(test["id"])
    active = services.is_open(test)
    status = "🟢 Faol" if active else f"🔴 Yakunlangan ({services.to_local(test['finished_at'] or test['deadline'])})"
    text = (
        f"📋 <b>{escape(test['title'])}</b>\n\n"
        f"🔢 Kod: <code>{test['code']}</code>\n"
        f"❓ Savollar: <b>{len(questions)}</b> ta (variantli: {closed}, ochiq: {len(questions) - closed})\n"
        f"💯 Ball: {services.points_summary(questions)}\n"
        f"👥 Ishtirokchilar: <b>{participants}</b> nafar\n"
        f"📅 Yaratilgan: {services.to_local(test['created_at'])}\n"
        f"⏰ Muddat: {services.to_local(test['deadline']) + ' gacha' if test['deadline'] else 'belgilanmagan'}\n"
        f"Holati: {status}"
    )
    tid = test["id"]
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📊 Natijalar", callback_data=f"t:res:{tid}"),
           InlineKeyboardButton(text="📥 Excel hisobot", callback_data=f"t:xl:{tid}"))
    kb.row(InlineKeyboardButton(text="🔑 Kalit", callback_data=f"t:key:{tid}"),
           InlineKeyboardButton(text="🔗 Ulashish", callback_data=f"t:share:{tid}"))
    if active:
        kb.row(InlineKeyboardButton(text="🏁 Testni yakunlash", callback_data=f"t:fin:{tid}"))
    kb.row(InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"t:del:{tid}"),
           InlineKeyboardButton(text="⬅️ Ro'yxat", callback_data="mt:0"))
    return text, kb.as_markup()


@router.callback_query(F.data.startswith("t:v:"))
async def view_test(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    text, kb = await _view(test)
    await services.edit_or_send(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("t:res:"))
async def test_results(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    await callback.answer()
    total = await db.count_submissions(test["id"])
    subs = await db.submissions_ranked(test["id"], 50)
    lines = services.ranking_lines(test, subs, total)
    if subs:
        all_subs = subs if total <= 50 else await db.submissions_ranked(test["id"])
        scores = [s["score"] for s in all_subs]
        lines += [
            "",
            f"📈 O'rtacha ball: <b>{kp.fmt_num(sum(scores) / len(scores))}</b> / {kp.fmt_num(all_subs[0]['max_score'])}",
            f"🔝 Eng yuqori: <b>{kp.fmt_num(max(scores))}</b> · eng past: <b>{kp.fmt_num(min(scores))}</b>",
            "",
            "To'liq ro'yxat va har bir savol tahlili — «📥 Excel hisobot»da.",
        ]
    await services.send_long(callback.bot, user["id"], lines)


@router.callback_query(F.data.startswith("t:xl:"))
async def test_excel(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    subs = await db.submissions_ranked(test["id"])
    if not subs:
        await callback.answer("Hozircha hech kim javob yubormagan.", show_alert=True)
        return
    await callback.answer("Hisobot tayyorlanmoqda…")
    from ..excel import build_report

    data = await asyncio.to_thread(build_report, dict(test), [dict(s) for s in subs])
    await callback.bot.send_document(
        user["id"],
        BufferedInputFile(data, filename=f"natijalar_{test['code']}.xlsx"),
        caption=f"📥 <b>{escape(test['title'])}</b> — natijalar ({len(subs)} nafar ishtirokchi)",
    )


@router.callback_query(F.data.startswith("t:key:"))
async def test_key(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    await callback.answer()
    questions = services.questions_of(test)
    lines = [f"🔑 <b>{escape(test['title'])}</b> — to'g'ri javoblar:", "", *services.key_preview(questions)]
    if len({q["p"] for q in questions}) > 1:
        lines += ["", "⚖️ Ballar: " + ", ".join(f"{i}) {kp.fmt_num(q['p'])}" for i, q in enumerate(questions, start=1))]
    await services.send_long(callback.bot, user["id"], lines)


@router.callback_query(F.data.startswith("t:share:"))
async def test_share(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    await callback.answer()
    me = await callback.bot.me()
    await callback.bot.send_message(user["id"], share_text(test, me.username), link_preview_options=NO_PREVIEW)


def _confirm_kb(action: str, test_id: int):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ Ha", callback_data=f"t:{action}:{test_id}"),
           InlineKeyboardButton(text="⬅️ Yo'q", callback_data=f"t:v:{test_id}"))
    return kb.as_markup()


@router.callback_query(F.data.startswith("t:fin:"))
async def finish_ask(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    await services.edit_or_send(
        callback,
        f"🏁 <b>{escape(test['title'])}</b> testini yakunlaysizmi?\n\n"
        "Javoblar qabul qilish to'xtaydi, ishtirokchilarga yakuniy o'rinlari va to'g'ri javoblar ochiladi. "
        "Bu amalni ortga qaytarib bo'lmaydi.",
        _confirm_kb("finok", test["id"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("t:finok:"))
async def finish_ok(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    await callback.answer()
    done = await services.finish_and_notify(callback.bot, test["id"])
    text, kb = await _view(await db.get_test(test["id"]))
    await services.edit_or_send(callback, text, kb)
    if not done:
        await callback.bot.send_message(user["id"], "ℹ️ Test avvalroq yakunlangan.")


@router.callback_query(F.data.startswith("t:del:"))
async def delete_ask(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    await services.edit_or_send(
        callback,
        f"🗑 <b>{escape(test['title'])}</b> testini o'chirasizmi?\n\n"
        "❗️ Test bilan birga <b>barcha ishtirokchilar natijalari</b> ham o'chadi. Bu amalni ortga qaytarib "
        "bo'lmaydi. Kerak bo'lsa, avval Excel hisobotni yuklab oling.",
        _confirm_kb("delok", test["id"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("t:delok:"))
async def delete_ok(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    await db.delete_test(test["id"])
    await callback.answer("Test o'chirildi.")
    text, kb = await _list_page(user["id"], 0)
    await services.edit_or_send(callback, "🗑 Test o'chirildi.\n\n" + text, kb)


# ---------------------------------------------------------------- tushunarsiz xabarlar (eng oxirgi handler)
@router.message()
async def fallback(message: Message, user) -> None:
    await message.answer(
        "🤔 Tushunmadim. Quyidagi menyudan foydalaning yoki /help ni bosing.", reply_markup=main_menu(user["id"])
    )


@router.callback_query()
async def fallback_callback(callback: CallbackQuery) -> None:
    await callback.answer("Bu tugma eskirgan. Amalni menyudan qaytadan boshlang.", show_alert=True)
