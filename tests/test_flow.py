"""To'liq ssenariy sinovi (internet va haqiqiy token kerak emas).

Ishga tushirish: .venv\\Scripts\\python -m tests.test_flow
"""
import asyncio
import itertools
import os
import tempfile
from datetime import datetime
from pathlib import Path

os.environ["BOT_TOKEN"] = "123456:TEST"
os.environ["ADMIN_IDS"] = "1"

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery, Chat, ChatMemberAdministrator, ChatMemberLeft, ChatMemberMember, Message, Update, User,
)

from bot import admins, backup, certs, config, daily, db, keyboards as kb, services  # noqa: E402
from bot import subscription  # noqa: E402
from bot.__main__ import build_dispatcher  # noqa: E402
from bot.handlers import admin as admin_h, create as create_h, mytests as mytests_h  # noqa: E402
from bot.handlers import solve as solve_h, start as start_h  # noqa: E402

config.ADMIN_IDS.clear()
config.ADMIN_IDS.add(1)

ADMIN, TEACHER, S1, S2, S3 = 1, 10, 21, 22, 23
CHANNEL_ID = -1001
ids = itertools.count(1)


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.subscribed: set[int] = set()
        self.file_bytes = b""  # bot.download() qaytaradigan fayl

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        yield self.file_bytes

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        name = type(method).__name__
        if name == "GetMe":
            return User(id=999, is_bot=True, first_name="Bot", username="test_bot")
        if name == "GetChatMember":
            user = User(id=method.user_id, is_bot=False, first_name="U")
            if method.user_id == bot.id:
                # model_construct: Bot API versiyasiga bog'liq majburiy maydonlarni to'ldirmaslik uchun
                return ChatMemberAdministrator.model_construct(status="administrator", user=user)
            return ChatMemberMember(user=user) if method.user_id in self.subscribed else ChatMemberLeft(user=user)
        if name == "GetFile":
            from aiogram.types import File
            return File(file_id=method.file_id, file_unique_id="u", file_size=len(self.file_bytes),
                        file_path="logo.png")
        if name == "GetChat":
            from aiogram.types import ChatFullInfo
            return ChatFullInfo.model_construct(
                id=CHANNEL_ID, type="channel", title="Riyoziyot kanali", username="riyoziyot", invite_link=None
            )
        if name in ("SendMessage", "SendPhoto", "SendDocument", "EditMessageText"):
            return Message(message_id=next(ids), date=datetime.now(), chat=Chat(id=getattr(method, "chat_id", 0) or 0, type="private"))
        if name == "CopyMessage":
            from aiogram.types import MessageId
            return MessageId(message_id=next(ids))
        return True


session = FakeSession()
bot = Bot("123456:TEST", session=session, default=DefaultBotProperties(parse_mode="HTML"))
dp = build_dispatcher()


def texts(since: int) -> str:
    out = []
    for m in session.calls[since:]:
        for attr in ("text", "caption"):
            v = getattr(m, attr, None)
            if isinstance(v, str):
                out.append(v)
    return "\n----\n".join(out)


def names(since: int) -> list[str]:
    return [type(m).__name__ for m in session.calls[since:]]


async def msg(uid: int, text: str) -> str:
    start = len(session.calls)
    m = Message(message_id=next(ids), date=datetime.now(), chat=Chat(id=uid, type="private"),
                from_user=User(id=uid, is_bot=False, first_name=f"User{uid}"), text=text)
    await dp.feed_update(bot, Update(update_id=next(ids), message=m))
    return texts(start)


async def cb(uid: int, data: str) -> str:
    start = len(session.calls)
    m = Message(message_id=next(ids), date=datetime.now(), chat=Chat(id=uid, type="private"),
                from_user=User(id=999, is_bot=True, first_name="Bot"), text="x")
    c = CallbackQuery(id=str(next(ids)), from_user=User(id=uid, is_bot=False, first_name=f"User{uid}"),
                      chat_instance="ci", data=data, message=m)
    await dp.feed_update(bot, Update(update_id=next(ids), callback_query=c))
    return texts(start)


async def photo(uid: int) -> str:
    """Matn o'rniga rasm yuborish (kutilmagan kontent)."""
    from aiogram.types import PhotoSize

    start = len(session.calls)
    m = Message(message_id=next(ids), date=datetime.now(), chat=Chat(id=uid, type="private"),
                from_user=User(id=uid, is_bot=False, first_name=f"User{uid}"),
                photo=[PhotoSize(file_id="f", file_unique_id="u", width=1, height=1)])
    await dp.feed_update(bot, Update(update_id=next(ids), message=m))
    return texts(start)


def restart():
    """Server qayta ishga tushishini taqlid qiladi: xotiradagi holat yo'qoladi, bazadagisi qoladi."""
    global dp
    for router in (start_h.router, admin_h.router, create_h.router, solve_h.router, mytests_h.router):
        router._parent_router = None
    dp = build_dispatcher()


