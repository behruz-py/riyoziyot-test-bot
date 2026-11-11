"""Ishtirokchi uchun sertifikat rasmi (PNG).

Shriftni almashtirish uchun: assets/fonts/regular.ttf va assets/fonts/bold.ttf fayllarini qo'ying.
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import BASE_DIR

W, H = 1600, 1130
BG = "#FBF7EC"
NAVY = "#1F3A5F"
GOLD = "#B8901F"
TEXT = "#2B2B2B"

_FONTS = {
    "regular": [
        BASE_DIR / "assets/fonts/regular.ttf",
        Path("C:/Windows/Fonts/georgia.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
    ],
    "bold": [
        BASE_DIR / "assets/fonts/bold.ttf",
        Path("C:/Windows/Fonts/georgiab.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
    ],
}


@lru_cache(maxsize=64)
def _font(kind: str, size: int):
    for path in _FONTS[kind]:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _center(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill: str) -> int:
    """Matnni gorizontal markazga yozadi, keyingi qator uchun y ni qaytaradi."""
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((W - (right - left)) / 2 - left, y), text, font=font, fill=fill)
    return y + int(font.size * 1.35)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.") + "…"
    return lines


def _fit(draw: ImageDraw.ImageDraw, text: str, kind: str, size: int, max_width: int, min_size: int = 36):
    while size > min_size and draw.textlength(text, font=_font(kind, size)) > max_width:
        size -= 4
    return _font(kind, size)


def build_certificate(
    *, name: str, title: str, code: str, correct: int, total_q: int, score: str, max_score: str,
    percent: str, rank: int | None, participants: int, date: str,
) -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Hoshiya
    d.rectangle((30, 30, W - 30, H - 30), outline=NAVY, width=14)
    d.rectangle((62, 62, W - 62, H - 62), outline=GOLD, width=4)
    for x, y in ((62, 62), (W - 62, 62), (62, H - 62), (W - 62, H - 62)):
        d.ellipse((x - 16, y - 16, x + 16, y + 16), fill=GOLD)

    y = _center(d, 120, "SERTIFIKAT", _font("bold", 120), NAVY)
    d.line((W / 2 - 220, y + 4, W / 2 + 220, y + 4), fill=GOLD, width=5)
    y = _center(d, y + 40, "Ushbu sertifikat", _font("regular", 38), TEXT)

    name_font = _fit(d, name, "bold", 88, W - 320)
    if d.textlength(name, font=name_font) > W - 320:
        name = _wrap(d, name, name_font, W - 320, 1)[0]
    y = _center(d, y + 10, name, name_font, GOLD)
    d.line((240, y + 2, W - 240, y + 2), fill=NAVY, width=2)

    y += 34
    body = _font("regular", 40)
    for line in _wrap(d, f"«{title}» testida ishtirok etib, quyidagi natijani qayd etgani uchun beriladi:",
                      body, W - 360, 3):
        y = _center(d, y, line, body, TEXT)

    y = _center(d, y + 22, f"{score} / {max_score} ball   ({percent}%)", _font("bold", 68), NAVY)
    y = _center(d, y + 6, f"To'g'ri javoblar: {correct} ta  (jami {total_q} ta savol)", body, TEXT)
    if rank is not None:
        _center(d, y + 4, f"Ishtirokchilar orasida {rank}-o'rin  (jami {participants} nafar)",
                _font("bold", 42), GOLD)

    small = _font("regular", 30)
    d.text((110, H - 130), f"Sana: {date}", font=small, fill=TEXT)
    code_text = f"Test kodi: {code}"
    d.text((W - 110 - d.textlength(code_text, font=small), H - 130), code_text, font=small, fill=TEXT)

    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
