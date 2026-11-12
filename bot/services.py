"""Umumiy yordamchi funksiyalar: vaqt, matn tuzish, testni yakunlash, muddat nazorati."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, CallbackQuery

from . import db, keyparser as kp
from .config import TZ
from .keyboards import result_kb

log = logging.getLogger(__name__)

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
_background_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    """Fon vazifasini ishga tushiradi (axlat yig'uvchi o'chirib yubormasligi uchun havolasi saqlanadi)."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------- vaqt
def to_local(utc_str: str | None) -> str:
    if not utc_str:
        return "—"
    dt = datetime.strptime(utc_str, db.TIME_FMT).replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def parse_local_deadline(text: str) -> str | None:
    """"25.12.2026 18:00" (mahalliy vaqt) -> UTC satr. Noto'g'ri format bo'lsa None."""
    text = " ".join(text.strip().replace(",", " ").split())
    now = datetime.now(TZ)
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%y %H:%M", "%d.%m %H:%M"):
        try:
            if fmt == "%d.%m %H:%M":
                # yilsiz: joriy yil qo'shib o'qiladi (29-fevral muammosiz ishlashi uchun)
                dt = datetime.strptime(f"{text} {now.year}", fmt + " %Y")
            else:
                dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=TZ).astimezone(timezone.utc).strftime(db.TIME_FMT)
    return None


def local_day_start(days_ago: int = 0) -> str:
    """Mahalliy vaqt bo'yicha (bugun - days_ago) kunining boshlanishi, UTC satr ko'rinishida."""
    midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return midnight.astimezone(timezone.utc).strftime(db.TIME_FMT)


