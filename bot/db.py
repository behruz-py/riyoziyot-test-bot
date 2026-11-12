"""Ma'lumotlar bazasi qatlami.

DATABASE_URL (postgres://...) berilgan bo'lsa - PostgreSQL (Neon), aks holda mahalliy SQLite fayli.
So'rovlar ikkala bazada bir xil ishlaydigan qilib yozilgan ("?" belgilari PostgreSQL uchun $1, $2... ga aylanadi).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiosqlite

log = logging.getLogger(__name__)

_conn: aiosqlite.Connection | None = None  # SQLite
_pool = None  # PostgreSQL (asyncpg.Pool)

TIME_FMT = "%Y-%m-%d %H:%M:%S"

# {PK}, {BIG}, {REAL} - bazaga qarab almashtiriladi
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          {BIG} PRIMARY KEY,
    username    TEXT,
    tg_name     TEXT,
    full_name   TEXT,
    joined_at   TEXT NOT NULL,
    is_blocked  INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    last_seen   TEXT
);
CREATE TABLE IF NOT EXISTS channels (
    id       {PK},
    chat_id  {BIG} NOT NULL UNIQUE,
    title    TEXT NOT NULL,
    url      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tests (
    id           {PK},
    code         TEXT NOT NULL UNIQUE,
    owner_id     {BIG} NOT NULL,
    title        TEXT NOT NULL,
    questions    TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    deadline     TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1,
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_tests_owner ON tests(owner_id);
CREATE TABLE IF NOT EXISTS submissions (
    id             {PK},
    test_id        {BIG} NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    user_id        {BIG} NOT NULL,
    full_name      TEXT NOT NULL,
    answers        TEXT NOT NULL,
    correct_count  INTEGER NOT NULL,
    score          {REAL} NOT NULL,
    max_score      {REAL} NOT NULL,
    submitted_at   TEXT NOT NULL,
    is_hidden      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(test_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_sub_user ON submissions(user_id);
CREATE TABLE IF NOT EXISTS banned_words (
    word  TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS admins (
    user_id   {BIG} PRIMARY KEY,
    added_by  {BIG} NOT NULL,
    added_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fsm (
    user_id     {BIG} PRIMARY KEY,
    state       TEXT,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""
# Jadval yaratilgandan keyin qo'shilgan ustunlar: (jadval, ustun, turi) - eski bazalarga avtomatik qo'shiladi
_NEW_COLUMNS = [
    ("submissions", "is_hidden", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "last_seen", "TEXT"),
    ("tests", "edited_at", "TEXT"),
    ("tests", "note", "TEXT"),
]
_SQLITE_TYPES = {"PK": "INTEGER PRIMARY KEY AUTOINCREMENT", "BIG": "INTEGER", "REAL": "REAL"}
_PG_TYPES = {"PK": "BIGSERIAL PRIMARY KEY", "BIG": "BIGINT", "REAL": "DOUBLE PRECISION"}

# Reyting tartibi: ball kamayishi bo'yicha, teng bo'lsa - oldin topshirgan yuqorida
# (submissions_ranked va rank_of bir xil tartibdan foydalanadi)
#
# submissions.is_hidden: 0 - reytingda; 1 - test muallifi chiqargan; 2 - admin bloklagani uchun yashirilgan.
# Yashirilgan natija o'chirilmaydi (qayta javob yuborib bo'lmasligi uchun), faqat reyting/hisobotda ko'rinmaydi.
HIDDEN_BY_OWNER = 1
HIDDEN_BY_BAN = 2


class Duplicate(Exception):
    """UNIQUE cheklovi buzildi (masalan, takroriy javob yoki band test kodi)."""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime(TIME_FMT)


def is_postgres(target) -> bool:
    return str(target).startswith(("postgres://", "postgresql://"))


def _clean_dsn(dsn: str) -> str:
    """asyncpg tushunmaydigan parametrlarni (Neon qo'shadigan channel_binding) olib tashlaydi."""
    parts = urlsplit(dsn)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k in ("sslmode", "options")]
    return urlunsplit(parts._replace(query=urlencode(query)))


