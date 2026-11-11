"""Yarim qolgan amallarni (FSM holatini) bazada saqlash.

Server qayta ishga tushsa yoki uxlab uyg'onsa ham foydalanuvchi to'xtagan joyidan davom etadi.
Xotiradagi kesh tufayli bazaga faqat holat o'zgarganda yoziladi.
"""
from __future__ import annotations

import json
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from . import db

_MAX_CACHE = 20_000


class DbStorage(BaseStorage):
    def __init__(self) -> None:
        self._cache: dict[int, tuple[str | None, dict[str, Any]]] = {}

    async def _load(self, key: StorageKey) -> tuple[str | None, dict[str, Any]]:
        uid = key.user_id
        if uid not in self._cache:
            row = await db.fsm_get(uid)
            if len(self._cache) >= _MAX_CACHE:
                self._cache.clear()
            self._cache[uid] = (row["state"], json.loads(row["data"])) if row else (None, {})
        return self._cache[uid]

    async def _save(self, key: StorageKey, state: str | None, data: dict[str, Any]) -> None:
        if await self._load(key) == (state, data):
            return
        self._cache[key.user_id] = (state, data)
        if state is None and not data:
            await db.fsm_delete(key.user_id)
        else:
            await db.fsm_set(key.user_id, state, json.dumps(data, ensure_ascii=False))

    async def set_state(self, key: StorageKey, state: str | State | None = None) -> None:
        _, data = await self._load(key)
        await self._save(key, state.state if isinstance(state, State) else state, data)

    async def get_state(self, key: StorageKey) -> str | None:
        return (await self._load(key))[0]

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        state, _ = await self._load(key)
        await self._save(key, state, json.loads(json.dumps(data)))  # nusxa + JSON'ga mosligini tekshirish

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        return json.loads(json.dumps((await self._load(key))[1]))

    async def close(self) -> None:
        self._cache.clear()
