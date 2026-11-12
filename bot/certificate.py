"""Sertifikat / diplom chizish (PNG rasm va chop etish uchun PDF).

Natijaga qarab olti xil ko'rinish:
  - yakunlangan testda 1-2-3-o'rin  -> oltin / kumush / bronza DIPLOM
  - 85% va undan yuqori              -> SERTIFIKAT, a'lo daraja
  - 60% va undan yuqori              -> SERTIFIKAT, yaxshi daraja
  - qolganlar                        -> ISHTIROKCHI sertifikati

Shriftni almashtirish: assets/fonts/regular.ttf va assets/fonts/bold.ttf.
"""
from __future__ import annotations

import math
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import BASE_DIR

W, H = 2000, 1414  # A4 (yotiq) nisbati
PDF_DPI = 171.0    # 2000 px -> 297 mm
BG = "#FBF8F0"
INK = "#2B2B2B"
MUTED = "#6B6B6B"

# dark - hoshiya va sarlavha, accent - bezaklar, soft - och fon
TIERS = {
    "place1": {"dark": "#5C4306", "accent": "#C9971A", "soft": "#F6EBC8", "doc": "DIPLOM", "label": "I O'RIN"},
    "place2": {"dark": "#3E434B", "accent": "#8F96A1", "soft": "#ECEEF1", "doc": "DIPLOM", "label": "II O'RIN"},
    "place3": {"dark": "#5A3515", "accent": "#B4733A", "soft": "#F3E2D2", "doc": "DIPLOM", "label": "III O'RIN"},
    "excellent": {"dark": "#1F3A5F", "accent": "#C9971A", "soft": "#E9EEF5", "doc": "SERTIFIKAT",
                  "label": "A'LO DARAJA"},
    "good": {"dark": "#1D5C58", "accent": "#3F9C95", "soft": "#E4F1F0", "doc": "SERTIFIKAT",
             "label": "YAXSHI DARAJA"},
    "participant": {"dark": "#3F4A5A", "accent": "#7C8AA0", "soft": "#ECEFF3", "doc": "SERTIFIKAT",
                    "label": "ISHTIROKCHI"},
}
_TIER_TITLES = {
    "place1": "Diplom — I o'rin", "place2": "Diplom — II o'rin", "place3": "Diplom — III o'rin",
    "excellent": "Sertifikat — A'lo daraja", "good": "Sertifikat — Yaxshi daraja",
    "participant": "Sertifikat — Ishtirokchi",
}
_ROMAN = {1: "I", 2: "II", 3: "III"}
EXCELLENT_FROM = 85.0
GOOD_FROM = 60.0

