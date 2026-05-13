import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = BASE_DIR / "media"

# Создаём директории при импорте
DATA_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# На Render используем 0.0.0.0 и порт из переменной PORT
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "8000")))
DATABASE_PATH = os.getenv("DATABASE_PATH", str(DATA_DIR / "antidrug.db"))
MEDIA_PATH = os.getenv("MEDIA_PATH", str(MEDIA_DIR))
SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret_key_change_in_production")

# Прокси для Telegram (если нужен)
# Формат: http://user:pass@proxy:port или socks5://user:pass@proxy:port
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", None)

# VK Bot
VK_TOKEN = os.getenv("VK_TOKEN", "")
VK_GROUP_ID = int(os.getenv("VK_GROUP_ID", "0"))
# Публичная ссылка на сообщество (кнопка на лендинге, футер)
VK_GROUP_PUBLIC_URL = os.getenv("VK_GROUP_PUBLIC_URL", "").strip().rstrip("/")

# Продакшен-URL сайта без завершающего слэша (для ссылок из VK/Telegram; иначе http://HOST:PORT)
_raw_pub = os.getenv("PUBLIC_SITE_URL", "").strip().rstrip("/")
PUBLIC_SITE_URL = _raw_pub or ""


def get_public_site_origin() -> str:
    """Базовый URL сайта для внешних ссылок (карта, боты)."""
    if PUBLIC_SITE_URL:
        return PUBLIC_SITE_URL
    return f"http://{WEB_HOST}:{WEB_PORT}"

# Статусы заявок
STATUS_NEW = "new"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_REJECTED = "rejected"

STATUS_LABELS = {
    STATUS_NEW: "🆕 Новая",
    STATUS_IN_PROGRESS: "⏳ В работе",
    STATUS_COMPLETED: "✅ Завершена",
    STATUS_REJECTED: "❌ Отклонена",
}