async def init(target: Path | str) -> None:
    """target: SQLite fayl yo'li yoki postgres:// manzili."""
    global _conn, _pool
    if is_postgres(target):
        import asyncpg

        _pool = await asyncpg.create_pool(
            _clean_dsn(str(target)),
            min_size=0,
            max_size=5,
            # Neon 5 daqiqa bo'sh tursa uxlaydi: eskirgan ulanishlarni undan oldin yopamiz
            max_inactive_connection_lifetime=60,
            command_timeout=30,
            statement_cache_size=0,  # Neon "pooler" (PgBouncer) manzili bilan ham ishlashi uchun
        )
        async with _pool.acquire() as conn:
            await conn.execute(SCHEMA.format(**_PG_TYPES))
            # Eski bazalar uchun yangi ustunlar
            for table, column, ddl in _NEW_COLUMNS:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")
        log.info("Baza: PostgreSQL")
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(path)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.executescript(SCHEMA.format(**_SQLITE_TYPES))
    for table, column, ddl in _NEW_COLUMNS:  # eski bazalar uchun yangi ustunlar
        async with _conn.execute(f"PRAGMA table_info({table})") as cur:
            columns = {row["name"] for row in await cur.fetchall()}
        if column not in columns:
            await _conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    await _conn.commit()
    log.info("Baza: SQLite (%s)", path)


async def close() -> None:
    global _conn, _pool
    if _conn is not None:
        await _conn.close()
        _conn = None
    if _pool is not None:
        await _pool.close()
        _pool = None


def _pg_sql(sql: str) -> str:
    counter = iter(range(1, 100))
    return re.sub(r"\?", lambda _: f"${next(counter)}", sql)


async def _pg(method: str, sql: str, params: tuple):
    """PostgreSQL so'rovi; ulanish uzilgan bo'lsa (Neon uyg'onayotganda) bir marta qayta urinadi."""
    import asyncpg

    sql = _pg_sql(sql)
    for attempt in range(3):
        try:
            async with _pool.acquire() as conn:
                return await getattr(conn, method)(sql, *params)
        except asyncpg.UniqueViolationError as e:
            raise Duplicate(str(e)) from e
        except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError, asyncio.TimeoutError) as e:
            if attempt == 2:
                raise
            log.warning("Baza ulanishi uzildi, qayta urinilmoqda: %s", e)
            await asyncio.sleep(0.5 * (attempt + 1))


async def _one(sql: str, params: tuple = ()):
    if _pool is not None:
        return await _pg("fetchrow", sql, params)
    async with _conn.execute(sql, params) as cur:
        return await cur.fetchone()


async def _all(sql: str, params: tuple = ()) -> list:
    if _pool is not None:
        return await _pg("fetch", sql, params)
    async with _conn.execute(sql, params) as cur:
        return await cur.fetchall()


async def _exec(sql: str, params: tuple = ()) -> int:
    """O'zgartirilgan qatorlar sonini qaytaradi."""
    if _pool is not None:
        status = await _pg("execute", sql, params)  # masalan: "UPDATE 1", "INSERT 0 1"
        tail = status.rsplit(" ", 1)[-1]
        return int(tail) if tail.isdigit() else 0
    try:
        cur = await _conn.execute(sql, params)
        await _conn.commit()
    except sqlite3.IntegrityError as e:
        await _conn.rollback()
        raise Duplicate(str(e)) from e
    return cur.rowcount


# ---------------------------------------------------------------- users
async def get_user(user_id: int):
    return await _one("SELECT * FROM users WHERE id=?", (user_id,))


