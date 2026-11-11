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
    # Kirill homogliflari (а, с, е)
    assert kp.parse_answers("аbсd") == list("abcd")

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
    qs = kp.build_questions(kp.parse_answers("1. a\n2. 0.5|1/2\n3. Toshkent"))
    assert [q["t"] for q in qs] == ["c", "o", "o"]
    assert raises(kp.build_questions, ["a", "-"])

    # Ochiq javoblarni solishtirish
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
    qs = kp.build_questions(kp.parse_answers("1. a\n2. b\n3. 12.5\n4. d"))
    for q, p in zip(qs, [1, 2, 3.5, 1]):
        q["p"] = p
    ans = kp.parse_answers("1. a\n2. c\n3. 12,50\n4. -")
    assert kp.validate_answers(qs, ans) is None
    res = kp.grade(qs, ans)
    assert res["flags"] == [1, 0, 1, -1] and res["correct"] == 2
    assert res["score"] == 4.5 and res["max_score"] == 7.5
    assert kp.validate_answers(qs, ["a", "b"]) is not None
    assert kp.validate_answers(qs, ["a", "xyz", "1", "d"]) is not None  # variantli savolga matn

    assert kp.fmt_num(4.5) == "4.5" and kp.fmt_num(3.0) == "3" and kp.fmt_num(0) == "0"
    assert kp.fmt_num(33.300000001) == "33.3"
    print("keyparser: OK")


if __name__ == "__main__":
    main()
