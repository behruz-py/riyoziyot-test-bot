"""Javoblar kalitini va o'quvchi javoblarini o'qish hamda tekshirish.

Qo'llab-quvvatlanadigan formatlar:
  1) Ixcham:        abcdabcd            (har bir harf - bitta savol)
  2) Raqamli:       1a2b3c4d  yoki  1a 2b 3c
  3) Qatorma-qator: har qatorda bitta javob (ochiq javoblar uchun)
         1. a
         2. 12.5
         3. x=2
     yoki ";" bilan ajratib:  a; 12.5; x=2

Bitta harf (a-f) -> variantli savol, boshqa har qanday qiymat -> ochiq javob.
"-" -> javob berilmagan (faqat o'quvchi javobida).
Ochiq javob kalitida "|" bilan bir nechta to'g'ri variant berish mumkin: 0.5|1/2
"""
from __future__ import annotations

import re
from fractions import Fraction

from .config import MAX_OPEN_ANSWER_LEN, MAX_QUESTIONS

LETTERS = "abcdef"
SKIP = "-"

# Lotin harfiga aynan o'xshash kirill harflari (klaviatura almashmay qolganda)
_HOMOGLYPHS = str.maketrans({"а": "a", "А": "A", "с": "c", "С": "C", "е": "e", "Е": "E"})
_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "`": "'", "ʻ": "'", "ʼ": "'", "−": "-", "–": "-", "—": "-"})

_RE_COMPACT_LETTERS = re.compile(r"[a-f\-]+")
_RE_COMPACT_NUMBERED = re.compile(r"(?:\d+[a-f\-])+")
_RE_PAIR = re.compile(r"(\d+)([a-f\-])")
_RE_ITEM_SEP = re.compile(r"^(\d+)\s*[.):]\s*(\S.*)$", re.S)
_RE_ITEM_LETTER = re.compile(r"^(\d+)\s*([a-fA-F\-])$")
_RE_DECIMAL = re.compile(r"^-?\d+(?:\.\d+)?$")
_RE_FRACTION = re.compile(r"^(-?\d+)/(\d+)$")
_RE_POINTS = re.compile(r"(\d+)(?:\s*-\s*(\d+))?\s*[:=]\s*(\d+(?:\.\d+)?)")


class ParseError(ValueError):
    """Foydalanuvchiga ko'rsatiladigan xato matni bilan."""


def _check_sequence(numbers: list[int]) -> None:
    for expected, got in enumerate(numbers, start=1):
        if got != expected:
            raise ParseError(
                f"Savol raqamlari ketma-ket emas: {expected}-savol o'rnida {got} turibdi. "
                "Raqamlar 1 dan boshlab tartib bilan yozilishi kerak."
            )


def _clean(ans: str) -> str:
    ans = ans.strip()
    if len(ans) == 1 and ans.lower() in LETTERS:
        return ans.lower()
    return ans


def parse_answers(text: str) -> list[str]:
    """Matndan javoblar ro'yxatini ajratib oladi."""
    text = (text or "").translate(_HOMOGLYPHS).translate(_APOSTROPHES).strip()
    if not text:
        raise ParseError("Javoblar bo'sh.")

    compact = re.sub(r"\s+", "", text).lower()
    if _RE_COMPACT_LETTERS.fullmatch(compact):
        answers = list(compact)
    elif _RE_COMPACT_NUMBERED.fullmatch(compact):
        pairs = _RE_PAIR.findall(compact)
        _check_sequence([int(n) for n, _ in pairs])
        answers = [a for _, a in pairs]
    else:
        items = [x.strip() for x in re.split(r"[\n;]+", text) if x.strip()]
        parsed = []
        for item in items:
            m = _RE_ITEM_SEP.match(item) or _RE_ITEM_LETTER.match(item)
            parsed.append((int(m.group(1)), m.group(2)) if m else None)
        if all(parsed):
            _check_sequence([n for n, _ in parsed])
            answers = [_clean(a) for _, a in parsed]
        else:
            answers = [_clean(x) for x in items]

    if len(answers) > MAX_QUESTIONS:
        raise ParseError(f"Savollar soni {MAX_QUESTIONS} tadan oshmasligi kerak.")
    for i, a in enumerate(answers, start=1):
        if len(a) > MAX_OPEN_ANSWER_LEN:
            raise ParseError(f"{i}-javob juda uzun (ko'pi bilan {MAX_OPEN_ANSWER_LEN} belgi).")
    return answers