async def touch_user(user_id: int, username: str | None, tg_name: str):
    """Foydalanuvchini bazaga qo'shadi yoki ma'lumotini yangilaydi; qatorni qaytaradi.

    last_seen (oxirgi faollik) soatiga ko'pi bilan bir marta yoziladi - bazani ortiqcha yuklamaslik uchun.
    """
    now = now_utc()
    row = await get_user(user_id)
    if row is None:
        await _exec(
            "INSERT INTO users(id, username, tg_name, joined_at, last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO NOTHING",
            (user_id, username, tg_name, now, now),
        )
        return await get_user(user_id)
    stale = (row["last_seen"] or "")[:13] != now[:13]
    if stale or row["username"] != username or row["tg_name"] != tg_name or not row["is_active"]:
        await _exec(
            "UPDATE users SET username=?, tg_name=?, is_active=1, last_seen=? WHERE id=?",
            (username, tg_name, now, user_id),
        )
        return await get_user(user_id)
    return row


async def set_full_name(user_id: int, full_name: str) -> None:
    await _exec("UPDATE users SET full_name=? WHERE id=?", (full_name, user_id))


async def set_blocked(user_id: int, blocked: bool) -> None:
    await _exec("UPDATE users SET is_blocked=? WHERE id=?", (int(blocked), user_id))


async def set_inactive(user_id: int) -> None:
    await _exec("UPDATE users SET is_active=0 WHERE id=?", (user_id,))


async def all_user_ids() -> list[int]:
    rows = await _all("SELECT id FROM users WHERE is_blocked=0 AND is_active=1")
    return [r["id"] for r in rows]


async def stats(day: str, week: str, month: str) -> dict:
    """Umumiy ko'rsatkichlar. day/week/month - davr boshlanishi (UTC satr)."""
    periods = (("d", day), ("w", week), ("m", month))
    parts, params = [], []
    for table, column, prefix in (
        ("users", "joined_at", "users_new"),
        ("users", "last_seen", "users_seen"),
        ("tests", "created_at", "tests_new"),
        ("submissions", "submitted_at", "subs_new"),
    ):
        for suffix, start in periods:
            parts.append(f"(SELECT COUNT(*) FROM {table} WHERE {column} >= ?) AS {prefix}_{suffix}")
            params.append(start)
    row = await _one(
        f"""SELECT
            (SELECT COUNT(*) FROM users) AS users,
            (SELECT COUNT(*) FROM users WHERE full_name IS NOT NULL) AS registered,
            (SELECT COUNT(*) FROM users WHERE is_active=0) AS stopped,
            (SELECT COUNT(*) FROM users WHERE is_blocked=1) AS blocked,
            (SELECT COUNT(*) FROM tests) AS tests,
            (SELECT COUNT(*) FROM tests WHERE is_active=1) AS active_tests,
            (SELECT COUNT(DISTINCT owner_id) FROM tests) AS authors,
            (SELECT COUNT(*) FROM submissions) AS subs,
            (SELECT COUNT(DISTINCT user_id) FROM submissions) AS solvers,
            (SELECT COUNT(*) FROM submissions WHERE is_hidden<>0) AS hidden,
            (SELECT AVG(score * 100.0 / max_score) FROM submissions WHERE max_score > 0) AS avg_percent,
            (SELECT COUNT(*) FROM channels) AS channels,
            {", ".join(parts)}
        """,
        tuple(params),
    )
    return dict(row)


async def daily_counts(table: str, column: str, bounds: list[str]) -> list[int]:
    """Har bir [bounds[i], bounds[i+1]) oralig'idagi yozuvlar soni (kunlik dinamika uchun)."""
    assert (table, column) in {("users", "joined_at"), ("submissions", "submitted_at"), ("tests", "created_at")}
    parts, params = [], []
    for i in range(len(bounds) - 1):
        parts.append(f"COALESCE(SUM(CASE WHEN {column} >= ? AND {column} < ? THEN 1 ELSE 0 END), 0) AS c{i}")
        params += [bounds[i], bounds[i + 1]]
    row = await _one(f"SELECT {', '.join(parts)} FROM {table} WHERE {column} >= ?", (*params, bounds[0]))
    return [int(row[f"c{i}"]) for i in range(len(bounds) - 1)]


async def top_tests(limit: int) -> list:
    return await _all(
        """SELECT t.id, t.title, t.code, t.is_active, COUNT(s.id) AS participants
           FROM tests t LEFT JOIN submissions s ON s.test_id=t.id
           GROUP BY t.id, t.title, t.code, t.is_active
           ORDER BY COUNT(s.id) DESC, t.id DESC LIMIT ?""",
        (limit,),
    )


