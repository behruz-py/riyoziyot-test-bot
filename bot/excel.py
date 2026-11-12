"""Test natijalari bo'yicha Excel hisobot."""
from __future__ import annotations

import json
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import keyparser as kp
from .services import to_local

_HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
_HEAD_FONT = Font(bold=True, color="FFFFFF")
_GREEN = PatternFill("solid", fgColor="C6EFCE")
_RED = PatternFill("solid", fgColor="FFC7CE")
_GRAY = PatternFill("solid", fgColor="EDEDED")
_CENTER = Alignment(horizontal="center", vertical="center")


def _safe(value: str) -> str:
    """Excel formulasi sifatida bajarilib ketmasligi uchun."""
    value = str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@") else value


def _header(ws, titles: list[str]) -> None:
    ws.append(titles)
    for cell in ws[1]:
        cell.fill = _HEAD_FILL
        cell.font = _HEAD_FONT
        cell.alignment = _CENTER
    ws.freeze_panes = "A2"


def build_report(test: dict, subs: list[dict], points: bool = True) -> bytes:
    """points=False («Ball tizimi» o'chiq) - hisobotda ball ustunlari bo'lmaydi, foiz to'g'ri javoblardan."""
    questions = json.loads(test["questions"])
    n = len(questions)
    wb = Workbook()

    # 1-varaq: reyting
    ws = wb.active
    ws.title = "Reyting"
    head = ["O'rin", "Ism familiya", "Username", "To'g'ri"] + (["Ball"] if points else []) + ["Foiz", "Topshirgan vaqti"]
    first_answer_col = len(head) + 1
    _header(ws, head + [str(i) for i in range(1, n + 1)])
    correct_per_q = [0] * n
    for pos, sub in enumerate(subs, start=1):
        answers = json.loads(sub["answers"])
        flags = kp.grade(questions, answers)["flags"]
        if points:
            pct = round(sub["score"] * 100 / sub["max_score"], 1) if sub["max_score"] else 0
        else:
            pct = round(sub["correct_count"] * 100 / n, 1) if n else 0
        ws.append(
            [pos, _safe(sub["full_name"]), f"@{sub['username']}" if sub.get("username") else "", sub["correct_count"]]
            + ([sub["score"]] if points else [])
            + [pct, to_local(sub["submitted_at"])]
            + [_safe(kp.fmt_answer(a)) for a in answers]
        )
        row = ws.max_row
        for i, flag in enumerate(flags):
            cell = ws.cell(row=row, column=first_answer_col + i)
            cell.alignment = _CENTER
            cell.fill = _GREEN if flag == 1 else _RED if flag == 0 else _GRAY
            if flag == 1:
                correct_per_q[i] += 1
    widths = [7, 30, 20, 9] + ([9] if points else []) + [8, 18]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for i in range(n):
        ws.column_dimensions[get_column_letter(first_answer_col + i)].width = 6 if questions[i]["t"] == "c" else 14

    # 2-varaq: savollar tahlili
    ws2 = wb.create_sheet("Savollar tahlili")
    _header(ws2, ["Savol", "Turi", "To'g'ri javob"] + (["Ball"] if points else [])
            + ["To'g'ri javob berganlar", "Foiz"])
    total = len(subs)
    for i, q in enumerate(questions):
        pct = round(correct_per_q[i] * 100 / total, 1) if total else 0
        ws2.append([i + 1, "Variantli" if q["t"] == "c" else "Ochiq", _safe(kp.fmt_answer(q["a"]))]
                   + ([q["p"]] if points else []) + [correct_per_q[i], pct])
        ws2.cell(row=ws2.max_row, column=ws2.max_column).fill = _GREEN if pct >= 70 else _RED if pct < 40 else _GRAY
    for i, width in enumerate([8, 12, 22] + ([8] if points else []) + [24, 8], start=1):
        ws2.column_dimensions[get_column_letter(i)].width = width

    # 3-varaq: umumiy ma'lumot
    ws3 = wb.create_sheet("Umumiy")
    values = [s["score"] if points else s["correct_count"] for s in subs]
    unit = "ball" if points else "to'g'ri javob"
    info = [
        ("Test nomi", _safe(test["title"])),
        ("Test kodi", test["code"]),
        ("Savollar soni", n),
        *([("Maksimal ball", round(sum(q["p"] for q in questions), 2))] if points else []),
        ("Ishtirokchilar", total),
        (f"O'rtacha ({unit})", round(sum(values) / total, 2) if total else 0),
        (f"Eng yuqori ({unit})", max(values) if values else 0),
        (f"Eng past ({unit})", min(values) if values else 0),
        ("Yaratilgan", to_local(test["created_at"])),
        ("Yakunlangan", to_local(test["finished_at"])),
    ]
    for key, value in info:
        ws3.append([key, value])
        ws3.cell(row=ws3.max_row, column=1).font = Font(bold=True)
    ws3.column_dimensions["A"].width = 22
    ws3.column_dimensions["B"].width = 40

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_users_report(users: list[dict]) -> bytes:
    """Admin uchun foydalanuvchilar ro'yxati."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Foydalanuvchilar"
    _header(ws, ["№", "ID", "Ism familiya", "Telegram nomi", "Username", "Qo'shilgan", "Oxirgi faollik",
                 "Yaratgan testlari", "Ishlagan testlari", "Holati"])
    for i, u in enumerate(users, start=1):
        if u["is_blocked"]:
            status = "Bloklangan"
        elif not u["is_active"]:
            status = "Botni to'xtatgan"
        elif not u["full_name"]:
            status = "Ro'yxatdan o'tmagan"
        else:
            status = "Faol"
        ws.append([
            i, u["id"], _safe(u["full_name"] or ""), _safe(u["tg_name"] or ""),
            f"@{u['username']}" if u["username"] else "", to_local(u["joined_at"]), to_local(u["last_seen"]),
            u["tests_count"], u["subs_count"], status,
        ])
        if status != "Faol":
            ws.cell(row=ws.max_row, column=10).fill = _RED if u["is_blocked"] else _GRAY
    for col, width in zip("ABCDEFGHIJ", (6, 14, 30, 26, 20, 18, 18, 17, 17, 20)):
        ws.column_dimensions[col].width = width
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