_FONTS = {
    "regular": [
        BASE_DIR / "assets/fonts/regular.ttf",
        Path("C:/Windows/Fonts/georgia.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ],
    "bold": [
        BASE_DIR / "assets/fonts/bold.ttf",
        Path("C:/Windows/Fonts/georgiab.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ],
}


def pick_tier(percent: float, rank: int | None, score: float) -> str:
    """rank faqat yakunlangan testda beriladi (aks holda None)."""
    if rank in _ROMAN and score > 0:
        return f"place{rank}"
    if percent >= EXCELLENT_FROM:
        return "excellent"
    if percent >= GOOD_FROM:
        return "good"
    return "participant"


def tier_title(tier: str) -> str:
    """Foydalanuvchiga ko'rsatiladigan nom, masalan: "Diplom — I o'rin"."""
    return _TIER_TITLES[tier]


@lru_cache(maxsize=128)
def _font(kind: str, size: int):
    for path in _FONTS[kind]:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


# ---------------------------------------------------------------- matn yordamchilari
def _spaced_width(d: ImageDraw.ImageDraw, text: str, font, spacing: int) -> float:
    return sum(d.textlength(ch, font=font) for ch in text) + spacing * max(len(text) - 1, 0)


def _text(d: ImageDraw.ImageDraw, cx: float, y: float, text: str, font, fill: str, spacing: int = 0) -> int:
    """Matnni cx atrofida markazlab yozadi; pastki chegarasini (keyingi qator uchun y) qaytaradi."""
    if spacing:
        x = cx - _spaced_width(d, text, font, spacing) / 2
        for ch in text:
            d.text((x, y), ch, font=font, fill=fill)
            x += d.textlength(ch, font=font) + spacing
    else:
        d.text((cx - d.textlength(text, font=font) / 2, y), text, font=font, fill=fill)
    return int(y + font.size * 1.3)


def _wrap(d: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if d.textlength(trial, font=font) <= max_width or not current:
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


def _fit(d: ImageDraw.ImageDraw, text: str, kind: str, size: int, max_width: int, min_size: int = 40,
         spacing: int = 0):
    while size > min_size and _spaced_width(d, text, _font(kind, size), spacing) > max_width:
        size -= 4
    return _font(kind, size)


def _cut(d: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if d.textlength(text, font=font) <= max_width:
        return text
    while len(text) > 1 and d.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


# ---------------------------------------------------------------- bezaklar
def _frame(d: ImageDraw.ImageDraw, t: dict) -> None:
    d.rectangle((34, 34, W - 34, H - 34), outline=t["dark"], width=22)
    d.rectangle((74, 74, W - 74, H - 74), outline=t["accent"], width=4)
    d.rectangle((88, 88, W - 88, H - 88), outline=t["accent"], width=1)
    # Burchak naqshlari: ichkariga qaragan yoylar va nuqta
    for cx, cy, start in ((88, 88, 0), (W - 88, 88, 90), (W - 88, H - 88, 180), (88, H - 88, 270)):
        for radius, width in ((58, 4), (84, 2), (104, 1)):
            d.arc((cx - radius, cy - radius, cx + radius, cy + radius), start, start + 90, fill=t["accent"],
                  width=width)
        d.ellipse((cx - 11, cy - 11, cx + 11, cy + 11), fill=t["accent"])
    # Yon tomonlar o'rtasidagi romblar
    for cx, cy in ((W // 2, 81), (W // 2, H - 81), (81, H // 2), (W - 81, H // 2)):
        d.polygon([(cx, cy - 13), (cx + 13, cy), (cx, cy + 13), (cx - 13, cy)], fill=t["accent"])


def _seal(d: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, t: dict, mark: str) -> None:
    """Muhr: lentali tishli doira, o'rtasida o'rin raqami (mark) yoki, mark bo'sh bo'lsa, yulduz."""
    for sign in (-1, 1):
        x = cx + sign * radius * 0.42
        d.polygon(
            [(x - 30, cy + radius * 0.5), (x + 30, cy + radius * 0.5), (x + 30 + sign * 14, cy + radius * 1.72),
             (x + sign * 8, cy + radius * 1.5), (x - 30 + sign * 14, cy + radius * 1.72)],
            fill=t["dark"],
        )
    points = []
    teeth = 40
    for i in range(teeth * 2):
        r = radius if i % 2 == 0 else radius * 0.92
        angle = math.pi * i / teeth
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    d.polygon(points, fill=t["accent"])
    inner = radius * 0.78
    d.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), outline=BG, width=4)
    core = radius * 0.68
    d.ellipse((cx - core, cy - core, cx + core, cy + core), fill=t["dark"])
    if mark:
        font = _fit(d, mark, "bold", int(radius * 0.8), int(core * 1.5), min_size=20)
        left, top, right, bottom = d.textbbox((0, 0), mark, font=font)
        d.text((cx - (right + left) / 2, cy - (bottom + top) / 2), mark, font=font, fill=BG)
    else:  # besh qirrali yulduz
        star = []
        for i in range(10):
            r = core * (0.62 if i % 2 == 0 else 0.26)
            angle = -math.pi / 2 + math.pi * i / 5
            star.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        d.polygon(star, fill=BG)


def _qr(url: str, size: int, color: str) -> Image.Image:
    import qrcode

    code = qrcode.QRCode(border=1, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(url)
    code.make(fit=True)
    return code.make_image(fill_color=color, back_color="white").convert("RGB").resize((size, size), Image.NEAREST)


def _logo(data: bytes, max_w: int, max_h: int) -> Image.Image | None:
    try:
        img = Image.open(BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    img.thumbnail((max_w, max_h), Image.LANCZOS)
    return img


# ---------------------------------------------------------------- asosiy
def build_certificate(
    *, name: str, title: str, correct: int, total_q: int, score: str, max_score: str, percent: float,
    rank: int | None, participants: int, date: str, number: str, tier: str,
    verify_url: str | None = None, org: str | None = None, signer: str | None = None,
    signer_role: str | None = None, logo: bytes | None = None, show_points: bool = True,
) -> tuple[bytes, bytes]:
    """(PNG, PDF) qaytaradi. rank - faqat yakunlangan testda (aks holda None)."""
    t = TIERS[tier]
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    _frame(d, t)
    cx = W // 2

    # --- Yuqori qism: logotip va tashkilot nomi
    y = 128
    logo_img = _logo(logo, 520, 132) if logo else None
    if logo_img:
        img.paste(logo_img, (cx - logo_img.width // 2, y), logo_img)
        y += logo_img.height + 16
    if org:
        org_font = _fit(d, org.upper(), "bold", 38, W - 520, min_size=24, spacing=4)
        y = _text(d, cx, y, _cut(d, org.upper(), org_font, W - 420), org_font, t["dark"], spacing=4) + 4
    header_bottom = y

    # --- Asosiy blok: alohida qatlamga chiziladi va bo'sh joyga vertikal markazlanadi
    block = Image.new("RGBA", (W, 900), (0, 0, 0, 0))
    b = ImageDraw.Draw(block)
    by = 0
    doc_font = _font("bold", 138 if (logo_img or org) else 156)
    by = _text(b, cx, by, t["doc"], doc_font, t["dark"], spacing=18) - 14

    label_font = _font("bold", 36)
    label_w = _spaced_width(b, t["label"], label_font, 6) + 110
    b.rounded_rectangle((cx - label_w / 2, by, cx + label_w / 2, by + 66), radius=33, fill=t["accent"])
    _text(b, cx, by + 11, t["label"], label_font, "#FFFFFF", spacing=6)
    for sign in (-1, 1):  # yorliq yonidagi chiziqlar
        x0 = cx + sign * (label_w / 2 + 24)
        b.line((x0, by + 33, x0 + sign * 170, by + 33), fill=t["accent"], width=3)
    by += 66 + 34

    by = _text(b, cx, by, f"Ushbu {t['doc'].lower()} sohibi", _font("regular", 38), MUTED) + 2
    name_font = _fit(b, name, "bold", 100, W - 440, min_size=48)
    by = _text(b, cx, by, _cut(b, name, name_font, W - 400), name_font, t["dark"])
    b.line((cx - 430, by, cx + 430, by), fill=t["accent"], width=3)
    b.polygon([(cx, by - 9), (cx + 9, by), (cx, by + 9), (cx - 9, by)], fill=t["accent"])
    by += 30

    if tier.startswith("place"):
        phrase = f"testida ishtirokchilar orasida {_ROMAN[rank]} o'rinni egalladi."
    elif tier == "excellent":
        phrase = "testida a'lo natija ko'rsatdi."
    elif tier == "good":
        phrase = "testida yaxshi natija ko'rsatdi."
    else:
        phrase = "testida ishtirok etdi."
    body_font = _font("regular", 42)
    for line in _wrap(b, f"«{title}» {phrase}", body_font, W - 520, 3):
        by = _text(b, cx, by, line, body_font, INK)
    block_h = by

    # --- Ko'rsatkichlar qatori
    stats = [(f"{score} / {max_score}", "ball")] if show_points else []
    stats += [(f"{percent:.1f}".rstrip("0").rstrip(".") + "%", "natija"), (f"{correct} / {total_q}", "to'g'ri javoblar")]
    if rank is not None:
        stats.append((f"{rank} / {participants}", "o'rin"))
    stats_top, stats_h = 930, 126
    zone_top = header_bottom + 6
    offset = zone_top + max((stats_top - 24 - zone_top - block_h) // 2, 0)
    img.paste(block, (0, offset), block)

    col_w = 360
    x0 = cx - col_w * len(stats) / 2
    d.rounded_rectangle((x0 - 20, stats_top, x0 + col_w * len(stats) + 20, stats_top + stats_h), radius=20,
                        fill=t["soft"])
    for i, (value, label) in enumerate(stats):
        col_cx = x0 + col_w * i + col_w / 2
        value_font = _fit(d, value, "bold", 54, col_w - 40, min_size=30)
        _text(d, col_cx, stats_top + 14 + (54 - value_font.size) // 2, value, value_font, t["dark"])
        _text(d, col_cx, stats_top + 82, label, _font("regular", 28), MUTED)
        if i:
            d.line((x0 + col_w * i, stats_top + 22, x0 + col_w * i, stats_top + stats_h - 22), fill=t["accent"],
                   width=2)

    # --- Pastki qism: imzo (chapda), muhr (o'rtada), QR (o'ngda)
    base_y = 1254
    if signer:
        sx = 400
        d.line((sx - 230, base_y - 62, sx + 230, base_y - 62), fill=INK, width=2)
        signer_font = _fit(d, signer, "bold", 34, 520, min_size=22)
        _text(d, sx, base_y - 52, _cut(d, signer, signer_font, 560), signer_font, INK)
        if signer_role:
            role_font = _fit(d, signer_role, "regular", 26, 520, min_size=18)
            _text(d, sx, base_y - 8, _cut(d, signer_role, role_font, 560), role_font, MUTED)

    _seal(d, cx, 1150, 74, t, _ROMAN[rank] if tier.startswith("place") else "")

    if verify_url:
        size = 186
        qx, qy = W - 400 - size // 2, 1076
        d.rectangle((qx - 8, qy - 8, qx + size + 8, qy + size + 8), fill="white", outline=t["accent"], width=2)
        img.paste(_qr(verify_url, size, t["dark"]), (qx, qy))
        _text(d, qx + size / 2, qy + size + 14, "Haqiqiyligini tekshirish", _font("regular", 24), MUTED)

    _text(d, cx, 1288, f"№ {number}   •   {date}", _font("regular", 26), MUTED)

    png = BytesIO()
    img.save(png, "PNG", optimize=True)
    pdf = BytesIO()
    img.save(pdf, "PDF", resolution=PDF_DPI)
    return png.getvalue(), pdf.getvalue()
