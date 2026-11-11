"""Nomaqbul (so'kinish, haqorat) so'zlarni aniqlash: ism-familiya va test nomlari uchun.

Filtr mukammal emas - shuning uchun u birinchi to'siq xolos. Asosiy himoya: test muallifi ishtirokchini
reytingdan chiqara oladi, admin esa bloklaydi yoki ismini bekor qiladi (handlers/mytests.py, handlers/admin.py).

Matn solishtirishdan oldin bir xil ko'rinishga keltiriladi: kirill -> lotin, raqam/belgilar -> harf (0->o, @->a),
x->h, q->k, takror harflar bitta qilinadi. Shu sabab "ж а л а б", "J@l4b", "jaaalab" bir xil ushlanadi.
"""
from __future__ import annotations

import re

from . import db

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "қ": "k", "ғ": "g", "ў": "o", "ҳ": "h",
}
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
_MAP = str.maketrans({**_CYR, **_LEET, "x": "h", "q": "k"})


def normalize(word: str) -> str:
    """Bitta so'zni solishtirish uchun yagona ko'rinishga keltiradi (faqat a-z, takrorsiz)."""
    word = word.lower().translate(_MAP)
    word = re.sub(r"[^a-z]", "", word)
    return re.sub(r"(.)\1+", r"\1", word)


# So'z ichida uchrasa ham ushlanadigan o'zaklar (uzun va boshqa so'zlarga o'xshamaydiganlari)
_STEMS_RAW = """
jalab qotoq qutoq sikaman sikay sikish siktir skaman amingga amingni onangni onengni
dalbayob dalbayop dolboyob qanjiq haromi haromzoda fohisha gandon pidaras pidaraz pidor pidar
blyad blyat bliad pizd yeban yoban ebat ebal uyeb mudak zalup shlyux shlux govn gavn
eshak ahmoq tentak itvachcha iflos kotingga kutingga
fuck bitch pussy porn asshole whore penis vagina nigger
"""
# Faqat alohida so'z bo'lib kelganda ushlanadiganlar (qisqa yoki ismlar ichida uchrashi mumkin)
_WORDS_RAW = "suka xuy huy sik am kot chmo sex seks dick cunt shit lox loh slut pidr blya ske skey"

_STEMS = {normalize(w) for w in _STEMS_RAW.split()}
_WORDS = {normalize(w) for w in _WORDS_RAW.split()}

_custom: set[str] | None = None  # admin qo'shgan so'zlar (bazadan)


def _check(text: str, extra: set[str]) -> bool:
    tokens = [t for t in (normalize(w) for w in text.split()) if t]
    if not tokens:
        return False
    stems = _STEMS | {w for w in extra if len(w) >= 4}
    words = _WORDS | {w for w in extra if len(w) < 4}
    for token in tokens:
        if token in words or any(stem in token for stem in stems):
            return True
    # Harflarni bo'shliq bilan ajratib yozish ("j a l a b"): qisqa bo'laklar ko'p bo'lsa, qo'shib tekshiramiz
    if sum(1 for t in tokens if len(t) <= 2) >= 3:
        joined = "".join(tokens)
        if any(bad in joined for bad in stems | {w for w in words if len(w) >= 4}):
            return True
    return False


def is_bad_builtin(text: str) -> bool:
    """Faqat ichki ro'yxat bo'yicha (bazaga murojaatsiz)."""
    return _check(text, set())


async def custom_words() -> set[str]:
    global _custom
    if _custom is None:
        _custom = {r["word"] for r in await db.get_banned_words()}
    return _custom


async def is_bad(text: str) -> bool:
    return _check(text, await custom_words())


async def add_word(raw: str) -> str | None:
    """Admin so'zini qo'shadi. Normallashtirilgan ko'rinishini qaytaradi (yaroqsiz bo'lsa None)."""
    word = normalize(raw)
    if not (2 <= len(word) <= 30):
        return None
    await db.add_banned_word(word)
    (await custom_words()).add(word)
    return word


async def remove_word(word: str) -> None:
    await db.delete_banned_word(word)
    (await custom_words()).discard(word)


def reset_cache() -> None:
    global _custom
    _custom = None
