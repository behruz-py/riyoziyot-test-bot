"""Muallifning testlari: ro'yxat, natijalar, Excel, yakunlash, o'chirish."""
from __future__ import annotations

import asyncio
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, keyparser as kp, services
from ..config import ADMIN_IDS, is_admin
from ..keyboards import BTN_MY_TESTS, flow_kb, home_btn, main_menu, pager
from .create import send_post

router = Router(name="mytests")
router.message.filter(F.chat.type == "private")

PAGE = 8


async def _list_page(user_id: int, page: int):
    total = await db.count_tests_by_owner(user_id)
    kb = InlineKeyboardBuilder()
    if total == 0:
        kb.row(InlineKeyboardButton(text="➕ Birinchi testni yaratish", callback_data="go:create"))
        return (
            "📚 <b>Mening testlarim</b>\n\nSiz hali test yaratmagansiz.\n"
            "Test yaratish 1 daqiqa vaqt oladi — sinab ko'ring 👇"
        ), kb.as_markup()
    pages = (total + PAGE - 1) // PAGE
    page = max(0, min(page, pages - 1))
    for t in await db.tests_by_owner(user_id, PAGE, page * PAGE):
        mark = "🟢" if services.is_open(t) else "🔴"
        kb.row(InlineKeyboardButton(
            text=f"{mark} {t['title'][:30]} · {t['code']} · 👥 {t['participants']}",
            callback_data=f"t:v:{t['id']}",
        ))
    row = pager("mt", page, pages)
    if row:
        kb.row(*row)
    kb.row(InlineKeyboardButton(text="➕ Yangi test", callback_data="go:create"), home_btn())
    return (
        f"📚 <b>Mening testlarim</b> — jami {total} ta\n"
        "<i>🟢 faol · 🔴 yakunlangan · 👥 ishtirokchilar soni</i>\n\n"
        "Boshqarish uchun testni tanlang 👇"
    ), kb.as_markup()


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
    participants = await db.count_submissions(test["id"])
    active = services.is_open(test)
    status = "🟢 Faol" if active else f"🔴 Yakunlangan ({services.to_local(test['finished_at'] or test['deadline'])})"
    text = (
        f"📋 <b>{escape(test['title'])}</b>\n\n"
        f"🔢 Kod: <code>{test['code']}</code>\n"
        f"❓ Savollar: <b>{len(questions)}</b> ta\n"
        f"💯 Ball: {services.points_summary(questions)}\n"
        f"👥 Ishtirokchilar: <b>{participants}</b> nafar\n"
        f"📅 Yaratilgan: {services.to_local(test['created_at'])}\n"
        f"⏰ Muddat: {services.to_local(test['deadline']) + ' gacha' if test['deadline'] else 'belgilanmagan'}\n"
        + (f"✏️ Kalit tahrirlangan: {services.to_local(test['edited_at'])}\n" if test["edited_at"] else "")
        + f"Holati: {status}"
    )
    tid = test["id"]
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📊 Natijalar", callback_data=f"t:res:{tid}"),
           InlineKeyboardButton(text="📥 Excel hisobot", callback_data=f"t:xl:{tid}"))
    kb.row(InlineKeyboardButton(text="👥 Ishtirokchilar", callback_data=f"t:pl:{tid}:0"),
           InlineKeyboardButton(text="🔑 Kalit", callback_data=f"t:key:{tid}"))
    kb.row(InlineKeyboardButton(text="✏️ Kalitni tahrirlash", callback_data=f"t:ed:{tid}"),
           InlineKeyboardButton(text="📣 Post (ulashish)", callback_data=f"t:post:{tid}"))
    if active:
        kb.row(InlineKeyboardButton(text="🏁 Testni yakunlash", callback_data=f"t:fin:{tid}"))
    kb.row(InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"t:del:{tid}"),
           InlineKeyboardButton(text="🔄 Yangilash", callback_data=f"t:v:{tid}"))
    kb.row(InlineKeyboardButton(text="⬅️ Testlar ro'yxati", callback_data="mt:0"), home_btn())
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
        await callback.answer("Hozircha hech kim javob yubormagan — hisobot bo'sh.", show_alert=True)
        return
    await callback.answer("📥 Hisobot tayyorlanmoqda…")
    await callback.bot.send_chat_action(user["id"], "upload_document")
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
    await send_post(callback.bot, user["id"], test)


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
    services.deadlines_changed()
    await callback.answer("Test o'chirildi.")
    text, kb = await _list_page(user["id"], 0)
    await services.edit_or_send(callback, "🗑 Test o'chirildi.\n\n" + text, kb)


