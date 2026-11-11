from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, LinkPreviewOptions, ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import is_admin

BTN_CREATE = "➕ Test yaratish"
BTN_CHECK = "✅ Javobni tekshirish"
BTN_MY_TESTS = "📚 Mening testlarim"
BTN_MY_RESULTS = "📊 Natijalarim"
BTN_RATING = "🏆 Reyting"
BTN_PROFILE = "👤 Profil"
BTN_HELP = "ℹ️ Yordam"
BTN_ADMIN = "🛠 Admin panel"
BTN_CANCEL = "❌ Bekor qilish"
BTN_BACK = "⬅️ Orqaga"

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# Bu tugmalar bosilganda har qanday boshlangan jarayon (holat) bekor qilinadi
MENU_BUTTONS = {
    BTN_CREATE, BTN_CHECK, BTN_MY_TESTS, BTN_MY_RESULTS, BTN_RATING, BTN_PROFILE, BTN_HELP, BTN_ADMIN, BTN_CANCEL,
}

# «⬅️ Orqaga» tugmasini o'zi qayta ishlaydigan jarayonlar (qolganlarida u asosiy menyuga qaytaradi)
BACK_AWARE_STATES = ("Create:", "Solve:")


def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_CHECK), KeyboardButton(text=BTN_CREATE)],
        [KeyboardButton(text=BTN_MY_RESULTS), KeyboardButton(text=BTN_MY_TESTS)],
        [KeyboardButton(text=BTN_RATING), KeyboardButton(text=BTN_PROFILE)],
        [KeyboardButton(text=BTN_HELP)],
    ]
    if is_admin(user_id):
        rows[-1].append(KeyboardButton(text=BTN_ADMIN))
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder="Bo'limni tanlang…")


def flow_kb(back: bool = True, placeholder: str | None = None) -> ReplyKeyboardMarkup:
    """Jarayon ichidagi klaviatura: orqaga / bekor qilish."""
    row = [KeyboardButton(text=BTN_CANCEL)]
    if back:
        row.insert(0, KeyboardButton(text=BTN_BACK))
    return ReplyKeyboardMarkup(keyboard=[row], resize_keyboard=True, input_field_placeholder=placeholder)


def cancel_kb(placeholder: str | None = None) -> ReplyKeyboardMarkup:
    return flow_kb(back=False, placeholder=placeholder)


def home_btn() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="home")


def subscribe_kb(channels) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ch in channels:
        kb.row(InlineKeyboardButton(text=f"📢 {ch['title']}", url=ch["url"]))
    kb.row(InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub"))
    return kb.as_markup()


def result_kb(test_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🏆 Reyting", callback_data=f"rating:{test_id}"),
        InlineKeyboardButton(text="🎓 Sertifikat", callback_data=f"cert:{test_id}"),
    )
    kb.row(InlineKeyboardButton(text="✅ Yana test tekshirish", callback_data="go:check"), home_btn())
    return kb.as_markup()


def pager(prefix: str, page: int, pages: int) -> list[InlineKeyboardButton]:
    """Sahifalash tugmalari qatori (bitta sahifa bo'lsa bo'sh)."""
    if pages <= 1:
        return []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:{page - 1}"))
    row.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        row.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:{page + 1}"))
    return row