def last_markup_data() -> list[str]:
    """Oxirgi yuborilgan inline klaviaturadagi callback_data lar."""
    for m in reversed(session.calls):
        rm = getattr(m, "reply_markup", None)
        if rm is not None and hasattr(rm, "inline_keyboard"):
            return [b.callback_data for row in rm.inline_keyboard for b in row if b.callback_data]
    return []


async def register(uid: int, name: str):
    session.subscribed.add(uid)
    out = await msg(uid, "/start")
    assert "ism va familiyangizni" in out, out
    out = await msg(uid, name)
    assert "Asosiy menyu" in out, out


async def main():
    # TEST_DATABASE_URL berilsa - PostgreSQL'da (bo'sh baza bo'lishi kerak), aks holda vaqtinchalik SQLite
    target = os.getenv("TEST_DATABASE_URL") or Path(tempfile.mkdtemp()) / "test.db"
    await db.init(target)
    try:
        await scenario()
        await webhook_check()
        await daily_and_backup_check()
    finally:
        await db.close()  # aks holda xato chiqqanda aiosqlite oqimi jarayonni ushlab qoladi
    print("flow: OK")


async def daily_and_backup_check():
    """Kunlik hisobot bir kunda faqat bir marta yuboriladi; zaxira nusxa to'liq tiklanadi."""
    # qo'lda: admin paneldan
    start = len(session.calls)
    await cb(ADMIN, "adm:backup")
    assert "SendDocument" in names(start) and "zaxira nusxasi" in texts(start), names(start)
    out = await cb(ADMIN, "adm:daily")
    assert "Kunlik hisobot" in out and "Yangi foydalanuvchilar: <b>+6</b>" in out, out
    start = len(session.calls)
    await cb(S1, "adm:backup")  # oddiy foydalanuvchi ololmaydi
    assert "SendDocument" not in names(start)

    # avtomatik: soat yetganda bir marta
    config.DAILY_HOUR = 0
    for expected in (1, 1):  # ikkinchi ishga tushirish (qayta yoqilgan server) takror yubormaydi
        task = asyncio.create_task(daily.daily_loop(bot, interval=0.05))
        await asyncio.sleep(0.4)
        task.cancel()
        sent = [m for m in session.calls[start:] if type(m).__name__ == "SendDocument"]
        assert len(sent) == expected, len(sent)
    assert "Kunlik hisobot" in texts(start)
    config.DAILY_HOUR = 24  # hali soati kelmagan
    await db.set_setting(daily.SETTING_KEY, "2000-01-01")
    task = asyncio.create_task(daily.daily_loop(bot, interval=0.05))
    await asyncio.sleep(0.3)
    task.cancel()
    assert len([m for m in session.calls[start:] if type(m).__name__ == "SendDocument"]) == 1

    # zaxira -> bo'sh bazaga tiklash (faqat SQLite rejimida; PostgreSQL alohida tekshiriladi)
    if os.getenv("TEST_DATABASE_URL"):
        return
    data = await backup.dump()
    before = backup.summary(data)
    assert before["users"] == 6 and before["tests"] == 1 and before["submissions"] == 1, before
    try:
        await backup.restore(data)
        raise AssertionError("bo'sh bo'lmagan bazaga tiklashga ruxsat berildi")
    except RuntimeError:
        pass
    old_test = (await db.tests_by_owner(TEACHER, 1, 0))[0]
    await db.close()
    await db.init(Path(tempfile.mkdtemp()) / "restored.db")
    assert await backup.restore(data) == before
    restored = await db.get_test(old_test["id"])
    assert restored["code"] == old_test["code"] and restored["questions"] == old_test["questions"]
    assert (await db.get_user(S1))["full_name"] == "Aliyev Vali"
    assert await db.get_submission(old_test["id"], S1) is not None
    new_test = await db.create_test(TEACHER, "Tiklangandan keyin", [{"t": "c", "a": "a", "p": 1.0}], None)
    assert new_test["id"] > old_test["id"]


async def webhook_check():
    """Server rejimi: /health javob beradi, webhook faqat to'g'ri maxfiy kalit bilan qabul qiladi."""
    import aiohttp
    from aiohttp import web

    from bot.__main__ import build_web_app

    runner = web.AppRunner(build_web_app(bot, dp, "sekret"))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    update = {"update_id": 10**6, "message": {
        "message_id": 10**6, "date": 0, "chat": {"id": S1, "type": "private"},
        "from": {"id": S1, "is_bot": False, "first_name": "U"}, "text": kb.BTN_HELP}}
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{port}/health") as r:
                assert r.status == 200 and await r.text() == "ok"
            async with http.head(f"http://127.0.0.1:{port}/") as r:
                assert r.status == 200
            start = len(session.calls)
            async with http.post(f"http://127.0.0.1:{port}/webhook/sekret", json=update,
                                 headers={"X-Telegram-Bot-Api-Secret-Token": "noto'g'ri".encode().hex()}) as r:
                assert r.status == 401, r.status
            assert len(session.calls) == start, "maxfiy kalitsiz so'rov qabul qilindi"
            async with http.post(f"http://127.0.0.1:{port}/webhook/sekret", json=update,
                                 headers={"X-Telegram-Bot-Api-Secret-Token": "sekret"}) as r:
                assert r.status == 200, r.status
            await asyncio.sleep(0.5)
            assert "Yordam</b>" in texts(start), texts(start)
    finally:
        await runner.cleanup()


