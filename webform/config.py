"""All settings come from environment variables (the server's .env file). See .env.example."""
import base64
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing setting {name}. Add it to the server's .env (see .env.example).")
    return value


def _key(name):
    raw = base64.b64decode(_required(name))
    if len(raw) != 32:
        raise RuntimeError(f"{name} must be 32 random bytes, base64-encoded (run: python manage.py genkeys).")
    return raw


APP_ENV = os.environ.get("APP_ENV", "production")
IS_DEV = APP_ENV == "development"

DATABASE_URL = _required("DATABASE_URL")
SECRET_KEY = _required("SECRET_KEY")

# Envelope encryption: MASTER_KEY_V<n> wraps per-lead data keys. Keep old versions after rotation.
KEK_VERSION = int(os.environ.get("KEK_VERSION", "1"))
MASTER_KEYS = {
    int(name.rsplit("_V", 1)[1]): _key(name)
    for name in os.environ if name.startswith("MASTER_KEY_V") and name.rsplit("_V", 1)[1].isdigit()
}
if KEK_VERSION not in MASTER_KEYS:
    raise RuntimeError(f"MASTER_KEY_V{KEK_VERSION} is not set (run: python manage.py genkeys).")
INDEX_KEY = _key("INDEX_KEY")

STORAGE_DIR = os.environ.get(
    "STORAGE_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "objects")
)
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
DEFAULT_PROGRAM_SLUG = os.environ.get("DEFAULT_PROGRAM_SLUG", "esaf-csp")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
# Dev-only sign-in without Google, accepted only from this machine and only when APP_ENV=development.
DEV_LOGIN_ENABLED = IS_DEV and os.environ.get("DEV_LOGIN", "") == "1"

SESSION_HOURS = int(os.environ.get("SESSION_HOURS", "8"))
SESSION_IDLE_MINUTES = int(os.environ.get("SESSION_IDLE_MINUTES", "30"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

CLAMAV_ENABLED = os.environ.get("CLAMAV_ENABLED", "") == "1"
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "15"))

CONSENT_NOTICE_VERSION = "v1-2026-11"