async def top_authors(limit: int) -> list:
    return await _all(
        """SELECT u.id, u.full_name, COUNT(DISTINCT t.id) AS tests, COUNT(s.id) AS participants
           FROM tests t JOIN users u ON u.id=t.owner_id LEFT JOIN submissions s ON s.test_id=t.id
           GROUP BY u.id, u.full_name
           ORDER BY COUNT(s.id) DESC, COUNT(DISTINCT t.id) DESC LIMIT ?""",
        (limit,),
    )


async def top_solvers(limit: int) -> list:
    return await _all(
        """SELECT u.id, u.full_name, COUNT(s.id) AS solved, AVG(s.score * 100.0 / s.max_score) AS avg_percent
           FROM submissions s JOIN users u ON u.id=s.user_id
           WHERE s.max_score > 0 AND s.is_hidden=0
           GROUP BY u.id, u.full_name
           ORDER BY COUNT(s.id) DESC, AVG(s.score * 100.0 / s.max_score) DESC LIMIT ?""",
        (limit,),
    )


async def users_export(limit: int = 50_000) -> list:
    return await _all(
        """SELECT u.*,
                  (SELECT COUNT(*) FROM tests t WHERE t.owner_id=u.id) AS tests_count,
                  (SELECT COUNT(*) FROM submissions s WHERE s.user_id=u.id) AS subs_count
           FROM users u ORDER BY u.joined_at, u.id LIMIT ?""",
        (limit,),
    )


# ---------------------------------------------------------------- channels
async def get_channels() -> list:
    return await _all("SELECT * FROM channels ORDER BY id")


async def add_channel(chat_id: int, title: str, url: str) -> None:
    await _exec(
        "INSERT INTO channels(chat_id, title, url) VALUES(?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, url=excluded.url",
        (chat_id, title, url),
    )


async def delete_channel(channel_id: int) -> None:
    await _exec("DELETE FROM channels WHERE id=?", (channel_id,))


# ---------------------------------------------------------------- tests
async def create_test(owner_id: int, title: str, questions: list[dict], deadline: str | None):
    payload = json.dumps(questions, ensure_ascii=False)
    for attempt in range(50):
        digits = 5 if attempt < 30 else 7
        code = str(random.randint(10 ** (digits - 1), 10**digits - 1))
        try:
            await _exec(
                "INSERT INTO tests(code, owner_id, title, questions, created_at, deadline) VALUES(?,?,?,?,?,?)",
                (code, owner_id, title, payload, now_utc(), deadline),
            )
        except Duplicate:
            continue
        return await get_test_by_code(code)
    raise RuntimeError("Test kodi yaratib bo'lmadi")


async def get_test(test_id: int):
    return await _one("SELECT * FROM tests WHERE id=?", (test_id,))


async def get_test_by_code(code: str):
    return await _one("SELECT * FROM tests WHERE code=?", (code,))


async def tests_by_owner(owner_id: int, limit: int, offset: int) -> list:
    return await _all(
        """SELECT t.*, (SELECT COUNT(*) FROM submissions s WHERE s.test_id=t.id AND s.is_hidden=0) AS participants
           FROM tests t WHERE owner_id=? ORDER BY id DESC LIMIT ? OFFSET ?""",
        (owner_id, limit, offset),
    )


async def count_tests_by_owner(owner_id: int) -> int:
    row = await _one("SELECT COUNT(*) AS c FROM tests WHERE owner_id=?", (owner_id,))
    return row["c"]


async def finish_test(test_id: int) -> bool:
    """Testni yakunlaydi. Faqat birinchi chaqiruvda True qaytaradi."""
    n = await _exec(
        "UPDATE tests SET is_active=0, finished_at=? WHERE id=? AND is_active=1", (now_utc(), test_id)
    )
    return n > 0


async def delete_test(test_id: int) -> None:
    await _exec("DELETE FROM tests WHERE id=?", (test_id,))


