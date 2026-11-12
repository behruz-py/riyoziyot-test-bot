"""Ishga tushirish: .venv\\Scripts\\python -m tests.test_keyparser"""
from bot import keyparser as kp


def raises(fn, *args):
    try:
        fn(*args)
    except kp.ParseError:
        return True
    return False


def main():
    # Ixcham formatlar
    assert kp.parse_answers("abcd") == list("abcd")
    assert kp.parse_answers("ABCD ab\ncd") == list("abcdabcd")
    assert kp.parse_answers("1a2b3c4d") == list("abcd")
    assert kp.parse_answers("1a 2B 3c\n4d") == list("abcd")
    assert kp.parse_answers("1a2b3c4d5a6b7c8d9a10b11c") == list("abcdabcdabc")
    assert kp.parse_answers("ab-d") == ["a", "b", "-", "d"]
    assert kp.parse_answers("1a2-3c") == ["a", "-", "c"]
    assert raises(kp.parse_answers, "1a2b4c")  # raqam tushib qolgan
    assert raises(kp.parse_answers, "")
    # Kirill homogliflari (а, с, В)
    assert kp.parse_answers("аbсd") == list("abcd")
    assert kp.parse_answers("АВСD") == list("abcd")

    # Faqat A-D: katta harf bilan ham, E/F - aniq xato
    assert kp.parse_answers("ABCDABCD") == list("abcdabcd")
    assert kp.parse_answers("1A2B3C4D") == list("abcd")
    assert kp.parse_answers("1A 2b 3C 4d") == list("abcd")
    assert kp.parse_answers("1. A\n2. 12.5\n3. D") == ["a", "12.5", "d"]
    for bad in ("abcde", "ABCDF", "1A2B3E", "1. a\n2. e", "1a\n2f", "a;b;e"):
        try:
            kp.parse_answers(bad)
            raise AssertionError(f"E/F qabul qilindi: {bad!r}")
        except kp.ParseError as e:
            assert "faqat <b>A, B, C, D</b>" in str(e), str(e)
    try:
        kp.parse_answers("abcde")
    except kp.ParseError as e:
        assert str(e).startswith("5-savolda «E»"), str(e)
    assert kp.fmt_answer("b") == "B" and kp.fmt_answer("x=2") == "x=2" and kp.fmt_answer("-") == "—"

    # Qatorma-qator format
    assert kp.parse_answers("1. a\n2. 12.5\n3. x=2") == ["a", "12.5", "x=2"]
    assert kp.parse_answers("1) A\n2) -5\n3: 1/2") == ["a", "-5", "1/2"]
    assert kp.parse_answers("a; 12,5; x = 2") == ["a", "12,5", "x = 2"]
    assert kp.parse_answers("a\n-3\n15") == ["a", "-3", "15"]
    assert kp.parse_answers("12\n15\n7") == ["12", "15", "7"]
    assert kp.parse_answers("1.5\n7.25\n3") == ["1.5", "7.25", "3"]  # raqamlanmagan o'nli kasrlar
    assert kp.parse_answers("1. a\n2. -\n3. 7") == ["a", "-", "7"]
    assert kp.parse_answers("1a\n2 b\n3. 44") == ["a", "b", "44"]
    assert raises(kp.parse_answers, "1. a\n2. b\n4. c")
    assert raises(kp.parse_answers, "x" * 100 + "\n1")

    # Kalit tuzish
    # Kalitda faqat A-D: ochiq (yozma) javob qabul qilinmaydi
    for bad in ("1. a\n2. 0.5|1/2\n3. Toshkent", "1. a\n2. 12", "ABCDX", "1A2B3X"):
        try:
            kp.build_questions(kp.parse_answers(bad))
            raise AssertionError(f"ochiq javob kalitga qabul qilindi: {bad!r}")
        except kp.ParseError as e:
            assert "A, B, C yoki D" in str(e) or "faqat" in str(e), (bad, str(e))
    qs = kp.build_questions(kp.parse_answers("1. a\n2. B\n3. c"))
    assert [q["t"] for q in qs] == ["c", "c", "c"]
    assert raises(kp.build_questions, ["a", "-"])

    # Ochiq javoblarni solishtirish (faqat avvalgi versiyada yaratilgan eski testlar uchun saqlangan)
    assert kp.open_equal("0,50", "0.5")
    assert kp.open_equal("1/2", "0.5")
    assert kp.open_equal("2/4", "0.5|3")
    assert kp.open_equal(" TOSHKENT ", "toshkent")
    assert kp.open_equal("x = 2", "x=2")
    assert kp.open_equal("-5", "-5.0")
    assert kp.open_equal("o‘n", "o'n")
    assert not kp.open_equal("0.51", "0.5")
    assert not kp.open_equal("1/0", "0.5")
    assert not kp.open_equal("", "5")

    # Ballar
    assert kp.parse_points("1-2: 1.1; 3: 2.5", 4) == [1.1, 1.1, 2.5, 1.0]
    assert kp.parse_points("1-4=2", 4) == [2.0] * 4
    assert kp.parse_points("1-2:1.1, 3-4:2.1", 4) == [1.1, 1.1, 2.1, 2.1]
    assert raises(kp.parse_points, "1-5: 2", 4)
    assert raises(kp.parse_points, "1-2: 1,1", 4)
    assert raises(kp.parse_points, "salom", 4)
    assert raises(kp.parse_points, "1: 0", 4)

    # Tekshirish va baholash
    # Eski (ochiq savolli) test ham to'g'ri baholanadi
    qs = [{"t": "c", "a": "a", "p": 1.0}, {"t": "c", "a": "b", "p": 1.0}, {"t": "o", "a": "12.5", "p": 1.0},
          {"t": "c", "a": "d", "p": 1.0}]
    for q, p in zip(qs, [1, 2, 3.5, 1]):
        q["p"] = p
    ans = kp.parse_answers("1. a\n2. c\n3. 12,50\n4. -")
    assert kp.validate_answers(qs, ans) is None
    res = kp.grade(qs, ans)
    assert res["flags"] == [1, 0, 1, -1] and res["correct"] == 2
    assert res["score"] == 4.5 and res["max_score"] == 7.5
    assert kp.validate_answers(qs, ["a", "b"]) is not None
    assert kp.validate_answers(qs, ["a", "xyz", "1", "d"]) is not None  # variantli savolga matn
    assert "A, B, C yoki D" in kp.validate_answers(qs, ["a", "xyz", "1", "d"])

    # Ayrim savollarni tuzatish
    assert kp.parse_corrections("5 B", 10) == {5: "b"}
    assert kp.parse_corrections("5. b\n12 D\n7 = A", 20) == {5: "b", 12: "d", 7: "a"}
    assert kp.parse_corrections("5B; 6) c; 7: D", 10) == {5: "b", 6: "c", 7: "d"}
    assert kp.parse_corrections("2 В", 5) == {2: "b"}  # kirill В
    for bad, error in (("11 B", "11-savol yo'q"), ("0 A", "0-savol yo'q"), ("2 E", "faqat"), ("2 -", "ko'rsatilmagan"),
                       ("2 A\n2 B", "ikki marta"), ("B", "tushunmadim"), ("", "bo'sh"),
                       ("7 12.5", "A, B, C yoki D"), ("3 0.5|1/2", "A, B, C yoki D")):
        try:
            kp.parse_corrections(bad, 10)
            raise AssertionError(f"qabul qilindi: {bad!r}")
        except kp.ParseError as e:
            assert error in str(e), (bad, str(e))
    qs = kp.build_questions(["a", "b", "c"])
    qs[1]["p"] = 2.5
    new = kp.apply_answers(qs, {1: "d", 3: "a"})
    assert [(q["t"], q["a"], q["p"]) for q in new] == [("c", "d", 1.0), ("c", "b", 2.5), ("c", "a", 1.0)]
    assert qs[0]["a"] == "a", "asl ro'yxat o'zgarib qoldi"

    assert kp.fmt_num(4.5) == "4.5" and kp.fmt_num(3.0) == "3" and kp.fmt_num(0) == "0"
    assert kp.fmt_num(33.300000001) == "33.3"
    # Natijaga baho: chegaralar
    from bot.services import feedback
    for pct, start in ((100, "🏆 A'lo"), (99.9, "🌟 Juda yaxshi"), (85, "🌟 Juda yaxshi"), (84.9, "👍 Yaxshi"),
                       (70, "👍 Yaxshi"), (69.9, "🙂 Qoniqarli"), (50, "🙂 Qoniqarli"), (49.9, "💪"), (0, "💪")):
        assert feedback(pct).startswith(start), (pct, feedback(pct))
    print("keyparser: OK")


if __name__ == "__main__":
    main()
