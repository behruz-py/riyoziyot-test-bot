# Riyoziyot test boti

Javoblar kaliti asosida test o'tkazadigan Telegram bot (Python 3.11+, aiogram 3, SQLite).

## Imkoniyatlar

- **Test yaratish** (har qanday foydalanuvchi): nom → javoblar kaliti → ball tizimi → muddat (ixtiyoriy).
  - Variantli (A–F) va ochiq (yozma) javobli savollar; ochiq javobda bir nechta to'g'ri variant (`0.5|1/2`).
  - Har bir savol 1 ball yoki savollarga alohida ball (`1-10: 1.1; 11-20: 2.1`).
  - Muddatsiz yoki muddatli; muddat tugagach test avtomatik yakunlanadi.
- **Javobni tekshirish**: kod → javoblar, yoki tezkor `12345*abcd...`, yoki havola orqali (`t.me/bot?start=test_12345`).
  - Har bir testga bir marta javob yuboriladi. Natija: to'g'ri javoblar soni, ball, foiz, o'rin, xato va javobsiz savollar.
  - To'g'ri javoblar faqat test yakunlangach ochiladi (kalit tarqalib ketmasligi uchun).
- **Reyting**: ball bo'yicha, teng bo'lsa — oldin topshirgan yuqorida. Faqat ishtirokchi, muallif va adminlar ko'radi.
- **Sertifikat** (PNG): ism, ball, foiz, yakunlangan testda — egallagan o'rin.
- **Muallif paneli**: natijalar, Excel hisobot (reyting + har bir savol tahlili), kalit, ulashish, yakunlash, o'chirish.
- **Majburiy obuna**: bir yoki bir nechta kanal, admin paneldan boshqariladi.
- **Admin panel**: statistika, barchaga xabar tarqatish, kanallar, foydalanuvchini bloklash.
- **Nomaqbul ismlardan himoya** (uch qatlam):
  1. Avtomatik filtr: ism-familiya va test nomlarida so'kinish so'zlari (o'zbek, rus, ingliz; kirill/lotin, bo'shliq yoki belgi bilan yozilgani ham). Admin qo'shimcha so'z kirita oladi.
  2. Test muallifi: «👥 Ishtirokchilar» bo'limida istalgan ishtirokchini reytingdan chiqaradi yoki adminga shikoyat yuboradi.
  3. Admin: bloklash (barcha reytinglardan yo'qoladi) yoki ismini bekor qilish (qayta ro'yxatdan o'tadi).

## O'rnatish

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # so'ng .env ichiga BOT_TOKEN va ADMIN_IDS ni yozing
.venv\Scripts\python -m bot
```

1. Tokenni [@BotFather](https://t.me/BotFather) dan oling.
2. O'z ID raqamingizni `ADMIN_IDS` ga yozing (bir nechta bo'lsa vergul bilan).
3. Majburiy kanal qo'shish: botni kanalga **administrator** qiling → botda «🛠 Admin panel» → «📡 Majburiy kanallar» → «➕ Kanal qo'shish».

## Sinovlar

```powershell
.venv\Scripts\python -m tests.test_keyparser
.venv\Scripts\python -m tests.test_moderation
.venv\Scripts\python -m tests.test_flow
```

`test_flow` internet va tokensiz, soxta Telegram sessiyasi bilan to'liq ssenariyni tekshiradi.

## Tuzilishi

| Fayl | Vazifasi |
|---|---|
| `bot/keyparser.py` | Kalit va javoblarni o'qish, baholash |
| `bot/db.py` | SQLite (foydalanuvchilar, kanallar, testlar, natijalar) |
| `bot/middlewares.py`, `bot/subscription.py` | Ro'yxatga olish, bloklash, majburiy obuna |
| `bot/services.py` | Matnlar, testni yakunlash, muddat nazorati |
| `bot/moderation.py` | Nomaqbul so'zlar filtri |
| `bot/storage.py` | Yarim qolgan amallarni bazada saqlash |
| `bot/excel.py`, `bot/certificate.py` | Excel hisobot va sertifikat |
| `bot/handlers/` | start, create, solve, mytests, admin |

Ma'lumotlar `data/bot.db` faylida saqlanadi — uni vaqti-vaqti bilan zaxiralab turing.
Sertifikat shriftini almashtirish uchun `assets/fonts/regular.ttf` va `assets/fonts/bold.ttf` qo'ying.

## Render (bepul) + Neon'ga joylash

Bot ikki rejimda ishlaydi va o'zi aniqlaydi:

| | Mahalliy kompyuter | Render |
|---|---|---|
| Baza | SQLite (`data/bot.db`) | PostgreSQL — `DATABASE_URL` berilsa |
| Yangiliklar | polling | webhook — `RENDER_EXTERNAL_URL` mavjud bo'lsa |

### 1. Neon bazasi
1. [neon.tech](https://neon.tech) da ro'yxatdan o'ting → **New Project** (region: Render bilan bir xil, masalan Frankfurt).
2. **Connect** tugmasidan `postgresql://...` ko'rinishidagi manzilni nusxalang. Jadvallarni bot birinchi ishga tushganda o'zi yaratadi.

### 2. GitHub
Kodni GitHub'dagi (yopiq bo'lishi mumkin) repozitoriyga yuklang. `.env` fayli yuklanmaydi — token faqat Render sozlamalarida turadi.

### 3. Render
1. [render.com](https://render.com) → **New → Blueprint** → repozitoriyni tanlang (`render.yaml` avtomatik o'qiladi).
2. So'ralgan qiymatlarni kiriting: `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL` (Neon manzili).
3. Deploy tugagach log'da `Webhook rejimi: https://...onrender.com` yozuvi chiqadi — bot ishlayapti.

### 4. Uxlab qolmasligi uchun
Bepul Render xizmati 15 daqiqa so'rov kelmasa uxlaydi. Telegram xabari uni uyg'otadi, lekin birinchi javob ~1 daqiqa kechikadi va muddatli testlar uyg'ongandagina yakunlanadi. Buning oldini olish uchun [UptimeRobot](https://uptimerobot.com) yoki [cron-job.org](https://cron-job.org) da `https://<xizmat-nomi>.onrender.com/health` manzilini har 5–10 daqiqada tekshirib turadigan monitor yarating.

### Muhim
- **Bitta token — bitta joy.** Render'da ishlayotgan bot tokeni bilan kompyuterda `python -m bot` ishga tushirilsa, webhook o'chadi va Render'dagi bot javob bermay qoladi (qayta deploy qilguncha). Mahalliy sinov uchun @BotFather'dan alohida test-bot oching.
- Mahalliy SQLite'dagi ma'lumotlar Neon'ga avtomatik ko'chmaydi.
- PostgreSQL'da sinash: `TEST_DATABASE_URL=postgresql://... python -m tests.test_flow` (bo'sh baza kerak).