# ---------------------------------------------------------------- ishtirokchilar nazorati
_reported: set[tuple[int, int]] = set()  # (test_id, user_id) - bir ishtirokchi ustidan takroriy shikoyatdan himoya


async def _participants_page(test, page: int):
    tid = test["id"]
    total = await db.count_participants(tid)
    kb = InlineKeyboardBuilder()
    if total == 0:
        kb.row(InlineKeyboardButton(text="⬅️ Testga qaytish", callback_data=f"t:v:{tid}"))
        return f"👥 <b>{escape(test['title'])}</b>\n\nHozircha hech kim javob yubormagan.", kb.as_markup()
    pages = (total + PAGE - 1) // PAGE
    page = max(0, min(page, pages - 1))
    for sub in await db.participants(tid, PAGE, page * PAGE):
        mark = "🚫 " if sub["is_hidden"] else ""
        kb.row(InlineKeyboardButton(
            text=f"{mark}{sub['full_name'][:32]} — {kp.fmt_num(sub['score'])}",
            callback_data=f"t:pu:{tid}:{sub['user_id']}",
        ))
    row = pager(f"t:pl:{tid}", page, pages)
    if row:
        kb.row(*row)
    kb.row(InlineKeyboardButton(text="⬅️ Testga qaytish", callback_data=f"t:v:{tid}"), home_btn())
    return (
        f"👥 <b>{escape(test['title'])}</b> — ishtirokchilar ({total} nafar)\n\n"
        "Nomaqbul ismli yoki testni buzayotgan ishtirokchini tanlab, <b>reytingdan chiqarishingiz</b> mumkin.\n"
        "<i>🚫 — reytingdan chiqarilgan</i>"
    ), kb.as_markup()


async def _participant_card(test, user_id: int):
    tid = test["id"]
    sub = await db.get_submission(tid, user_id)
    if sub is None:
        return None, None
    account = await db.get_user(user_id)
    username = f"@{account['username']}" if account and account["username"] else "yo'q"
    if sub["is_hidden"] == db.HIDDEN_BY_OWNER:
        status = "🚫 Siz reytingdan chiqargansiz"
    elif sub["is_hidden"] == db.HIDDEN_BY_BAN:
        status = "🚫 Administrator tomonidan bloklangan"
    else:
        status = "✅ Reytingda"
    text = (
        f"👤 <b>{escape(sub['full_name'])}</b>\n\n"
        f"Username: {escape(username)}\n"
        f"ID: <code>{user_id}</code>\n"
        f"💯 Ball: <b>{kp.fmt_num(sub['score'])} / {kp.fmt_num(sub['max_score'])}</b> "
        f"({sub['correct_count']} ta to'g'ri)\n"
        f"🕒 Topshirgan: {services.to_local(sub['submitted_at'])}\n"
        f"Holati: {status}"
    )
    kb = InlineKeyboardBuilder()
    if sub["is_hidden"] == 0:
        kb.row(InlineKeyboardButton(text="🚫 Reytingdan chiqarish", callback_data=f"t:ph:{tid}:{user_id}"))
    elif sub["is_hidden"] == db.HIDDEN_BY_OWNER:
        kb.row(InlineKeyboardButton(text="♻️ Reytingga qaytarish", callback_data=f"t:pr:{tid}:{user_id}"))
    kb.row(InlineKeyboardButton(text="📣 Adminga shikoyat qilish", callback_data=f"t:pp:{tid}:{user_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ Ishtirokchilar", callback_data=f"t:pl:{tid}:0"))
    return text, kb.as_markup()