async def next_deadline() -> str | None:
    row = await _one("SELECT MIN(deadline) AS d FROM tests WHERE is_active=1 AND deadline IS NOT NULL")
    return row["d"] if row else None


async def expired_tests() -> list:
    return await _all(
        "SELECT * FROM tests WHERE is_active=1 AND deadline IS NOT NULL AND deadline <= ?", (now_utc(),)
    )


# ---------------------------------------------------------------- submissions
async def add_submission(
    test_id: int, user_id: int, full_name: str, answers: list[str], correct: int, score: float, max_score: float
) -> bool:
    """False - foydalanuvchi bu testga avval javob yuborgan."""
    try:
        await _exec(
            "INSERT INTO submissions(test_id, user_id, full_name, answers, correct_count, score, max_score, "
            "submitted_at) VALUES(?,?,?,?,?,?,?,?)",
            (test_id, user_id, full_name, json.dumps(answers, ensure_ascii=False), correct, score, max_score,
             now_utc()),
        )
    except Duplicate:
        return False
    return True


async def get_submission(test_id: int, user_id: int):
    return await _one("SELECT * FROM submissions WHERE test_id=? AND user_id=?", (test_id, user_id))


async def set_note(test_id: int, note: str | None) -> None:
    await _exec("UPDATE tests SET note=? WHERE id=?", (note or None, test_id))


async def submissions_all(test_id: int) -> list:
    """Testning barcha natijalari (reytingdan chiqarilganlari ham) - qayta hisoblash uchun."""
    return await _all("SELECT * FROM submissions WHERE test_id=? ORDER BY id", (test_id,))


async def update_questions(test_id: int, questions: list[dict]) -> None:
    await _exec(
        "UPDATE tests SET questions=?, edited_at=? WHERE id=?",
        (json.dumps(questions, ensure_ascii=False), now_utc(), test_id),
    )


async def update_grade(sub_id: int, correct: int, score: float, max_score: float) -> None:
    await _exec(
        "UPDATE submissions SET correct_count=?, score=?, max_score=? WHERE id=?",
        (correct, score, max_score, sub_id),
    )


async def get_submission_by_id(sub_id: int):
    return await _one("SELECT * FROM submissions WHERE id=?", (sub_id,))


