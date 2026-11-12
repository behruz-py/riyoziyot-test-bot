"""Botdagi xatolar haqida bosh adminlarga Telegram orqali xabar.

Ishlash tartibi: "bot.*" loggerlaridagi ERROR darajasidagi yozuvlar navbatga tushadi, fon vazifasi ularni
yuboradi. Bir xil xato (bir joy, bir tur) 15 daqiqada bir martadan ko'p yuborilmaydi - takrorlar sanaladi va
keyingi xabarda ko'rsatiladi. Umumiy chegara: soatiga 30 ta xabar. O'chirish: ERROR_ALERTS=0.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from datetime import datetime
from html import escape

from aiogram import Bot

from . import config

log = logging.getLogger(__name__)

REPEAT_WINDOW = 15 * 60  # bir xil xato uchun jimlik davri (soniya)
HOURLY_LIMIT = 30
TRACE_CHARS = 2500

_queue: asyncio.Queue | None = None
_loop: asyncio.AbstractEventLoop | None = None
_task: asyncio.Task | None = None
_handler: "AlertHandler | None" = None
_last_sent: dict[tuple, float] = {}
_suppressed: dict[tuple, int] = {}
_sent_times: list[float] = []


def _signature(record: logging.LogRecord) -> tuple:
    exc_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ""
    # Xato aynan qayerda chiqqanini (eng ichki kadr) hisobga olamiz: bir handler turli joyda yiqilsa - alohida
    where = ""
    if record.exc_info and record.exc_info[2]:
        frame = traceback.extract_tb(record.exc_info[2])[-1]
        where = f"{frame.filename}:{frame.lineno}"
    return record.name, record.lineno, exc_type, where


class AlertHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("bot") or record.name == __name__ or _queue is None or _loop is None:
            return
        try:
            item = (_signature(record), _format(record))
            _loop.call_soon_threadsafe(_queue.put_nowait, item)  # boshqa oqimdan ham xavfsiz
        except Exception:
            pass  # xabar tayyorlashdagi xato botni to'xtatmasligi kerak


def _format(record: logging.LogRecord) -> str:
    lines = [
        "🚨 <b>Botda xatolik</b>",
        f"🕒 {datetime.now(config.TZ):%d.%m.%Y %H:%M:%S}",
        f"📍 <code>{escape(record.name)}:{record.lineno}</code>",
        f"💬 {escape(record.getMessage()[:300])}",
    ]
    context = getattr(record, "alert_context", None)
    if context:
        lines.append(f"👤 {context}")
    if record.exc_info and record.exc_info[1] is not None:
        exc = record.exc_info[1]
        lines.append(f"❗️ <b>{escape(type(exc).__name__)}</b>: {escape(str(exc)[:300])}")
        lines.append(f"<pre>{escape(_short_trace(record.exc_info))}</pre>")
    return "\n".join(lines)


def _short_trace(exc_info) -> str:
    """Faqat botimiz kodidagi qatorlar (kutubxonalar ichi tushib qoladi) - xabar qisqa va tushunarli bo'ladi."""
    frames = traceback.extract_tb(exc_info[2])
    ours = [f for f in frames if str(config.BASE_DIR / "bot") in f.filename and ".venv" not in f.filename]
    shown = ours or frames[-3:]
    out = ["Traceback (bot kodi):"]
    for f in shown:
        path = f.filename.replace(str(config.BASE_DIR), "").lstrip("\\/").replace("\\", "/")
        out.append(f'  {path}:{f.lineno} — {f.name}()')
        if f.line:
            out.append(f"    {f.line.strip()}")
    out.append("".join(traceback.format_exception_only(exc_info[0], exc_info[1])).strip())
    return "\n".join(out)[-TRACE_CHARS:]


def _allowed(signature: tuple, now: float) -> bool:
    global _sent_times
    if now - _last_sent.get(signature, -REPEAT_WINDOW) < REPEAT_WINDOW:
        _suppressed[signature] = _suppressed.get(signature, 0) + 1
        return False
    _sent_times = [t for t in _sent_times if now - t < 3600]
    if len(_sent_times) >= HOURLY_LIMIT:
        _suppressed[signature] = _suppressed.get(signature, 0) + 1
        return False
    _last_sent[signature] = now
    _sent_times.append(now)
    return True


async def _sender(bot: Bot) -> None:
    while True:
        signature, text = await _queue.get()
        try:
            if not _allowed(signature, time.monotonic()):
                continue
            repeats = _suppressed.pop(signature, 0)
            if repeats:
                text += f"\n\n<i>Shu xato oxirgi xabardan beri yana {repeats} marta takrorlandi.</i>"
            for admin_id in config.SUPER_ADMIN_IDS:
                try:
                    await bot.send_message(admin_id, text)
                except Exception as e:  # ERROR emas: aks holda xabar yuborish xatosi o'zini o'zi chaqiradi
                    log.warning("Xato haqidagi xabar yuborilmadi (%s): %s", admin_id, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("Xato xabarini tayyorlab bo'lmadi: %s", e)
        finally:
            _queue.task_done()


def setup(bot: Bot) -> None:
    """Bot ishga tushganda chaqiriladi."""
    global _queue, _loop, _task, _handler
    if not config.ERROR_ALERTS or not config.SUPER_ADMIN_IDS:
        return
    _loop = asyncio.get_running_loop()
    _queue = asyncio.Queue(maxsize=200)
    _task = asyncio.create_task(_sender(bot))
    if _handler is None:
        _handler = AlertHandler()
        logging.getLogger("bot").addHandler(_handler)


def shutdown() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None


def reset() -> None:
    """Sinovlar uchun: cheklov hisoblagichlarini tozalaydi."""
    _last_sent.clear()
    _suppressed.clear()
    _sent_times.clear()
