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
    is_active   INTEGER NOT NULL DEFAULT 1
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
    UNIQUE(test_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_sub_user ON submissions(user_id);
CREATE TABLE IF NOT EXISTS fsm (
    user_id     {BIG} PRIMARY KEY,
    state       TEXT,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""
_SQLITE_TYPES = {"PK": "INTEGER PRIMARY KEY AUTOINCREMENT", "BIG": "INTEGER", "REAL": "REAL"}
_PG_TYPES = {"PK": "BIGSERIAL PRIMARY KEY", "BIG": "BIGINT", "REAL": "DOUBLE PRECISION"}

# Reyting tartibi: ball kamayishi bo'yicha, teng bo'lsa - oldin topshirgan yuqorida
# (submissions_ranked va rank_of bir xil tartibdan foydalanadi)


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
        log.info("Baza: PostgreSQL")
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(path)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.executescript(SCHEMA.format(**_SQLITE_TYPES))
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
    """Foydalanuvchini bazaga qo'shadi yoki ma'lumotini yangilaydi; qatorni qaytaradi."""
    row = await get_user(user_id)
    if row is None:
        await _exec(
            "INSERT INTO users(id, username, tg_name, joined_at) VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING",
            (user_id, username, tg_name, now_utc()),
        )
        return await get_user(user_id)
    if row["username"] != username or row["tg_name"] != tg_name or not row["is_active"]:
        await _exec(
            "UPDATE users SET username=?, tg_name=?, is_active=1 WHERE id=?", (username, tg_name, user_id)
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


async def stats() -> dict:
    today = now_utc()[:10]
    row = await _one(
        """SELECT
            (SELECT COUNT(*) FROM users) AS users,
            (SELECT COUNT(*) FROM users WHERE is_active=1 AND is_blocked=0) AS active_users,
            (SELECT COUNT(*) FROM users WHERE joined_at >= ?) AS users_today,
            (SELECT COUNT(*) FROM users WHERE is_blocked=1) AS blocked,
            (SELECT COUNT(*) FROM tests) AS tests,
            (SELECT COUNT(*) FROM tests WHERE is_active=1) AS active_tests,
            (SELECT COUNT(*) FROM tests WHERE created_at >= ?) AS tests_today,
            (SELECT COUNT(*) FROM submissions) AS subs,
            (SELECT COUNT(*) FROM submissions WHERE submitted_at >= ?) AS subs_today
        """,
        (today, today, today),
    )
    return dict(row)


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
        """SELECT t.*, (SELECT COUNT(*) FROM submissions s WHERE s.test_id=t.id) AS participants
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


async def submissions_ranked(test_id: int, limit: int | None = None) -> list:
    sql = (
        "SELECT s.*, u.username FROM submissions s LEFT JOIN users u ON u.id=s.user_id "
        "WHERE s.test_id=? ORDER BY s.score DESC, s.submitted_at ASC, s.id ASC"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return await _all(sql, (test_id,))


async def count_submissions(test_id: int) -> int:
    row = await _one("SELECT COUNT(*) AS c FROM submissions WHERE test_id=?", (test_id,))
    return row["c"]


async def rank_of(sub) -> int:
    row = await _one(
        """SELECT COUNT(*) AS c FROM submissions WHERE test_id=? AND (
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