def deadline_in(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime(db.TIME_FMT)


def is_open(test) -> bool:
    return bool(test["is_active"]) and (test["deadline"] is None or test["deadline"] > db.now_utc())


def questions_of(test) -> list[dict]:
    return json.loads(test["questions"])


# ---------------------------------------------------------------- xabar yuborish
async def send_long(bot: Bot, chat_id: int, lines: list[str], reply_markup=None) -> None:
    """Uzun matnni Telegram cheklovidan oshmaydigan bo'laklarga bo'lib yuboradi."""
    chunks, current, size = [], [], 0
    for line in lines:
        if size + len(line) + 1 > 3800 and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    for i, chunk in enumerate(chunks):
        await bot.send_message(chat_id, chunk, reply_markup=reply_markup if i == len(chunks) - 1 else None)


async def edit_or_send(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    """Tugma bosilgan xabarni tahrirlaydi; iloji bo'lmasa yangi xabar yuboradi."""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except (TelegramAPIError, AttributeError):
        await callback.bot.send_message(callback.from_user.id, text, reply_markup=reply_markup)


# ---------------------------------------------------------------- matnlar
def key_preview(questions: list[dict]) -> list[str]:
    """Kalitni ko'rsatish uchun qatorlar."""
    if all(q["t"] == "c" for q in questions):
        cells = [f"{i}{kp.fmt_answer(q['a'])}" for i, q in enumerate(questions, start=1)]
        return ["<code>" + "  ".join(cells[i:i + 5]) + "</code>" for i in range(0, len(cells), 5)]
    lines = []
    for i, q in enumerate(questions, start=1):
        mark = "" if q["t"] == "c" else " ✍️"
        lines.append(f"{i}) <code>{escape(kp.fmt_answer(q['a']))}</code>{mark}")
    return lines


def answers_preview(answers: list[str]) -> list[str]:
    """O'quvchi javoblarini tasdiqlash oynasida ko'rsatish uchun qatorlar."""
    if all(a == kp.SKIP or (len(a) == 1 and a in kp.LETTERS) for a in answers):
        cells = [f"{i}{kp.fmt_answer(a)}" for i, a in enumerate(answers, start=1)]
        return ["<code>" + "  ".join(cells[i:i + 5]) + "</code>" for i in range(0, len(cells), 5)]
    return [f"{i}) <code>{escape(kp.fmt_answer(a))}</code>" for i, a in enumerate(answers, start=1)]


def points_summary(questions: list[dict]) -> str:
    values = sorted({q["p"] for q in questions})
    total = kp.fmt_num(sum(q["p"] for q in questions))
    if len(values) == 1:
        return f"har bir savol {kp.fmt_num(values[0])} ball (jami {total})"
    return f"savollarga alohida ball (jami {total})"


def percent(score: float, max_score: float) -> str:
    return kp.fmt_num(score * 100 / max_score if max_score else 0)


def rank_line(pos: int, sub, total_q: int, me_id: int | None = None) -> str:
    prefix = MEDALS.get(pos, f"{pos}.")
    name = escape(sub["full_name"])
    if me_id is not None and sub["user_id"] == me_id:
        name = f"<b>{name}</b> 👈"
    return f"{prefix} {name} — <b>{kp.fmt_num(sub['score'])}</b> ball ({sub['correct_count']}/{total_q})"


def ranking_lines(test, subs: list, total: int, me_id: int | None = None) -> list[str]:
    total_q = len(questions_of(test))
    status = "yakuniy" if not is_open(test) else "joriy"
    lines = [f"🏆 <b>{escape(test['title'])}</b> — {status} reyting", f"👥 Ishtirokchilar: {total} nafar", ""]
    if not subs:
        lines.append("Hozircha hech kim javob yubormagan.")
    lines += [rank_line(pos, s, total_q, me_id) for pos, s in enumerate(subs, start=1)]
    if total > len(subs):
        lines.append(f"… va yana {total - len(subs)} nafar ishtirokchi")
    return lines


def result_lines(test, sub, rank: int, total: int) -> list[str]:
    questions = questions_of(test)
    answers = json.loads(sub["answers"])
    res = kp.grade(questions, answers)
    finished = not is_open(test)
    lines = [
        f"📋 <b>{escape(test['title'])}</b> (kod: <code>{test['code']}</code>)",
        f"👤 {escape(sub['full_name'])}",
        "",
        f"✅ To'g'ri javoblar: <b>{sub['correct_count']} / {len(questions)}</b>",
        f"💯 Ball: <b>{kp.fmt_num(sub['score'])} / {kp.fmt_num(sub['max_score'])}</b> "
        f"({percent(sub['score'], sub['max_score'])}%)",
        f"🏅 O'rin: <b>{rank} / {total}</b> ({'yakuniy' if finished else 'hozircha'})",
        f"🕒 Topshirilgan: {to_local(sub['submitted_at'])}",
        "",
    ]
    wrong = [i for i, f in enumerate(res["flags"]) if f == 0]
    skipped = [i for i, f in enumerate(res["flags"]) if f == -1]
    if not wrong and not skipped:
        lines.append("🎉 Barcha javoblaringiz to'g'ri. Barakalla!")
        return lines
    if wrong:
        lines.append(f"❌ <b>Xato javoblar ({len(wrong)} ta):</b>")
        for i in wrong:
            line = f"{i + 1}) siz: <code>{escape(kp.fmt_answer(answers[i]))}</code>"
            if finished:
                line += f" → to'g'ri: <code>{escape(kp.fmt_answer(questions[i]['a']))}</code>"
            lines.append(line)
    if skipped:
        lines.append(f"⚪️ <b>Javobsiz ({len(skipped)} ta):</b> " + ", ".join(str(i + 1) for i in skipped))
        if finished:
            lines += [
                f"{i + 1}) to'g'ri: <code>{escape(kp.fmt_answer(questions[i]['a']))}</code>" for i in skipped
            ]
    if not finished:
        lines += ["", "ℹ️ To'g'ri javoblar test yakunlangach «📊 Natijalarim» bo'limida ko'rinadi."]
    return lines


async def show_result(bot: Bot, chat_id: int, test, sub) -> None:
    if sub["is_hidden"]:
        await bot.send_message(
            chat_id,
            f"📋 <b>{escape(test['title'])}</b>\n\n"
            "🚫 Sizning natijangiz bu test reytingidan chiqarilgan "
            f"({'administrator' if sub['is_hidden'] == db.HIDDEN_BY_BAN else 'test muallifi'} qarori bilan).\n\n"
            "<i>Odatda bunga nomaqbul ism yoki test qoidalarini buzish sabab bo'ladi.</i>",
        )
        return
    rank = await db.rank_of(sub)
    total = await db.count_submissions(test["id"])
    await send_long(bot, chat_id, result_lines(test, sub, rank, total), reply_markup=result_kb(test["id"]))


# ---------------------------------------------------------------- yakunlash
async def finish_and_notify(bot: Bot, test_id: int, auto: bool = False) -> bool:
    """Testni yakunlaydi, muallifga hisobot, ishtirokchilarga yakuniy natijani yuboradi."""
    if not await db.finish_test(test_id):
        return False
    test = await db.get_test(test_id)
    subs = list(await db.submissions_ranked(test_id))
    try:
        head = "⏰ Muddat tugadi — test avtomatik yakunlandi." if auto else "🏁 Test yakunlandi."
        await send_long(bot, test["owner_id"], [head, ""] + ranking_lines(test, subs[:30], len(subs)))
        if subs:
            from .excel import build_report  # og'ir import faqat kerak bo'lganda

            data = await asyncio.to_thread(build_report, dict(test), [dict(s) for s in subs])
            await bot.send_document(
                test["owner_id"],
                BufferedInputFile(data, filename=f"natijalar_{test['code']}.xlsx"),
                caption="📥 To'liq natijalar va savollar tahlili",
            )
    except TelegramAPIError as e:
        log.warning("Muallifga hisobot yuborilmadi (test %s): %s", test_id, e)
    if subs:
        spawn(_notify_participants(bot, test, subs))
    return True


async def _notify_participants(bot: Bot, test, subs: list) -> None:
    total = len(subs)
    for pos, sub in enumerate(subs, start=1):
        text = (
            f"🏁 <b>{escape(test['title'])}</b> testi yakunlandi!\n\n"
            f"🏅 Yakuniy o'rningiz: <b>{pos} / {total}</b>\n"
            f"💯 Ball: <b>{kp.fmt_num(sub['score'])} / {kp.fmt_num(sub['max_score'])}</b>\n\n"
            "To'g'ri javoblarni «📊 Natijalarim» bo'limida ko'rishingiz mumkin."
        )
        for _ in range(2):
            try:
                await bot.send_message(sub["user_id"], text, reply_markup=result_kb(test["id"]))
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                await db.set_inactive(sub["user_id"])
                break
            except TelegramAPIError:
                break
        await asyncio.sleep(0.05)


_deadlines_dirty = True
_next_deadline: str | None = None


def deadlines_changed() -> None:
    """Muddatli test yaratilganda/yakunlanganda/o'chirilganda chaqiriladi."""
    global _deadlines_dirty
    _deadlines_dirty = True


async def deadline_watcher(bot: Bot, interval: float = 20) -> None:
    """Muddati o'tgan testlarni avtomatik yakunlaydi. Bot qayta ishga tushsa ham bazadan davom etadi.

    Eng yaqin muddat xotirada saqlanadi: bazaga faqat kerak bo'lganda murojaat qilinadi
    (aks holda Neon bazasi hech qachon "uxlamaydi" va bepul limit tez tugaydi).
    """
    global _deadlines_dirty, _next_deadline
    _deadlines_dirty = True
    while True:
        try:
            if _deadlines_dirty:
                _deadlines_dirty = False
                _next_deadline = await db.next_deadline()
            if _next_deadline is not None and _next_deadline <= db.now_utc():
                _deadlines_dirty = True
                for test in await db.expired_tests():
                    await finish_and_notify(bot, test["id"], auto=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            _deadlines_dirty = True
            log.exception("Muddat nazoratida xatolik")
        await asyncio.sleep(interval)
