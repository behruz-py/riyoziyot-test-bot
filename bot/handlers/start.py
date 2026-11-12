from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from .. import certs, db, moderation
from ..keyboards import BTN_BACK, BTN_CANCEL, BTN_HELP, BTN_PROFILE, cancel_kb, home_btn, main_menu
from ..subscription import PENDING_START
from . import solve

router = Router(name="start")
router.message.filter(F.chat.type == "private")


class Reg(StatesGroup):
    name = State()


class Profile(StatesGroup):
    name = State()


MENU_TEXT = (
    "🏠 <b>Asosiy menyu</b>\n\n"
    "✅ <b>Javobni tekshirish</b> — test kodi bo'yicha javoblaringizni tekshiring\n"
    "➕ <b>Test yaratish</b> — o'z testingizni o'tkazing\n"
    "📊 <b>Natijalarim</b> · 📚 <b>Mening testlarim</b> · 🏆 <b>Reyting</b>\n\n"
    "Kerakli bo'limni tanlang 👇"
)

HELP_TEXT = (
    "ℹ️ <b>Yordam</b>\n\n"
    "<b>🧑‍🎓 Test javobini tekshirish</b>\n"
    "1. «✅ Javobni tekshirish» tugmasini bosing\n"
    "2. O'qituvchi bergan <b>test kodini</b> yuboring\n"
    "3. Javoblaringizni yuboring: <code>abcdabcd</code> yoki <code>1a2b3c4d</code>\n"
    "4. Javoblarni ko'zdan kechirib, <b>«✅ Yuborish»</b>ni bosing\n\n"
    "• Javob bermaydigan savolga <code>-</code> qo'ying\n"
    "• Tezkor usul: <code>12345*abcdabcd</code> (kod*javoblar)\n"
    "• Har bir testga faqat <b>bir marta</b> javob yuboriladi\n"
    "• To'g'ri javoblar test yakunlangach ochiladi\n\n"
    "<b>👨‍🏫 Test yaratish</b>\n"
    "1. «➕ Test yaratish» → test nomi\n"
    "2. To'g'ri javoblar kaliti: <code>abcdabcd</code>\n"
    "3. Ball tizimi va muddat (ixtiyoriy)\n"
    "4. Bot bergan <b>test kodini</b> o'quvchilarga tarqating\n\n"
    "Natijalar, Excel hisobot va testni yakunlash — «📚 Mening testlarim» bo'limida.\n\n"
    "<b>✍️ Ochiq (yozma) javobli savollar</b>\n"
    "Har bir javob yangi qatordan yoziladi:\n"
    "<code>1. a\n2. 12.5\n3. x=2</code>\n\n"
    "<b>🧭 Adashib qolsangiz</b>\n"
    "«❌ Bekor qilish» yoki /start — istalgan joydan asosiy menyuga qaytaradi."
)

NAME_ERROR = (
    "⚠️ Ism va familiya 3–60 belgidan iborat bo'lishi va <b>faqat harflardan</b> tashkil topishi kerak "
    "(raqam, belgi va emoji mumkin emas).\n\n"
    "Qaytadan yozing (masalan: <i>Aliyev Vali</i>):"
)
BAD_NAME_ERROR = (
    "⚠️ Bu ismni qabul qila olmaymiz.\n\n"
    "Iltimos, <b>haqiqiy ism va familiyangizni</b> yozing — u reyting va sertifikatda boshqalarga ko'rinadi."
)
_NAME_EXTRA_CHARS = " '-.’ʻʼ‘`"


def valid_name(text: str) -> str | None:
    """Ism faqat harflar, bo'shliq, tire, nuqta va apostrofdan iborat bo'lishi mumkin."""
    name = " ".join(text.split())
    if not (3 <= len(name) <= 60):
        return None
    if not all(ch.isalpha() or ch in _NAME_EXTRA_CHARS for ch in name):
        return None
    if sum(1 for ch in name if ch.isalpha()) < 3:
        return None
    return name


async def send_menu(bot: Bot, user_id: int, text: str = MENU_TEXT) -> None:
    await bot.send_message(user_id, text, reply_markup=main_menu(user_id))