def build_questions(answers: list[str]) -> list[dict]:
    """Kalit javoblaridan savollar ro'yxatini tuzadi: {"t": "c"|"o", "a": javob, "p": ball}."""
    questions = []
    for i, a in enumerate(answers, start=1):
        if a == SKIP or not a.strip("| "):
            raise ParseError(f"{i}-savolning to'g'ri javobi ko'rsatilmagan.")
        if len(a) == 1 and a in LETTERS:
            questions.append({"t": "c", "a": a, "p": 1.0})
        else:
            questions.append({"t": "o", "a": a, "p": 1.0})
    return questions


def parse_points(text: str, n: int) -> list[float]:
    """"1-10: 1.1; 11-20: 2.1; 21: 3.1" ko'rinishidagi matndan ballar ro'yxati (ko'rsatilmaganlari 1 ball)."""
    text = (text or "").strip()
    matches = list(_RE_POINTS.finditer(text))
    leftover = re.sub(r"[\s,;]+", "", _RE_POINTS.sub("", text))
    if not matches or leftover:
        raise ParseError(
            "Format noto'g'ri. Namuna: <code>1-10: 1.1; 11-20: 2.1; 21: 3</code>\n"
            "Kasr ballarda nuqta ishlating (2.5)."
        )
    points = [1.0] * n
    for m in matches:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        value = float(m.group(3))
        if not (1 <= start <= end <= n):
            raise ParseError(f"Savol raqami noto'g'ri: {m.group(0).strip()} (testda {n} ta savol bor).")
        if not (0 < value <= 100):
            raise ParseError("Ball 0 dan katta va 100 dan oshmasligi kerak.")
        for i in range(start - 1, end):
            points[i] = value
    return points


def _norm(s: str) -> str:
    s = s.translate(_HOMOGLYPHS).translate(_APOSTROPHES).lower()
    s = re.sub(r"\s+", "", s)
    return s.replace(",", ".")


def _as_number(s: str) -> Fraction | None:
    if _RE_DECIMAL.match(s):
        return Fraction(s)
    m = _RE_FRACTION.match(s)
    if m and int(m.group(2)) != 0:
        return Fraction(int(m.group(1)), int(m.group(2)))
    return None


def open_equal(user_answer: str, key_answer: str) -> bool:
    """Ochiq javobni solishtiradi: registr/bo'shliqlarsiz, sonlar qiymati bo'yicha (0.5 == 1/2 == 0,50)."""
    u = _norm(user_answer)
    u_num = _as_number(u)
    for variant in key_answer.split("|"):
        k = _norm(variant)
        if not k:
            continue
        if u == k:
            return True
        k_num = _as_number(k)
        if u_num is not None and k_num is not None and u_num == k_num:
            return True
    return False


def validate_answers(questions: list[dict], answers: list[str]) -> str | None:
    """O'quvchi javoblari testga mos kelishini tekshiradi. Xato bo'lsa matnini qaytaradi."""
    if len(answers) != len(questions):
        return f"Testda <b>{len(questions)}</b> ta savol bor, siz esa <b>{len(answers)}</b> ta javob yubordingiz."
    for i, (q, a) in enumerate(zip(questions, answers), start=1):
        if q["t"] == "c" and a != SKIP and not (len(a) == 1 and a in LETTERS):
            return (
                f"{i}-savol variantli (A–F), lekin siz «{a[:20]}» deb yubordingiz. "
                "Variantli savolga faqat bitta lotin harfi yoziladi."
            )
    return None


def grade(questions: list[dict], answers: list[str]) -> dict:
    """Natija: flags[i] = 1 (to'g'ri) / 0 (xato) / -1 (javobsiz), correct, score, max_score."""
    flags: list[int] = []
    score = 0.0
    for q, a in zip(questions, answers):
        if a == SKIP:
            flags.append(-1)
            continue
        ok = (a == q["a"]) if q["t"] == "c" else open_equal(a, q["a"])
        flags.append(1 if ok else 0)
        if ok:
            score += q["p"]
    return {
        "flags": flags,
        "correct": sum(1 for f in flags if f == 1),
        "score": round(score, 2),
        "max_score": round(sum(q["p"] for q in questions), 2),
    }


def fmt_num(x: float) -> str:
    s = f"{round(float(x), 2):.2f}".rstrip("0").rstrip(".")
    return s or "0"


def fmt_answer(a: str) -> str:
    """Ko'rsatish uchun: variant harfi katta, javobsiz -> tire."""
    if a == SKIP:
        return "—"
    if len(a) == 1 and a in LETTERS:
        return a.upper()
    return a