async def _show_card(callback: CallbackQuery, test, user_id: int) -> None:
    text, kb = await _participant_card(test, user_id)
    if text is None:
        await callback.answer("Ishtirokchi topilmadi.", show_alert=True)
        return
    await services.edit_or_send(callback, text, kb)


@router.callback_query(F.data.startswith("t:pl:"))
async def participants_list(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    text, kb = await _participants_page(test, int(callback.data.split(":")[3]))
    await services.edit_or_send(callback, text, kb)
    await callback.answer()


@router.callback_query(F.data.startswith("t:pu:"))
async def participant_view(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    await _show_card(callback, test, int(callback.data.split(":")[3]))
    await callback.answer()


@router.callback_query(F.data.startswith("t:ph:"))
async def participant_hide(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    target = int(callback.data.split(":")[3])
    done = await db.set_hidden(test["id"], target, db.HIDDEN_BY_OWNER, only_if=0)
    await callback.answer("🚫 Reytingdan chiqarildi." if done else "Bu natija allaqachon reytingda emas.")
    await _show_card(callback, test, target)


@router.callback_query(F.data.startswith("t:pr:"))
async def participant_restore(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    target = int(callback.data.split(":")[3])
    done = await db.set_hidden(test["id"], target, 0, only_if=db.HIDDEN_BY_OWNER)
    await callback.answer("♻️ Reytingga qaytarildi." if done else "Qaytarib bo'lmadi.")
    await _show_card(callback, test, target)


@router.callback_query(F.data.startswith("t:pp:"))
async def participant_report(callback: CallbackQuery, user) -> None:
    test = await _owned_test(callback, user)
    if test is None:
        return
    target = int(callback.data.split(":")[3])
    sub = await db.get_submission(test["id"], target)
    account = await db.get_user(target)
    if sub is None or account is None:
        await callback.answer("Ishtirokchi topilmadi.", show_alert=True)
        return
    if (test["id"], target) in _reported:
        await callback.answer("Bu ishtirokchi ustidan shikoyat allaqachon yuborilgan.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🚫 Bloklash", callback_data=f"adm:ban:{target}"),
           InlineKeyboardButton(text="✏️ Ismini bekor qilish", callback_data=f"adm:rename:{target}"))
    kb.row(InlineKeyboardButton(text="✅ E'tiborsiz qoldirish", callback_data="adm:ignore"))
    username = f"@{account['username']}" if account["username"] else "yo'q"
    text = (
        "📣 <b>Shikoyat: nomaqbul ishtirokchi</b>\n\n"
        f"👤 Ismi: <b>{escape(sub['full_name'])}</b>\n"
        f"Telegram nomi: {escape(account['tg_name'] or '—')}\n"
        f"Username: {escape(username)}\n"
        f"ID: <code>{target}</code>\n\n"
        f"📋 Test: {escape(test['title'])} (<code>{test['code']}</code>)\n"
        f"✍️ Shikoyatchi: {escape(user['full_name'] or '')} (<code>{user['id']}</code>)"
    )
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await callback.bot.send_message(admin_id, text, reply_markup=kb.as_markup())
            sent += 1
        except Exception:
            pass
    if not sent:
        await callback.answer("Shikoyatni yuborib bo'lmadi. Keyinroq urinib ko'ring.", show_alert=True)
        return
    _reported.add((test["id"], target))
    await callback.answer("📣 Shikoyat administratorga yuborildi. Rahmat!", show_alert=True)


# ---------------------------------------------------------------- tushunarsiz xabarlar (eng oxirgi handlerlar)
# Jarayon ichida kutilmagan narsa yuborilganda: hozir aynan nima kutilayotganini eslatamiz
STATE_HINTS = {
    "Reg:name": "ism va familiyangizni <b>matn</b> ko'rinishida yozing",
    "Profile:name": "yangi ism va familiyangizni <b>matn</b> ko'rinishida yozing",
    "Create:title": "test nomini <b>matn</b> ko'rinishida yozing",
    "Create:key": "javoblar kalitini <b>matn</b> ko'rinishida yuboring (masalan: <code>1A2B3C4D</code>)",
    "Create:points": "ballarni <b>matn</b> ko'rinishida yuboring (masalan: <code>1-10: 1.1; 11-20: 2.1</code>)",
    "Create:deadline": "muddatni tugmalardan tanlang yoki sanani yozing (masalan: <code>25.12.2026 18:00</code>)",
    "Create:confirm": "yuqoridagi <b>«✅ Testni yaratish»</b> yoki <b>«⬅️ Orqaga»</b> tugmasini bosing",
    "Solve:code": "test kodini <b>raqamlar</b> bilan yuboring (masalan: <code>48213</code>)",
    "Solve:answers": "javoblaringizni <b>matn</b> ko'rinishida yuboring (masalan: <code>1A2B3C4D</code>)",
    "Solve:confirm": "yuqoridagi <b>«✅ Yuborish»</b> yoki <b>«✏️ Tuzatish»</b> tugmasini bosing",
    "RatingSt:code": "test kodini yuboring yoki ro'yxatdan testni tanlang",
    "Admin:channel": "kanal username'i, ID raqami yoki kanaldan forward qilingan postni yuboring",
    "Admin:block": "foydalanuvchining ID raqamini yuboring",
    "Admin:badword": "taqiqlanadigan so'zni <b>matn</b> ko'rinishida yuboring",
    "Admin:certtext": "qiymatni <b>matn</b> ko'rinishida yuboring (o'chirish uchun: <code>-</code>)",
    "Admin:certlogo": "logotipni <b>rasm</b> yoki PNG fayl ko'rinishida yuboring",
    "KeyEdit:fix": "tuzatishlarni <b>savol raqami va yangi javob</b> ko'rinishida yuboring "
                   "(masalan: <code>5 B</code>)",
    "KeyEdit:full": "barcha savollarning to'g'ri javobini yuboring (masalan: <code>1A2B3C4D</code>)",
    "KeyEdit:points": "ballarni yuboring (masalan: <code>1-10: 1.1; 11-20: 2.1</code>)",
    "KeyEdit:confirm": "yuqoridagi <b>«✅ Saqlash»</b> yoki <b>«❌ Bekor qilish»</b> tugmasini bosing",
    "PostNote:text": "postga qo'shiladigan izohni <b>matn</b> ko'rinishida yuboring",
    "Admin:addadmin": "yangi adminning ID raqamini yuboring yoki uning xabarini forward qiling",
}


@router.message()
async def fallback(message: Message, state: FSMContext, user) -> None:
    current = await state.get_state()
    hint = STATE_HINTS.get(current or "")
    if hint:
        back = (current or "").startswith(("Create:", "Solve:"))
        await message.answer(
            f"🤔 Bu xabarni qabul qila olmadim.\n\nHozir {hint}.\n\n"
            "<i>Jarayonni to'xtatish uchun «❌ Bekor qilish»ni bosing.</i>",
            reply_markup=flow_kb(back=back),
        )
        return
    if current:
        await state.clear()
    await message.answer(
        "🤔 Bu xabarni tushunmadim.\n\n"
        "• Test javobini tekshirish uchun <b>test kodini</b> yuboring\n"
        "• Yoki quyidagi menyudan kerakli bo'limni tanlang 👇",
        reply_markup=main_menu(user["id"]),
    )


@router.callback_query()
async def fallback_callback(callback: CallbackQuery, state: FSMContext, user) -> None:
    # Eski xabardagi tugma: foydalanuvchi "qotib" qolmasligi uchun yo'l ko'rsatamiz
    await callback.answer("Bu tugma endi faol emas.")
    current = await state.get_state()
    hint = STATE_HINTS.get(current or "")
    if hint:
        await callback.bot.send_message(
            user["id"],
            f"ℹ️ Bu tugma eski xabarga tegishli.\n\nHozir {hint}.\n\n"
            "<i>Jarayonni to'xtatish uchun «❌ Bekor qilish»ni bosing.</i>",
        )
        return
    await callback.bot.send_message(
        user["id"],
        "ℹ️ Bu tugma eski xabarga tegishli va endi ishlamaydi.\n\nQuyidagi menyudan davom eting 👇",
        reply_markup=main_menu(user["id"]),
    )
