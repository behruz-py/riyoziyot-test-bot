from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import db
from ..keyboards import BTN_CANCEL, BTN_HELP, BTN_PROFILE, cancel_kb, main_menu
from ..subscription import PENDING_START
from . import solve

router = Router(name="start")
router.message.filter(F.chat.type == "private")


class Reg(StatesGroup):
    name = State()


class Profile(StatesGroup):
    name = State()


HELP_TEXT = (
    "ℹ️ <b>Botdan foydalanish</b>\n\n"
    "<b>👨‍🏫 Test yaratish</b>\n"
    "«➕ Test yaratish» → test nomi → to'g'ri javoblar kaliti → ball tizimi → muddat (ixtiyoriy).\n"
    "Bot sizga <b>test kodi</b> beradi — uni o'quvchilarga tarqatasiz.\n\n"
    "<b>🔑 Kalit formatlari</b>\n"
    "• <code>abcdabcd</code> — har bir harf bitta savol\n"
    "• <code>1a2b3c4d</code> — raqamli\n"
    "• Ochiq (yozma) javobli savollar bo'lsa, har bir javob yangi qatordan:\n"
    "<code>1. a\n2. 12.5\n3. x=2</code>\n"
    "Ochiq javobda bir nechta to'g'ri variant: <code>0.5|1/2</code>\n\n"
    "<b>🧑‍🎓 Javobni tekshirish</b>\n"
    "«✅ Javobni tekshirish» → test kodi → javoblaringiz.\n"
    "Tezkor usul: <code>12345*abcdabcd</code> (kod*javoblar).\n"
    "Javob bermoqchi bo'lmagan savolga <code>-</code> qo'ying.\n"
    "❗️ Har bir testga faqat <b>bir marta</b> javob yuborish mumkin.\n\n"
    "<b>🏆 Natijalar</b>\n"
    "Natijada to'g'ri javoblar soni, ball, o'rningiz va xato javoblaringiz ko'rsatiladi. "
    "To'g'ri javoblar test yakunlangach ochiladi. Sertifikatni natija ostidagi tugma orqali olasiz.\n\n"
    "/cancel — boshlangan amalni bekor qilish"
)


def valid_name(text: str) -> str | None:
    name = " ".join(text.split())
    if 3 <= len(name) <= 60 and any(ch.isalpha() for ch in name) and not name.startswith("/"):
        return name
    return None


async def enter(bot: Bot, state: FSMContext, user) -> None:
    """Obuna tekshiruvidan o'tgan foydalanuvchini kutib oladi."""
    uid = user["id"]
    if not user["full_name"]:
        await state.set_state(Reg.name)
        await bot.send_message(
            uid,
            "👋 Assalomu alaykum! Test botiga xush kelibsiz.\n\n"
            "Iltimos, <b>ism va familiyangizni</b> yuboring.\n"
            "<i>U reyting, hisobot va sertifikatlarda ko'rsatiladi (masalan: Aliyev Vali).</i>",
        )
        return
    await bot.send_message(
        uid, f"🏠 Asosiy menyu. Xush kelibsiz, <b>{escape(user['full_name'])}</b>!", reply_markup=main_menu(uid)
    )
    payload = PENDING_START.pop(uid, None)
    if payload and payload.startswith("test_") and payload[5:].isdigit():
        await solve.open_test(bot, state, user, payload[5:])


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
        await message.answer("Ism familiya 3–60 belgidan iborat bo'lishi kerak. Qaytadan yuboring:")
        return
    await db.set_full_name(user["id"], name)
    await state.clear()
    await enter(message.bot, state, await db.get_user(user["id"]))


# Ro'yxatdan o'tmaganlar boshqa hech narsa qila olmaydi
@router.message(lambda message, user: not user["full_name"])
async def need_reg_message(message: Message, state: FSMContext, user) -> None:
    await enter(message.bot, state, user)


@router.callback_query(lambda callback, user: not user["full_name"])
async def need_reg_callback(callback: CallbackQuery, state: FSMContext, user) -> None:
    await callback.answer()
    await enter(callback.bot, state, user)


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cancel(message: Message, user) -> None:
    # Holat UserMiddleware ichida tozalangan
    await message.answer("Bekor qilindi.", reply_markup=main_menu(user["id"]))


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def help_cmd(message: Message, user) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_menu(user["id"]))


@router.message(F.text == BTN_PROFILE)
async def profile(message: Message, user) -> None:
    created = await db.count_tests_by_owner(user["id"])
    solved = await db.count_submissions_by_user(user["id"])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✏️ Ismni o'zgartirish", callback_data="profile:name")]]
    )
    await message.answer(
        "👤 <b>Profil</b>\n\n"
        f"Ism familiya: <b>{escape(user['full_name'])}</b>\n"
        f"ID: <code>{user['id']}</code>\n"
        f"Yaratgan testlaringiz: <b>{created}</b>\n"
        f"Ishlagan testlaringiz: <b>{solved}</b>",
        reply_markup=kb,
    )


@router.callback_query(F.data == "profile:name")
async def profile_name(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(Profile.name)
    await callback.bot.send_message(
        callback.from_user.id,
        "Yangi ism va familiyangizni yuboring.\n"
        "<i>Avval topshirilgan testlardagi ism o'zgarmaydi.</i>",
        reply_markup=cancel_kb(),
    )


@router.message(Profile.name, F.text)
async def profile_name_set(message: Message, state: FSMContext, user) -> None:
    name = valid_name(message.text)
    if not name:
        await message.answer("Ism familiya 3–60 belgidan iborat bo'lishi kerak. Qaytadan yuboring:")
        return
    await db.set_full_name(user["id"], name)
    await state.clear()
    await message.answer(f"✅ Saqlandi: <b>{escape(name)}</b>", reply_markup=main_menu(user["id"]))
