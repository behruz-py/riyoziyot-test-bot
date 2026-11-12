import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

# Bosh adminlar (.env / Render): bot ichidan o'chirib bo'lmaydi, faqat ular boshqa adminlarni boshqaradi
SUPER_ADMIN_IDS: frozenset[int] = frozenset(
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()
)
# Barcha adminlar: bosh adminlar + bot ichidan qo'shilganlar (bazadan yuklanadi, admins.py ga qarang)
ADMIN_IDS: set[int] = set(SUPER_ADMIN_IDS)

_db_path = Path(os.getenv("DB_PATH", "data/bot.db"))
DB_PATH: Path = _db_path if _db_path.is_absolute() else BASE_DIR / _db_path

# PostgreSQL manzili (Neon). Bo'sh bo'lsa mahalliy SQLite fayli (DB_PATH) ishlatiladi
DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()

# Webhook rejimi (server). Render RENDER_EXTERNAL_URL va PORT ni o'zi beradi.
# Bo'sh bo'lsa bot polling rejimida ishlaydi (mahalliy kompyuter uchun).
WEBHOOK_URL: str = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
PORT: int = int(os.getenv("PORT", "8080"))

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))

# Adminlarga kunlik hisobot va zaxira nusxa yuboriladigan soat (mahalliy vaqt, 0-23). -1 - o'chirilgan
DAILY_HOUR: int = int(os.getenv("DAILY_HOUR", "21"))

# Xatolar haqida bosh adminlarga xabar yuborish (1 - yoqilgan, 0 - o'chirilgan)
ERROR_ALERTS: bool = os.getenv("ERROR_ALERTS", "1").strip() not in ("0", "false", "no", "")

# Spamdan himoya: PERIOD soniyada LIMIT dan ko'p xabar/tugma - foydalanuvchi vaqtincha to'xtatiladi
FLOOD_LIMIT: int = int(os.getenv("FLOOD_LIMIT", "12"))
FLOOD_PERIOD: float = float(os.getenv("FLOOD_PERIOD", "6"))

# Cheklovlar
MAX_QUESTIONS = 200
MAX_OPEN_ANSWER_LEN = 60
MAX_TITLE_LEN = 100
SUB_CACHE_TTL = 120  # obuna tekshiruvi natijasi necha soniya keshlanadi


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