async def scenario():
    # --- admin: kanal qo'shish
    out = await msg(ADMIN, "/start")
    assert "ism va familiyangizni" in out
    await msg(ADMIN, "Admin Adminov")
    out = await msg(ADMIN, kb.BTN_ADMIN)
    assert "Admin panel" in out
    await cb(ADMIN, "adm:ch")
    await cb(ADMIN, "adm:chadd")
    out = await photo(ADMIN)  # forward bo'lmagan rasm
    assert "Tushunmadim" in out or "tushunmadim" in out.lower(), out
    out = await msg(ADMIN, "@riyoziyot")
    assert "qo'shildi" in out, out
    assert len(await db.get_channels()) == 1

    # --- obuna talabi
    out = await msg(S1, "/start test_00000")
    assert "obuna bo'ling" in out, out
    out = await msg(S1, kb.BTN_CREATE)
    assert "obuna bo'ling" in out
    start = len(session.calls)
    await cb(S1, "check_sub")
    assert any(getattr(m, "show_alert", False) for m in session.calls[start:]), "obunasiz o'tib ketdi"
    session.subscribed.add(S1)
    out = await cb(S1, "check_sub")
    assert "ism va familiyangizni" in out, out
    out = await msg(S1, kb.BTN_CREATE)  # ro'yxatdan o'tmasdan menyu ishlamasligi kerak
    assert "ism va familiyangizni" in out, out
    out = await photo(S1)
    assert "ism va familiyangizni" in out, out
    out = await msg(S1, "Ali 777")
    assert "faqat harflardan" in out, out
    out = await msg(S1, "Jalab Jalabov")
    assert "qabul qila olmaymiz" in out, out
    out = await msg(S1, "с у к а")
    assert "qabul qila olmaymiz" in out, out
    assert (await db.get_user(S1))["full_name"] is None
    out = await msg(S1, "Aliyev Vali")
    assert "Ro'yxatdan o'tdingiz" in out and "topilmadi" in out, out  # deep-link saqlanib qolgan, test yo'q
    out = await msg(S1, kb.BTN_BACK)  # kod kutish holatidan orqaga -> menyu
    assert "Asosiy menyu" in out, out

    await register(TEACHER, "Ustoz Karimov")
    await register(S2, "Bobur Mirzo")
    await register(S3, "Salimova Dilnoza")

    # --- test yaratish (aralash, alohida ballar, muddatsiz) + orqaga qaytishlar
    out = await msg(TEACHER, kb.BTN_CREATE)
    assert "1-qadam" in out, out
    out = await msg(TEACHER, "ab")
    assert "3–100 belgidan" in out, out
    out = await msg(TEACHER, "Blyat test")
    assert "nomaqbul so'z" in out, out
    out = await photo(TEACHER)
    assert "test nomini" in out, out  # holatga mos yo'l-yo'riq
    out = await msg(TEACHER, "Algebra <9-sinf> & nazorat")
    assert "2-qadam" in out, out
    out = await msg(TEACHER, kb.BTN_BACK)
    assert "1-qadam" in out, out
    out = await msg(TEACHER, "Algebra <9-sinf> & nazorat")
    assert "2-qadam" in out, out
    out = await msg(TEACHER, "1a2b4c")
    assert "ketma-ket emas" in out
    out = await msg(TEACHER, "1. a\n2. b\n3. 0.5|1/2\n4. d\n5. Toshkent")
    assert "5 ta savol" in out and "variantli: 3, ochiq: 2" in out and "3-qadam" in out, out
    out = await cb(TEACHER, "cr:p:custom")
    assert "savollar: ball" in out
    out = await msg(TEACHER, kb.BTN_BACK)  # ballardan kalitga qaytish - kalit saqlangan
    assert "Kalit qabul qilindi" in out and "Toshkent" in out, out
    await cb(TEACHER, "cr:p:custom")
    out = await msg(TEACHER, "1-9: 2")
    assert "noto'g'ri" in out
    out = await msg(TEACHER, "1-2: 1.1; 3: 3.1")
    assert "Maksimal ball: <b>7.3</b>" in out and "4-qadam" in out, out
    out = await msg(TEACHER, "01.01.2020 10:00")
    assert "o'tib ketgan" in out
    out = await msg(TEACHER, "ertaga")
    assert "tushunmadim" in out
    out = await cb(TEACHER, "cr:d:0")
    assert "Hammasi to'g'rimi" in out and "belgilanmagan" in out and "&lt;9-sinf&gt; &amp;" in out, out
    out = await cb(TEACHER, "cr:back")
    assert "4-qadam" in out, out
    restart()  # server qayta ishga tushdi: yaratish jarayoni davom etishi kerak
    out = await cb(TEACHER, "cr:d:0")
    assert "Hammasi to'g'rimi" in out and "jami 7.3" in out, out
    out = await cb(TEACHER, "cr:ok")
    assert "Test yaratildi" in out and "start=test_" in out, out
    tests = await db.tests_by_owner(TEACHER, 10, 0)
    assert len(tests) == 1
    test = tests[0]
    code, tid = test["code"], test["id"]

    # --- muallif o'z testiga javob yubora olmaydi
    out = await msg(TEACHER, f"{code}*abcda")
    assert "o'zingiz yaratgan test" in out, out

    # --- S1: menyu orqali, xatolar bilan
    out = await msg(S1, kb.BTN_CHECK)
    assert "test kodini" in out
    out = await msg(S1, "abc")
    assert "faqat raqamlardan" in out
    out = await msg(S1, "99")
    assert "topilmadi" in out
    out = await msg(S1, code)
    assert "Ochiq (yozma) javobli savollar: <b>3, 5</b>" in out, out
    out = await msg(S1, kb.BTN_BACK)  # javoblardan kod so'rashga qaytish
    assert "test kodini" in out, out
    await msg(S1, code)
    out = await msg(S1, "abcd")
    assert "5</b> ta savol bor" in out, out
    out = await msg(S1, "1. a\n2. zzz\n3. 1\n4. d\n5. x")
    assert "variantli" in out, out
    out = await msg(S1, "1. a\n2. a\n3. 2/4\n4. -\n5. toshkent")
    assert "Javoblaringizni tekshiring" in out and "Javobsiz qoldirilgan savollar: <b>1</b>" in out, out
    assert await db.get_submission(tid, S1) is None, "tasdiqlanmasdan saqlandi"
    out = await photo(S1)
    assert "«✅ Yuborish»" in out, out
    out = await cb(S1, "sv:edit")
    assert "Javoblaringizni bitta xabarda" in out, out
    out = await msg(S1, "1. a\n2. c\n3. 2/4\n4. -\n5. toshkent")
    assert "Javoblaringizni tekshiring" in out, out
    restart()  # tasdiqlash oldidan server qayta ishga tushdi
    out = await cb(S1, "sv:ok")
    assert "qabul qilindi" in out and "3 / 5" in out and "5.2 / 7.3" in out, out
    assert "1 / 1" in out and "Xato javoblar (1 ta)" in out and "Javobsiz (1 ta):</b> 4" in out, out
    assert "siz: <code>C</code>" in out, out
    assert "to'g'ri: <code>" not in out, "kalit test tugamasdan oshkor bo'ldi"
    # qayta yuborish
    out = await msg(S1, f"{code}*1. a\n2. b\n3. 0.5\n4. d\n5. toshkent")
    assert "avval javob yuborgansiz" in out, out
    out = await msg(S1, code)  # holatsiz yuborilgan raqam - test kodi
    assert "avval javob yuborgansiz" in out, out
    out = await cb(S1, "sv:ok")  # eskirgan tugma
    assert "eski xabarga tegishli" in out and "menyudan davom eting" in out, out

    # --- S2: tezkor format, hammasi to'g'ri; deep link orqali S3
    out = await msg(S2, f"{code}*a;b;0,5;d;TOSHKENT")
    assert "Javoblaringizni tekshiring" in out, out
    out = await cb(S2, "sv:ok")
    assert "Barcha javoblaringiz to'g'ri" in out and "7.3 / 7.3" in out and "1 / 2" in out, out
    out = await msg(S3, f"/start test_{code}")
    assert "Savollar soni" in out, out
    await msg(S3, "1. b\n2. b\n3. 7\n4. d\n5. -")
    out = await cb(S3, "sv:ok")
    assert "2 / 5" in out and "3 / 3" in out, out  # 1.1 + 1 = 2.1 ball, 3-o'rin
    start = len(session.calls)
    await cb(S3, "sv:ok")  # ikki marta bosish
    assert (await db.count_submissions(tid)) == 3

    # --- reyting
    out = await cb(S1, f"rating:{tid}")
    assert out.index("Bobur") < out.index("Aliyev") < out.index("Salimova"), out
    out = await msg(S1, kb.BTN_RATING)
    assert f"rating:{tid}" in last_markup_data(), last_markup_data()
    out = await cb(S1, f"rating:{tid}")
    assert "Bobur" in out
    out = await msg(S1, "tushunarsiz")  # reytingdan keyin holat yopilgan bo'lishi kerak
    assert "tushunmadim" in out, out
    await msg(ADMIN, kb.BTN_RATING)
    out = await msg(ADMIN, code)
    assert "Bobur" in out
    await register(77, "Begona Odam")
    start = len(session.calls)
    await cb(77, f"rating:{tid}")
    assert "SendMessage" not in names(start), "begona reytingni ko'rdi"
    await msg(77, kb.BTN_RATING)
    out = await msg(77, code)
    assert "faqat unda qatnashganlar" in out, out
    start = len(session.calls)
    await cb(77, f"t:res:{tid}")
    assert "SendMessage" not in names(start), "begona muallif paneliga kirdi"
    await cb(77, f"t:delok:{tid}")
    assert await db.get_test(tid) is not None, "begona testni o'chirdi"
    out = await msg(77, kb.BTN_MY_RESULTS)
    assert "hali birorta testga" in out and "go:check" in last_markup_data(), out
    out = await msg(77, kb.BTN_MY_TESTS)
    assert "hali test yaratmagansiz" in out and "go:create" in last_markup_data(), out
    out = await cb(77, "go:create")
    assert "1-qadam" in out, out
    out = await cb(77, "home")
    assert "Asosiy menyu" in out, out
    out = await cb(77, "go:check")
    assert "test kodini" in out, out
    out = await msg(77, kb.BTN_CANCEL)
    assert "Bekor qilindi" in out and "Asosiy menyu" in out, out

    # --- natijalarim, sertifikat
    out = await msg(S1, kb.BTN_MY_RESULTS)
    assert f"res:{tid}" in last_markup_data()
    out = await cb(S1, f"res:{tid}")
    assert "3 / 5" in out
    start = len(session.calls)
    await cb(S1, f"cert:{tid}")
    assert "SendPhoto" in names(start) and "SendDocument" in names(start), names(start)
    sub1 = await db.get_submission(tid, S1)
    out = texts(start)
    assert "Sertifikat — Yaxshi daraja" in out and f"{code}-{sub1['id']:05d}" in out, out  # 5.2/7.3 = 71%
    assert "Test hali yakunlanmagan" in out, out
    pdf = [m for m in session.calls[start:] if type(m).__name__ == "SendDocument"][0].document.data
    assert pdf[:5] == b"%PDF-" and len(pdf) > 20_000
    # QR orqali tekshirish (istalgan foydalanuvchi)
    cert_token = await certs.token(sub1["id"])
    out = await msg(77, f"/start cert_{cert_token}")
    assert "Sertifikat haqiqiy" in out and "Aliyev Vali" in out and "5.2 / 7.3" in out, out
    assert "hali yakunlanmagan" in out, out
    out = await msg(77, f"/start cert_{sub1['id']}_0000000000")  # imzo noto'g'ri
    assert "Sertifikat topilmadi" in out, out
    out = await msg(77, f"/start cert_{sub1['id'] + 1}_{cert_token.split('_')[1]}")  # boshqa natijaga urinish
    assert "Sertifikat topilmadi" in out, out
    out = await msg(77, "/start cert_abc")
    assert "Sertifikat topilmadi" in out, out

    # --- muallif: ro'yxat, ko'rish, natijalar, excel, kalit
    out = await msg(TEACHER, kb.BTN_MY_TESTS)
    assert f"t:v:{tid}" in last_markup_data()
    out = await cb(TEACHER, f"t:v:{tid}")
    assert "Ishtirokchilar: <b>3</b>" in out and "Faol" in out, out
    assert "home" in last_markup_data() and "mt:0" in last_markup_data()
    out = await cb(TEACHER, f"t:res:{tid}")
    assert "O'rtacha ball" in out, out
    start = len(session.calls)
    await cb(TEACHER, f"t:xl:{tid}")
    assert "SendDocument" in names(start)
    out = await cb(TEACHER, f"t:key:{tid}")
    assert "Toshkent" in out and "Ballar" in out, out
    out = await cb(TEACHER, f"t:share:{tid}")
    assert code in out

    # --- moderatsiya: muallif ishtirokchini reytingdan chiqaradi / qaytaradi
    out = await cb(TEACHER, f"t:pl:{tid}:0")
    assert "ishtirokchilar (3 nafar)" in out and f"t:pu:{tid}:{S3}" in last_markup_data(), out
    out = await cb(TEACHER, f"t:pu:{tid}:{S3}")
    assert "Salimova Dilnoza" in out and "Reytingda" in out and f"t:ph:{tid}:{S3}" in last_markup_data(), out
    start = len(session.calls)
    await cb(77, f"t:ph:{tid}:{S3}")  # begona odam chiqara olmaydi
    assert (await db.get_submission(tid, S3))["is_hidden"] == 0
    out = await cb(TEACHER, f"t:ph:{tid}:{S3}")
    assert "Siz reytingdan chiqargansiz" in out and f"t:pr:{tid}:{S3}" in last_markup_data(), out
    assert await db.count_submissions(tid) == 2
    out = await cb(S1, f"rating:{tid}")
    assert "Salimova" not in out and "2 nafar" in out, out
    out = await cb(S3, f"res:{tid}")
    assert "reytingidan chiqarilgan" in out and "test muallifi" in out, out
    sub3 = await db.get_submission(tid, S3)
    out = await msg(S1, f"/start cert_{await certs.token(sub3['id'])}")
    assert "Sertifikat bekor qilingan" in out, out
    start = len(session.calls)
    await cb(S3, f"rating:{tid}")
    await cb(S3, f"cert:{tid}")
    assert "SendMessage" not in names(start) and "SendPhoto" not in names(start), names(start)
    out = await msg(S3, f"{code}*abcda")  # qayta javob yubora olmaydi
    assert "reytingidan chiqarilgan" in out, out
    out = await cb(TEACHER, f"t:pr:{tid}:{S3}")
    assert "Reytingda" in out and await db.count_submissions(tid) == 3, out

    # --- moderatsiya: shikoyat -> admin ismni bekor qiladi
    start = len(session.calls)
    await cb(TEACHER, f"t:pp:{tid}:{S3}")
    out = texts(start)
    assert "Shikoyat" in out and "Salimova Dilnoza" in out and f"adm:rename:{S3}" in last_markup_data(), out
    start = len(session.calls)
    await cb(TEACHER, f"t:pp:{tid}:{S3}")  # takroriy shikoyat yuborilmaydi
    assert "SendMessage" not in names(start)
    start = len(session.calls)
    await cb(S1, f"adm:rename:{S1}")  # oddiy foydalanuvchi admin tugmasidan foydalana olmaydi
    assert (await db.get_user(S1))["full_name"] == "Aliyev Vali"
    out = await cb(ADMIN, f"adm:rename:{S3}")
    assert "Ismi bekor qilindi" in out and "Ismingiz bekor qilindi" in out, out
    assert (await db.get_user(S3))["full_name"] is None
    assert (await db.get_submission(tid, S3))["full_name"] == "Ishtirokchi 23"
    out = await msg(S3, kb.BTN_MY_RESULTS)
    assert "ism va familiyangizni" in out, out
    out = await msg(S3, "Salimova Dilnoza")
    assert "Ro'yxatdan o'tdingiz" in out, out

    # --- moderatsiya: admin bloklaydi -> barcha reytinglardan yo'qoladi; blokdan chiqarsa qaytadi
    out = await cb(ADMIN, f"adm:ban:{S2}")
    assert "Bloklandi" in out, out
    assert await db.count_submissions(tid) == 2 and (await db.get_user(S2))["is_blocked"]
    out = await cb(S1, f"rating:{tid}")
    assert "Bobur" not in out, out
    start = len(session.calls)
    await msg(S2, kb.BTN_HELP)
    assert len(session.calls) == start, "bloklangan foydalanuvchiga javob berildi"
    await cb(ADMIN, "adm:block")
    out = await msg(ADMIN, str(S2))
    assert "Blokdan chiqarildi" in out and await db.count_submissions(tid) == 3, out

    # --- moderatsiya: admin qo'shimcha so'z qo'shadi
    out = await cb(ADMIN, "adm:words")
    assert "Taqiqlangan so'zlar" in out
    await cb(ADMIN, "adm:wadd")
    out = await msg(ADMIN, "Маймун")
    assert "<code>maymun</code>" in out and "adm:wdel:maymun" in last_markup_data(), out
    await cb(S1, "profile:name")
    out = await msg(S1, "Maymunov Vali")
    assert "qabul qila olmaymiz" in out, out
    await msg(S1, kb.BTN_CANCEL)
    await cb(ADMIN, "adm:wdel:maymun")
    await cb(S1, "profile:name")
    out = await msg(S1, "Maymunov Vali")
    assert "saqlandi" in out, out
    await cb(S1, "profile:name")
    await msg(S1, "Aliyev Vali")

    # --- yakunlash
    await cb(TEACHER, f"t:fin:{tid}")
    start = len(session.calls)
    out = await cb(TEACHER, f"t:finok:{tid}")
    await asyncio.sleep(0.5)  # ishtirokchilarga fon xabarlari
    out = texts(start)
    assert "Test yakunlandi" in out and "Yakuniy o'rningiz: <b>1 / 3</b>" in out, out
    assert "SendDocument" in names(start)
    out = await cb(S1, f"res:{tid}")
    assert "to'g'ri: <code>B</code>" in out and "to'g'ri: <code>D</code>" in out and "yakuniy" in out, out
    out = await msg(77, f"{code}*abcda")
    assert "yakunlangan" in out, out

    # --- sertifikat sozlamalari (admin) va diplomlar
    out = await cb(ADMIN, "adm:cert")
    assert "Sertifikat sozlamalari" in out and "kiritilmagan" in out, out
    await cb(ADMIN, "adm:cset:org")
    out = await msg(ADMIN, "x")
    assert "2–60 belgi" in out, out
    out = await msg(ADMIN, "«Riyoziyot» o'quv markazi")
    assert "Tashkilot nomi: <b>«Riyoziyot» o&#x27;quv markazi</b>" in out, out
    await cb(ADMIN, "adm:cset:signer")
    await msg(ADMIN, "A. Karimov")
    await cb(ADMIN, "adm:cset:role")
    await msg(ADMIN, "Markaz direktori")
    assert (await certs.settings())[certs.KEY_SIGNER] == "A. Karimov"
    await cb(ADMIN, "adm:clogo")
    out = await msg(ADMIN, "bu matn")  # rasm kutilmoqda
    assert "logotipni" in out, out
    session.file_bytes = b"bu rasm emas"
    out = await photo(ADMIN)
    assert "o'qib bo'lmadi" in out, out
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGBA", (300, 200), (31, 58, 95, 255)).save(buf, "PNG")
    session.file_bytes = buf.getvalue()
    out = await photo(ADMIN)
    assert "Logotip saqlandi" in out and "adm:clogodel" in last_markup_data(), out
    start = len(session.calls)
    await cb(S1, "adm:cert")  # oddiy foydalanuvchi kira olmaydi
    await cb(S1, "adm:csample")
    assert "SendPhoto" not in names(start) and "Sertifikat sozlamalari" not in texts(start)
    start = len(session.calls)
    await cb(ADMIN, "adm:csample")
    assert "SendPhoto" in names(start) and "Namuna" in texts(start), names(start)
    start = len(session.calls)
    await cb(S2, f"cert:{tid}")  # yakunlangan test, 1-o'rin -> diplom (logotip va imzo bilan)
    out = texts(start)
    assert "Diplom — I o'rin" in out and "Test hali yakunlanmagan" not in out, out
    start = len(session.calls)
    await cb(S1, f"cert:{tid}")
    assert "Diplom — II o'rin" in texts(start), texts(start)
    out = await msg(77, f"/start cert_{cert_token}")
    assert "Sertifikat haqiqiy" in out and "O'rin: <b>2 / 3</b>" in out and "Diplom" in out, out
    await cb(ADMIN, "adm:cset:role")
    out = await msg(ADMIN, "-")
    assert "o'chirildi" in out and (await certs.settings())[certs.KEY_ROLE] is None, out
    await cb(ADMIN, "adm:clogodel")
    assert (await certs.settings())[certs.KEY_LOGO] is None

    # --- muddatli test + avtomatik yakunlash
    await msg(TEACHER, kb.BTN_CREATE)
    await msg(TEACHER, "Tezkor test")
    out = await msg(TEACHER, "abcd")
    assert "variantli: 4, ochiq: 0" in out
    await cb(TEACHER, "cr:p:std")
    out = await cb(TEACHER, "cr:d:60")
    assert "gacha" in out
    await cb(TEACHER, "cr:ok")
    t2 = (await db.tests_by_owner(TEACHER, 10, 0))[0]
    out = await msg(S1, f"{t2['code']}*abca")
    assert "1.A  2.B  3.C  4.A" in out, out
    out = await cb(S1, "sv:ok")
    assert "3 / 4" in out, out
    await db._exec("UPDATE tests SET deadline='2000-01-01 00:00:00' WHERE id=?", (t2["id"],))
    out = await msg(S2, f"{t2['code']}*abcd")
    assert "yakunlangan" in out, out
    start = len(session.calls)
    watcher = asyncio.create_task(services.deadline_watcher(bot))
    await asyncio.sleep(0.6)
    watcher.cancel()
    out = texts(start)
    assert "avtomatik yakunlandi" in out and "Yakuniy o'rningiz" in out, out
    assert not (await db.get_test(t2["id"]))["is_active"]

    # --- menyu tugmasi holatni bekor qiladi
    await msg(S1, kb.BTN_CHECK)
    out = await msg(S1, kb.BTN_PROFILE)
    assert "Profil" in out and "Ishlagan testlaringiz: <b>2</b>" in out, out
    await cb(S1, "profile:name")
    out = await msg(S1, kb.BTN_BACK)  # «Orqaga» ism sifatida saqlanib qolmasligi kerak
    assert "Asosiy menyu" in out and (await db.get_user(S1))["full_name"] == "Aliyev Vali", out
    out = await msg(S1, "tushunarsiz narsa")
    assert "tushunmadim" in out

    # --- o'chirish
    await cb(TEACHER, f"t:del:{tid}")
    await cb(TEACHER, f"t:delok:{tid}")
    assert await db.get_test(tid) is None and await db.get_submission(tid, S1) is None

    # --- admin: statistika, bloklash, tarqatish, begona admin panelga kira olmaydi
    out = await cb(ADMIN, "adm:stats")
    assert "Foydalanuvchilar: 6</b>" in out and "ro'yxatdan o'tgan: 6" in out, out
    assert "bugun <b>+6</b>" in out and "Faol: bugun <b>6</b>" in out, out
    assert "Testlar: 1</b>" in out and "Yuborilgan javoblar: 1</b>" in out and "o'rtacha natija: 75%" in out, out
    out = await cb(ADMIN, "adm:stats:week")
    assert "Oxirgi 7 kun" in out and "Jami       6     1      1" in out, out
    out = await cb(ADMIN, "adm:stats:top")
    assert "Tezkor test" in out and "Ustoz Karimov — 1 ta test, <b>1</b> ishtirokchi" in out, out
    assert "Aliyev Vali — <b>1</b> ta test, o'rtacha 75%" in out, out
    start = len(session.calls)
    await cb(ADMIN, "adm:users_xl")
    assert "SendDocument" in names(start) and "6 nafar" in texts(start), names(start)
    start = len(session.calls)
    await cb(S1, "adm:stats")
    out = await msg(S1, "/admin")
    assert "Statistika" not in texts(start) and "Admin panel" not in out
    await cb(ADMIN, "adm:block")
    out = await msg(ADMIN, "77")
    assert "Bloklandi" in out and "Admin panel" in out
    start = len(session.calls)
    await msg(77, kb.BTN_HELP)
    assert len(session.calls) == start, "bloklangan foydalanuvchiga javob berildi"
    await cb(ADMIN, "adm:bc")
    await msg(ADMIN, "Hammaga salom")
    data = [d for d in last_markup_data() if d.startswith("adm:bcgo:")]
    start = len(session.calls)
    await cb(ADMIN, data[0])
    await asyncio.sleep(1.0)
    assert names(start).count("CopyMessage") == 5, names(start)  # 6 kishi - 1 bloklangan
    assert "Yetkazildi: 5" in texts(start) and "PinChatMessage" not in names(start)
    # pin bilan tarqatish va pinni olib tashlash
    await cb(ADMIN, "adm:bc")
    await msg(ADMIN, "Muhim e'lon")
    data = [d for d in last_markup_data() if d.startswith("adm:bcpin:")]
    start = len(session.calls)
    await cb(S1, data[0])  # oddiy foydalanuvchi tarqata olmaydi
    assert "CopyMessage" not in names(start)
    await cb(ADMIN, data[0])
    await asyncio.sleep(1.0)
    assert names(start).count("CopyMessage") == 5 and names(start).count("PinChatMessage") == 5, names(start)
    assert "Pin qilindi: 5" in texts(start) and "adm:unpin" in last_markup_data()
    out = await cb(ADMIN, "adm:unpin")
    assert "Davom etilsinmi" in out
    start = len(session.calls)
    await cb(ADMIN, "adm:unpinok")
    await asyncio.sleep(1.0)
    assert names(start).count("UnpinChatMessage") == 5 and "Tekshirildi: 5" in texts(start), names(start)

    # --- adminlarni bot ichidan boshqarish
    out = await cb(ADMIN, "adm:admins")
    assert "👑 Admin Adminov" in out and "adm:admadd" in last_markup_data(), out
    await cb(ADMIN, "adm:admadd")
    out = await msg(ADMIN, "abc")
    assert "faqat raqamlardan" in out, out
    out = await msg(ADMIN, "555")
    assert "hali kirmagan" in out, out
    out = await msg(ADMIN, "1")
    assert "allaqachon admin" in out, out
    out = await msg(ADMIN, str(S2))
    assert "admin etib tayinlandi" in out and "Siz admin etib tayinlandingiz" in out, out
    assert config.is_admin(S2) and f"adm:admdel:{S2}" in last_markup_data()
    out = await msg(S2, kb.BTN_ADMIN)  # yangi admin panelga kira oladi
    assert "Admin panel" in out, out
    out = await cb(S2, "adm:stats")
    assert "Statistika" in out
    out = await cb(S2, "adm:admins")  # ...lekin adminlarni boshqara olmaydi
    assert "faqat bosh adminga" in out and "adm:admadd" not in last_markup_data(), out
    start = len(session.calls)
    await cb(S2, "adm:admadd")
    await cb(S2, f"adm:admdelok:{ADMIN}")
    await cb(S2, f"adm:admdelok:{S2}")
    assert config.is_admin(ADMIN) and config.is_admin(S2) and "SendMessage" not in names(start)
    await cb(ADMIN, f"adm:admdelok:{ADMIN}")  # bosh admin o'zini ham o'chira olmaydi
    assert config.is_admin(ADMIN)
    await admins.load()  # qayta ishga tushganda bazadan tiklanadi
    assert config.ADMIN_IDS == {ADMIN, S2}, config.ADMIN_IDS
    out = await cb(ADMIN, f"adm:admdel:{S2}")
    assert "adminlikdan olinsinmi" in out
    out = await cb(ADMIN, f"adm:admdelok:{S2}")
    assert "endi admin emassiz" in out and not config.is_admin(S2), out
    out = await msg(S2, kb.BTN_ADMIN)
    assert "Admin panel" not in out, out
    await admins.load()
    assert config.ADMIN_IDS == {ADMIN}

    # --- kanal o'chirilgach obuna talab qilinmaydi
    session.subscribed.discard(S3)
    subscription.invalidate()
    out = await msg(S3, kb.BTN_HELP)
    assert "obuna bo'ling" in out
    ch = (await db.get_channels())[0]
    await cb(ADMIN, f"adm:chdel:{ch['id']}")
    out = await msg(S3, kb.BTN_HELP)
    assert "Yordam</b>" in out


if __name__ == "__main__":
    asyncio.run(main())
