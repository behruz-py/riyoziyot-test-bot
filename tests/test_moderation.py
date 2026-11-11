"""Ishga tushirish: .venv\\Scripts\\python -m tests.test_moderation"""
from bot.handlers.start import valid_name
from bot.moderation import is_bad_builtin, normalize

# Filtr bularni o'tkazib yuborishi SHART (oddiy ism, familiya va test nomlari)
GOOD = """
Aliyev Vali; Abdullayeva Mohinur Shavkat qizi; Karimov Islom; Hasanov Husan; Xasanova Xurshida; Sikandar Lodi;
Iskandarov Iskandar; Amirov Amir; Amonov Omon; Kotibov Sardor; Qosimov Qodir; Zebo Alimova; Zeba Latipova;
Anas Ukasha; Musa Kamolov; Yunus Karimov; Sukayna Rahimova; Eshmatov Toshmat; Eshonqulov Eshon;
Shukurov Shukur; Xudoyberdiyev Xudoyor; Huseynov Husayn; Pirmatov Pirnazar; Gavhar Ergasheva;
Ahmadov Ahmad; Ahmedov Ahmed; Samandarov Samandar; Kamola Yoqubova; Sitora Bahromova; Asal Nematova;
Алиев Вали; Каримова Гулноза; Хусанов Хусан; Сикандаров Собир; Ойбек Қодиров; O'tkirov Sa'dulla;
G‘ulomov G‘ayrat; Mo'minov Mo'min; Dilnoza Salimova; Bobur Mirzo; Ustoz Karimov; Admin Adminov;
Algebra 9-sinf 2-nazorat ishi; Matematika DTM 2026 1-variant; Fizika klassik mexanika; Analitik geometriya;
Tarix 7-sinf yakuniy test; Kimyo: kislotalar va asoslar; Ona tili va adabiyot; Ingliz tili Grammar Test
"""

# Filtr bularni ushlashi SHART
BAD = """
Jalab Jalabov; JALAB; j a l a b; J@l4b; jaaalaaab; жалаб; ж а л а б; Вася Сука; suka; с у к а; s.u.k.a;
Qotoq; qo'toq; kotok; Xuy Xuyev; хуй; huy; pizdes; Пиздабол; blyat; бляд; fuck you; FUCKER; f u c k;
Eshak Eshakov; ahmoq bola; Ali ahmoq; onangni; Dalbayob; gandon; pidaras; Sex Sexov; bitch; siktir; Sikaman
"""


def items(block: str) -> list[str]:
    return [x.strip() for x in block.replace("\n", " ").split(";") if x.strip()]


def main():
    assert normalize("Ж@лаааб!") == "jalab"
    assert normalize("Qo‘toq") == "kotok"

    wrong = [x for x in items(GOOD) if is_bad_builtin(x)]
    assert not wrong, f"Oddiy ismlar noto'g'ri ushlandi: {wrong}"
    missed = [x for x in items(BAD) if not is_bad_builtin(x)]
    assert not missed, f"Ushlanmay qoldi: {missed}"

    # Ism shakli: faqat harflar, bo'shliq, tire, nuqta, apostrof
    for name in ("Aliyev Vali", "O'tkirov Sa'dulla", "G‘ulomov G‘ayrat", "Алиев Вали", "Abdulla-zoda A."):
        assert valid_name(name) == name, name
    for name in ("Al", "12345", "Ali 777", "Ali 😀", "<b>Ali</b>", "t.me/kanal", "@username", "...", "a" * 61):
        assert valid_name(name) is None, name
    print("moderation: OK")


if __name__ == "__main__":
    main()
