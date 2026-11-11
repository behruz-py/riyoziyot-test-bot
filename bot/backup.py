"""Bazaning zaxira nusxasi (SQLite va PostgreSQL uchun bir xil format: gzip qilingan JSON).

Nusxa olish:   bot ichida - admin panel «💾 Zaxira nusxa» yoki kunlik avtomatik yuborish.
Tiklash:       python -m bot.backup restore zaxira_2026-11-11.json.gz
               (.env dagi DATABASE_URL / DB_PATH ko'rsatgan bazaga; baza BO'SH bo'lishi kerak)
"""
from __future__ import annotations

import asyncio
import gzip
import json
import sys
from pathlib import Path

from . import config, db

# Tartib muhim: submissions tests ga bog'langan. fsm (yarim qolgan amallar) nusxaga kirmaydi.
TABLES = ["users", "channels", "tests", "submissions", "banned_words", "settings"]
_SERIAL_TABLES = ["channels", "tests", "submissions"]  # id ustuni avtomatik o'sadigan jadvallar
FORMAT_VERSION = 1


async def dump() -> bytes:
    tables = {name: [dict(row) for row in await db._all(f"SELECT * FROM {name} ORDER BY 1")] for name in TABLES}
    payload = {"format": FORMAT_VERSION, "created_at": db.now_utc(), "tables": tables}
    return gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def summary(data: bytes) -> dict[str, int]:
    """Nusxadagi yozuvlar soni (jadval -> son)."""
    payload = json.loads(gzip.decompress(data).decode("utf-8"))
    return {name: len(rows) for name, rows in payload["tables"].items()}


async def restore(data: bytes) -> dict[str, int]:
    """Nusxani bo'sh bazaga tiklaydi. Bazada ma'lumot bo'lsa RuntimeError."""
    payload = json.loads(gzip.decompress(data).decode("utf-8"))
    if payload.get("format") != FORMAT_VERSION:
        raise RuntimeError(f"Noma'lum nusxa formati: {payload.get('format')}")
    for name in ("users", "tests", "submissions"):
        row = await db._one(f"SELECT COUNT(*) AS c FROM {name}")
        if row["c"]:
            raise RuntimeError(f"Baza bo'sh emas ({name} jadvalida {row['c']} ta yozuv). Tiklash bekor qilindi.")

    counts = {}
    for name in TABLES:
        rows = payload["tables"].get(name, [])
        for row in rows:
            columns = list(row)
            await db._exec(
                f"INSERT INTO {name}({', '.join(columns)}) VALUES({', '.join('?' * len(columns))})",
                tuple(row[c] for c in columns),
            )
        counts[name] = len(rows)
    if db._pool is not None:
        # PostgreSQL: id hisoblagichlarini tiklangan eng katta id dan keyinga suramiz
        for name in _SERIAL_TABLES:
            await db._one(
                f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {name}), 0) + 1, false) AS v"
            )
    return counts


async def _cli() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "restore":
        sys.exit("Foydalanish: python -m bot.backup restore <fayl.json.gz>")
    data = Path(sys.argv[2]).read_bytes()
    target = config.DATABASE_URL or config.DB_PATH
    print("Tiklanadigan baza:", "PostgreSQL (DATABASE_URL)" if config.DATABASE_URL else target)
    print("Nusxadagi yozuvlar:", summary(data))
    await db.init(target)
    try:
        print("Tiklandi:", await restore(data))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(_cli())
