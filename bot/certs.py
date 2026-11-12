"""Sertifikat berish va haqiqiyligini tekshirish.

Har bir sertifikatda QR kod bor: u botga `?start=cert_<id>_<imzo>` havolasi bilan olib keladi va bot
bazadagi haqiqiy ma'lumotni ko'rsatadi. Imzo (HMAC) boshqalarning natijalarini raqamlarni terib
ko'rib chiqishdan himoya qiladi. Maxfiy kalit bazada (settings) saqlanadi va zaxira nusxaga kiradi.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from io import BytesIO

from aiogram import Bot

from . import db, keyparser as kp, services
from .certificate import build_certificate, pick_tier, tier_title

# Admin paneldan sozlanadigan qiymatlar (settings jadvali)
KEY_ORG = "cert_org"
KEY_SIGNER = "cert_signer"
KEY_ROLE = "cert_role"
KEY_LOGO = "cert_logo"  # Telegram file_id
_KEY_SECRET = "cert_secret"
SETTING_KEYS = (KEY_ORG, KEY_SIGNER, KEY_ROLE, KEY_LOGO)
MAX_LOGO_BYTES = 5 * 1024 * 1024

_settings: dict[str, str | None] | None = None
_secret: str | None = None
_logo_cache: tuple[str, bytes] | None = None  # (file_id, rasm baytlari)


async def settings() -> dict[str, str | None]:
    global _settings
    if _settings is None:
        _settings = {key: await db.get_setting(key) or None for key in SETTING_KEYS}
    return _settings


async def set_value(key: str, value: str | None) -> None:
    """value=None yoki bo'sh - qiymatni o'chiradi."""
    global _logo_cache
    await db.set_setting(key, value or "")
    (await settings())[key] = value or None
    if key == KEY_LOGO:
        _logo_cache = None


def reset_cache() -> None:
    global _settings, _secret, _logo_cache
    _settings = _secret = _logo_cache = None


async def logo_bytes(bot: Bot) -> bytes | None:
    """Logotip rasmini qaytaradi (Telegram'dan bir marta yuklab, xotirada saqlaydi)."""
    global _logo_cache
    file_id = (await settings())[KEY_LOGO]
    if not file_id:
        return None
    if _logo_cache and _logo_cache[0] == file_id:
        return _logo_cache[1]
    try:
        buf = await bot.download(file_id, destination=BytesIO())
        data = buf.getvalue()
    except Exception:
        return None  # logotip yuklanmasa ham sertifikat berilaveradi
    _logo_cache = (file_id, data)
    return data


# ---------------------------------------------------------------- raqam va tekshirish havolasi
async def _get_secret() -> str:
    global _secret
    if _secret is None:
        _secret = await db.get_setting(_KEY_SECRET)
        if not _secret:
            _secret = secrets.token_hex(16)
            await db.set_setting(_KEY_SECRET, _secret)
    return _secret


async def _sign(sub_id: int) -> str:
    key = (await _get_secret()).encode()
    return hmac.new(key, str(sub_id).encode(), hashlib.sha256).hexdigest()[:10]


async def token(sub_id: int) -> str:
    return f"{sub_id}_{await _sign(sub_id)}"


async def parse_token(value: str) -> int | None:
    """To'g'ri imzolangan bo'lsa, natija (submission) id sini qaytaradi."""
    sub_id, _, signature = value.partition("_")
    if not sub_id.isdigit() or len(sub_id) > 12 or not signature:
        return None
    if not hmac.compare_digest(signature, await _sign(int(sub_id))):
        return None
    return int(sub_id)


def number(test, sub) -> str:
    return f"{test['code']}-{sub['id']:05d}"


# ---------------------------------------------------------------- sertifikat
async def _result(test, sub) -> dict:
    """Sertifikat va tekshiruv javobi uchun umumiy ma'lumotlar."""
    finished = not services.is_open(test)
    total_q = len(services.questions_of(test))
    if services.points_on():
        percent = sub["score"] * 100 / sub["max_score"] if sub["max_score"] else 0.0
    else:
        percent = sub["correct_count"] * 100 / total_q if total_q else 0.0
    rank = await db.rank_of(sub) if finished else None
    return {
        "finished": finished,
        "percent": percent,
        "rank": rank,
        "participants": await db.count_submissions(test["id"]),
        "tier": pick_tier(percent, rank, sub["score"]),
        "date": services.to_local(sub["submitted_at"])[:10],
        "number": number(test, sub),
    }


async def issue(bot: Bot, test, sub) -> tuple[bytes, bytes, dict]:
    """(PNG, PDF, ma'lumot) qaytaradi."""
    info = await _result(test, sub)
    conf = await settings()
    me = await bot.me()
    png, pdf = await asyncio.to_thread(
        build_certificate,
        name=sub["full_name"],
        title=test["title"],
        correct=sub["correct_count"],
        total_q=len(services.questions_of(test)),
        score=kp.fmt_num(sub["score"]),
        max_score=kp.fmt_num(sub["max_score"]),
        percent=info["percent"],
        rank=info["rank"],
        participants=info["participants"],
        date=info["date"],
        number=info["number"],
        tier=info["tier"],
        verify_url=f"https://t.me/{me.username}?start=cert_{await token(sub['id'])}",
        org=conf[KEY_ORG],
        signer=conf[KEY_SIGNER],
        signer_role=conf[KEY_ROLE],
        logo=await logo_bytes(bot),
        show_points=services.points_on(),
    )
    info["title"] = tier_title(info["tier"])
    return png, pdf, info


async def sample(bot: Bot) -> bytes:
    """Admin uchun namuna (hozirgi sozlamalar bilan)."""
    conf = await settings()
    me = await bot.me()
    png, _ = await asyncio.to_thread(
        build_certificate,
        name="Aliyev Vali", title="Namuna test", correct=27, total_q=30, score="27", max_score="30",
        percent=90.0, rank=1, participants=120, date=services.to_local(db.now_utc())[:10], number="00000-00000",
        tier="place1", verify_url=f"https://t.me/{me.username}", org=conf[KEY_ORG], signer=conf[KEY_SIGNER],
        signer_role=conf[KEY_ROLE], logo=await logo_bytes(bot), show_points=services.points_on(),
    )
    return png


async def verify_text(payload: str) -> str:
    """QR kod orqali kelgan so'rovga javob matni."""
    from html import escape

    sub_id = await parse_token(payload)
    sub = await db.get_submission_by_id(sub_id) if sub_id is not None else None
    test = await db.get_test(sub["test_id"]) if sub else None
    if sub is None or test is None:
        return (
            "❌ <b>Sertifikat topilmadi</b>\n\n"
            "Bunday sertifikat bazada yo'q. U soxta bo'lishi yoki test o'chirilgan bo'lishi mumkin."
        )
    if sub["is_hidden"]:
        return (
            "⚠️ <b>Sertifikat bekor qilingan</b>\n\n"
            f"№ {number(test, sub)}\n"
            "Bu ishtirokchining natijasi reytingdan chiqarilgan — sertifikat haqiqiy emas."
        )
    info = await _result(test, sub)
    place = (
        f"🏅 O'rin: <b>{info['rank']} / {info['participants']}</b>" if info["finished"]
        else "🏅 O'rin: test hali yakunlanmagan"
    )
    return (
        "✅ <b>Sertifikat haqiqiy</b>\n\n"
        f"№ <code>{info['number']}</code>\n"
        f"🎓 {tier_title(info['tier'])}\n"
        f"👤 <b>{escape(sub['full_name'])}</b>\n"
        f"📋 {escape(test['title'])}\n"
        + (f"💯 Ball: <b>{kp.fmt_num(sub['score'])} / {kp.fmt_num(sub['max_score'])}</b> "
           f"({services.percent(sub['score'], sub['max_score'])}%)\n" if services.points_on() else
           f"✅ To'g'ri javoblar: <b>{sub['correct_count']} / {len(services.questions_of(test))}</b> "
           f"({kp.fmt_num(info['percent'])}%)\n")
        +
        f"{place}\n"
        f"📅 Sana: {info['date']}\n\n"
        "<i>Qog'ozdagi ism, natija va o'rin shu ma'lumotlar bilan bir xil bo'lishi kerak. "
        "Farq qilsa — sertifikat o'zgartirilgan.</i>"
    )
