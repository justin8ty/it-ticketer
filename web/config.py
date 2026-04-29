import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None


ROOT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
LOCAL_ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


if load_dotenv is not None:
    load_dotenv(ROOT_ENV_FILE, override=False)
    load_dotenv(LOCAL_ENV_FILE, override=False)
else:
    _load_env_file(ROOT_ENV_FILE)
    _load_env_file(LOCAL_ENV_FILE)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


APP_PORT = int(os.getenv("APP_PORT", "8080"))
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip().rstrip("/")

DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "ticketdb")
DB_USER = os.getenv("DB_USER", "ticketuser")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ticketpass")

# Automated assessment service (Gemini)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
HEALTH_AI_ENABLED = _env_bool("HEALTH_AI_ENABLED", True)
_HEALTH_AI_QUESTION_COUNT = os.getenv("HEALTH_AI_QUESTION_COUNT", "5").strip()
try:
    HEALTH_AI_QUESTION_COUNT = max(3, min(10, int(_HEALTH_AI_QUESTION_COUNT)))
except ValueError:
    HEALTH_AI_QUESTION_COUNT = 5

NOTIFY_EMAIL_ENABLED = _env_bool("NOTIFY_EMAIL_ENABLED", False)
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", True)
SMTP_USE_SSL = _env_bool("SMTP_USE_SSL", False)
SMTP_TIMEOUT = float(os.getenv("SMTP_TIMEOUT", "10"))

NOTIFY_TELEGRAM_ENABLED = _env_bool("NOTIFY_TELEGRAM_ENABLED", False)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

NOTIFICATION_PREFERENCES = ["BOTH", "EMAIL", "TELEGRAM", "NONE"]

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SIGNATURE_DIR = UPLOAD_DIR / "signatures"
SIGNATURE_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = ["Network", "Hardware", "Software", "Printer", "Account", "Other"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["NEW", "IN_PROGRESS", "PENDING_CONFIRMATION", "CLOSED", "REOPENED"]