async def submissions_ranked(test_id: int, limit: int | None = None) -> list:
    sql = (
        "SELECT s.*, u.username FROM submissions s LEFT JOIN users u ON u.id=s.user_id "
        "WHERE s.test_id=? AND s.is_hidden=0 ORDER BY s.score DESC, s.submitted_at ASC, s.id ASC"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return await _all(sql, (test_id,))


async def count_submissions(test_id: int) -> int:
    row = await _one("SELECT COUNT(*) AS c FROM submissions WHERE test_id=? AND is_hidden=0", (test_id,))
    return row["c"]


async def rank_of(sub) -> int:
    row = await _one(
        """SELECT COUNT(*) AS c FROM submissions WHERE test_id=? AND is_hidden=0 AND (
               score > ? OR (score = ? AND (submitted_at < ? OR (submitted_at = ? AND id < ?))))""",
        (sub["test_id"], sub["score"], sub["score"], sub["submitted_at"], sub["submitted_at"], sub["id"]),
    )
    return row["c"] + 1


async def submissions_by_user(user_id: int, limit: int, offset: int) -> list:
    return await _all(
        """SELECT s.*, t.title, t.code FROM submissions s JOIN tests t ON t.id=s.test_id
           WHERE s.user_id=? ORDER BY s.id DESC LIMIT ? OFFSET ?""",
        (user_id, limit, offset),
    )


async def count_submissions_by_user(user_id: int) -> int:
    row = await _one("SELECT COUNT(*) AS c FROM submissions WHERE user_id=?", (user_id,))
    return row["c"]


async def recent_tests_for_user(user_id: int, limit: int) -> list:
    """Foydalanuvchi yaratgan yoki qatnashgan oxirgi testlar (reyting ro'yxati uchun)."""
    return await _all(
        """SELECT t.id, t.title, t.code, t.owner_id FROM tests t
           WHERE t.owner_id=? OR t.id IN (SELECT test_id FROM submissions WHERE user_id=?)
           ORDER BY t.id DESC LIMIT ?""",
        (user_id, user_id, limit),
    )


# ---------------------------------------------------------------- fsm (yarim qolgan amallar)
async def fsm_get(user_id: int):
    return await _one("SELECT state, data FROM fsm WHERE user_id=?", (user_id,))


async def fsm_set(user_id: int, state: str | None, data: str) -> None:
    await _exec(
        "INSERT INTO fsm(user_id, state, data, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET state=excluded.state, data=excluded.data, updated_at=excluded.updated_at",
        (user_id, state, data, now_utc()),
    )


async def fsm_delete(user_id: int) -> None:
    await _exec("DELETE FROM fsm WHERE user_id=?", (user_id,))


# ---------------------------------------------------------------- moderatsiya
async def participants(test_id: int, limit: int, offset: int) -> list:
    """Barcha ishtirokchilar (yashirilganlari ham) - muallif nazorati uchun."""
    return await _all(
        """SELECT s.*, u.username FROM submissions s LEFT JOIN users u ON u.id=s.user_id
           WHERE s.test_id=? ORDER BY s.score DESC, s.submitted_at ASC, s.id ASC LIMIT ? OFFSET ?""",
        (test_id, limit, offset),
    )


async def count_participants(test_id: int) -> int:
    row = await _one("SELECT COUNT(*) AS c FROM submissions WHERE test_id=?", (test_id,))
    return row["c"]


async def set_hidden(test_id: int, user_id: int, value: int, only_if: int) -> bool:
    """Natijaning ko'rinishini o'zgartiradi; faqat hozirgi qiymati only_if bo'lsa."""
    n = await _exec(
        "UPDATE submissions SET is_hidden=? WHERE test_id=? AND user_id=? AND is_hidden=?",
        (value, test_id, user_id, only_if),
    )
    return n > 0


async def hide_user_everywhere(user_id: int) -> None:
    await _exec("UPDATE submissions SET is_hidden=? WHERE user_id=? AND is_hidden=0", (HIDDEN_BY_BAN, user_id))


async def unhide_user_everywhere(user_id: int) -> None:
    await _exec("UPDATE submissions SET is_hidden=0 WHERE user_id=? AND is_hidden=?", (user_id, HIDDEN_BY_BAN))


async def anonymize_user(user_id: int, label: str) -> None:
    """Ismni bekor qiladi: foydalanuvchi qayta ro'yxatdan o'tadi, eski natijalarida ismi almashtiriladi."""
    await _exec("UPDATE users SET full_name=NULL WHERE id=?", (user_id,))
    await _exec("UPDATE submissions SET full_name=? WHERE user_id=?", (label, user_id))


async def get_banned_words() -> list:
    return await _all("SELECT word FROM banned_words ORDER BY word")


async def add_banned_word(word: str) -> None:
    await _exec("INSERT INTO banned_words(word) VALUES(?) ON CONFLICT(word) DO NOTHING", (word,))


async def delete_banned_word(word: str) -> None:
    await _exec("DELETE FROM banned_words WHERE word=?", (word,))


# ---------------------------------------------------------------- sozlamalar (kalit -> qiymat)
async def get_setting(key: str) -> str | None:
    row = await _one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    await _exec(
        "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


# ---------------------------------------------------------------- adminlar (bot ichidan qo'shilganlar)
async def get_admins() -> list:
    return await _all("SELECT * FROM admins ORDER BY added_at, user_id")


async def add_admin(user_id: int, added_by: int) -> None:
    await _exec(
        "INSERT INTO admins(user_id, added_by, added_at) VALUES(?,?,?) ON CONFLICT(user_id) DO NOTHING",
        (user_id, added_by, now_utc()),
    )


async def remove_admin(user_id: int) -> None:
    await _exec("DELETE FROM admins WHERE user_id=?", (user_id,))