async def enter(bot: Bot, state: FSMContext, user) -> None:
    """Obuna tekshiruvidan o'tgan foydalanuvchini kutib oladi."""
    uid = user["id"]
    if not user["full_name"]:
        await state.set_state(Reg.name)
        suggestion = valid_name(user["tg_name"] or "")
        if suggestion and await moderation.is_bad(suggestion):
            suggestion = None
        keyboard = (
            ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=suggestion)]], resize_keyboard=True,
                input_field_placeholder="Ism va familiyangiz",
            )
            if suggestion else ReplyKeyboardRemove()
        )
        await bot.send_message(
            uid,
            "👋 <b>Assalomu alaykum!</b>\n\n"
            "Bu bot yordamida test javoblaringizni bir zumda tekshirasiz, natija va reytingni ko'rasiz, "
            "o'zingiz ham test o'tkaza olasiz.\n\n"
            "Boshlash uchun <b>ism va familiyangizni</b> yozing — u reyting va sertifikatda ko'rsatiladi.\n"
            "<i>Masalan: Aliyev Vali</i>"
            + ("\n\nYoki quyidagi tugmani bosib, Telegram'dagi ismingizni tanlang 👇" if suggestion else ""),
            reply_markup=keyboard,
        )
        return
    payload = PENDING_START.pop(uid, None)
    if payload and payload.startswith("cert_"):
        await bot.send_message(uid, await certs.verify_text(payload[5:]), reply_markup=main_menu(uid))
        return
    if payload and payload.startswith("test_") and payload[5:].isdigit():
        await bot.send_message(uid, f"👋 Xush kelibsiz, <b>{escape(user['full_name'])}</b>!", reply_markup=main_menu(uid))
        await solve.open_test(bot, state, user, payload[5:])
        return
    await send_menu(bot, uid, f"👋 Xush kelibsiz, <b>{escape(user['full_name'])}</b>!\n\n{MENU_TEXT}")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, user) -> None:
    if command.args:
        PENDING_START[user["id"]] = command.args.strip()
    await enter(message.bot, state, user)


@router.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery, state: FSMContext, user) -> None:
    # Bu yerga faqat obuna tasdiqlangandan keyin yetib kelinadi (SubscriptionMiddleware)
    await callback.answer("✅ Obuna tasdiqlandi. Rahmat!")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await enter(callback.bot, state, user)


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext, user) -> None:
    name = valid_name(message.text)
    if not name:
        await message.answer(NAME_ERROR)
        return
    if await moderation.is_bad(name):
        await message.answer(BAD_NAME_ERROR)
        return
    await db.set_full_name(user["id"], name)
    await state.clear()
    await message.answer(
        f"✅ Rahmat, <b>{escape(name)}</b>! Ro'yxatdan o'tdingiz.\n"
        "<i>Ismni keyinroq «👤 Profil» bo'limida o'zgartirishingiz mumkin.</i>"
    )
    await enter(message.bot, state, await db.get_user(user["id"]))


# Ro'yxatdan o'tmaganlar boshqa hech narsa qila olmaydi
@router.message(lambda message, user: not user["full_name"])
async def need_reg_message(message: Message, state: FSMContext, user) -> None:
    await enter(message.bot, state, user)


@router.callback_query(lambda callback, user: not user["full_name"])
async def need_reg_callback(callback: CallbackQuery, state: FSMContext, user) -> None:
    await callback.answer()
    await enter(callback.bot, state, user)


@router.callback_query(F.data == "home")
async def home(callback: CallbackQuery, state: FSMContext, user) -> None:
    await state.clear()
    await callback.answer()
    await send_menu(callback.bot, user["id"])


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cancel(message: Message, user) -> None:
    # Holat UserMiddleware ichida tozalangan
    await send_menu(message.bot, user["id"], "❌ Bekor qilindi.\n\n" + MENU_TEXT)


@router.message(StateFilter(None), F.text == BTN_BACK)
async def back_to_menu(message: Message, user) -> None:
    await send_menu(message.bot, user["id"])


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def help_cmd(message: Message, user) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Javobni tekshirish", callback_data="go:check"),
        InlineKeyboardButton(text="➕ Test yaratish", callback_data="go:create"),
    ]])
    await message.answer(HELP_TEXT, reply_markup=kb)


@router.message(F.text == BTN_PROFILE)
async def profile(message: Message, user) -> None:
    created = await db.count_tests_by_owner(user["id"])
    solved = await db.count_submissions_by_user(user["id"])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ismni o'zgartirish", callback_data="profile:name")],
        [home_btn()],
    ])
    await message.answer(
        "👤 <b>Profil</b>\n\n"
        f"Ism familiya: <b>{escape(user['full_name'])}</b>\n"
        f"ID: <code>{user['id']}</code>\n\n"
        f"✅ Ishlagan testlaringiz: <b>{solved}</b> ta\n"
        f"📚 Yaratgan testlaringiz: <b>{created}</b> ta",
        reply_markup=kb,
    )


@router.callback_query(F.data == "profile:name")
async def profile_name(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Profile.name)
    await callback.bot.send_message(
        callback.from_user.id,
        "✏️ Yangi <b>ism va familiyangizni</b> yozing.\n\n"
        "<i>Avval topshirilgan testlardagi ismingiz o'zgarmaydi.</i>",
        reply_markup=cancel_kb("Ism va familiya"),
    )


@router.message(Profile.name, F.text)
async def profile_name_set(message: Message, state: FSMContext, user) -> None:
    name = valid_name(message.text)
    if not name:
        await message.answer(NAME_ERROR)
        return
    if await moderation.is_bad(name):
        await message.answer(BAD_NAME_ERROR)
        return
    await db.set_full_name(user["id"], name)
    await state.clear()
    await message.answer(f"✅ Ismingiz saqlandi: <b>{escape(name)}</b>", reply_markup=main_menu(user["id"]))
