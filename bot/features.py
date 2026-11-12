"""Botdagi funksiyalarni admin paneldan yoqish/o'chirish (feature flags).

Har bir funksiyaning holati bazadagi settings jadvalida "feature.<kalit>" = "1"/"0" ko'rinishida saqlanadi.
Holatlar bot ishga tushganda xotiraga yuklanadi (load), shuning uchun on() bazaga murojaat qilmaydi va
tugmalar chizadigan oddiy (sinxron) funksiyalarda ham ishlatiladi.

Yangi funksiya qo'shish: FEATURES ro'yxatiga yozing va kodda `features.on("kalit")` bilan tekshiring.
O'chirilgan funksiya foydalanuvchiga ko'rinmaydi, lekin u bilan bog'liq mavjud ma'lumotlar o'chmaydi.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import db

_PREFIX = "feature."
OFF_TEXT = "Bu funksiya hozircha o'chirilgan."


@dataclass(frozen=True)
class Feature:
    key: str
    title: str
    description: str
    group: str
    basic: bool  # «Oddiy rejim»da yoqilganmi (birinchi ishga tushishdagi holat ham shu)


GROUPS = {
    "author": "👨‍🏫 Test yaratish (muallif uchun)",
    "student": "🧑‍🎓 Ishtirokchilar uchun",
    "general": "⚙️ Umumiy",
}

FEATURES: list[Feature] = [
    # --- muallif
    Feature("custom_points", "Savollarga alohida ball",
            "Test yaratishda har bir savolga turli ball berish (1-10: 1.1 kabi). O'chiq bo'lsa — har bir savol 1 ball.",
            "author", basic=False),
    Feature("deadline", "Muddat belgilash",
            "Test yaratishda javob qabul qilish muddati; muddat tugagach test o'zi yakunlanadi.",
            "author", basic=False),
    Feature("open_questions", "Ochiq (yozma javobli) savollar",
            "Kalitda A–D dan tashqari son yoki matn javoblar (12.5, x=2). O'chiq bo'lsa — faqat A, B, C, D.",
            "author", basic=False),
    Feature("key_edit", "Kalitni tahrirlash",
            "Test yaratilgandan keyin kalitdagi xatoni tuzatish; barcha natijalar qayta hisoblanadi.",
            "author", basic=True),
    Feature("excel", "Excel hisobot",
            "Natijalar va har bir savol tahlilini Excel faylda yuklab olish.",
            "author", basic=True),
    Feature("post_note", "Postga izoh qo'shish",
            "O'quvchilar uchun tayyor postga muallif o'z matnini qo'shadi.",
            "author", basic=True),
    Feature("participants", "Ishtirokchilarni boshqarish",
            "Muallif nomaqbul ishtirokchini reytingdan chiqaradi yoki adminga shikoyat qiladi.",
            "author", basic=True),
    # --- ishtirokchi
    Feature("rating", "Reyting",
            "Ishtirokchilar test reytingini va o'z o'rnini ko'radi. O'chiq bo'lsa — reytingni faqat muallif ko'radi.",
            "student", basic=True),
    Feature("certificate", "Sertifikat",
            "Ishtirokchi natijasi bo'yicha sertifikat yoki diplom (rasm va PDF) oladi.",
            "student", basic=False),
    Feature("show_answers", "To'g'ri javoblarni ko'rsatish",
            "Test yakunlangach ishtirokchi xato javoblarining to'g'risini ko'radi.",
            "student", basic=True),
    Feature("confirm_submit", "Yuborishdan oldin tasdiqlash",
            "Javoblar yuborilishidan oldin ko'rib chiqish oynasi chiqadi (xato yuborishning oldini oladi).",
            "student", basic=True),
    Feature("finish_notify", "Yakuniy natija xabari",
            "Test yakunlanganda har bir ishtirokchiga yakuniy natijasi yuboriladi.",
            "student", basic=True),
    # --- umumiy
    Feature("subscription", "Majburiy obuna",
            "Botdan foydalanish uchun admin panelda qo'shilgan kanallarga obuna bo'lish talab qilinadi.",
            "general", basic=True),
    Feature("word_filter", "Nomaqbul so'zlar filtri",
            "Ism, test nomi va izohlarda so'kinish so'zlari qabul qilinmaydi.",
            "general", basic=True),
]
BY_KEY = {f.key: f for f in FEATURES}

_state: dict[str, bool] = {}


async def load() -> None:
    """Bazadagi holatlarni xotiraga yuklaydi (bot ishga tushganda)."""
    _state.clear()
    for feature in FEATURES:
        value = await db.get_setting(_PREFIX + feature.key)
        _state[feature.key] = feature.basic if value is None else value == "1"


def on(key: str) -> bool:
    if key not in BY_KEY:
        raise KeyError(f"Noma'lum funksiya: {key}")
    return _state.get(key, BY_KEY[key].basic)


async def set_value(key: str, value: bool) -> None:
    if key not in BY_KEY:
        raise KeyError(f"Noma'lum funksiya: {key}")
    await db.set_setting(_PREFIX + key, "1" if value else "0")
    _state[key] = value


async def apply_preset(name: str) -> None:
    """name: "basic" - oddiy rejim, "full" - hammasi yoqilgan."""
    for feature in FEATURES:
        await set_value(feature.key, True if name == "full" else feature.basic)


def mode() -> str:
    """Hozirgi rejim nomi: «Oddiy», «To'liq» yoki «Maxsus»."""
    if all(on(f.key) == f.basic for f in FEATURES):
        return "🟢 Oddiy"
    if all(on(f.key) for f in FEATURES):
        return "🔵 To'liq"
    return "🟡 Maxsus"
