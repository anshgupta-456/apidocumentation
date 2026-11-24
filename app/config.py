"""Central application settings, loaded from environment variables / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _env_list(name: str, default: str) -> tuple:
    raw = os.getenv(name)
    if raw is None:
        raw = default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip() or "sqlite:///./api_validator.db"
    # Render / Heroku / Railway hand out "postgres://" URLs, which SQLAlchemy 2 rejects.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


class Settings:
    APP_NAME: str = "API Contract Validator"
    VERSION: str = "2.1.0"

    # Database: PostgreSQL in production, SQLite fallback for local dev / tests.
    DATABASE_URL: str = _database_url()

    # Authentication. Leave ADMIN_PASSWORD empty to disable login (local development).
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "").strip()
    SECRET_KEY: str = os.getenv("SECRET_KEY", "").strip()
    SESSION_HOURS: int = _env_int("SESSION_HOURS", 24 * 7)

    # AI (optional). Without a key the system uses the built-in rule-based engine.
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
    AI_MODEL: str = os.getenv("AI_MODEL", "llama-3.1-8b-instant")
    AI_ENABLED: bool = _env_bool("AI_ENABLED", True)
    AI_TIMEOUT_SECONDS: float = float(os.getenv("AI_TIMEOUT_SECONDS", "20"))

    # Traffic capture: only paths starting with these prefixes are logged.
    LOG_INCLUDE_PREFIXES: tuple = _env_list("LOG_INCLUDE_PREFIXES", "/api/")
    LOG_MAX_BODY_BYTES: int = _env_int("LOG_MAX_BODY_BYTES", 64 * 1024)
    # Values of these JSON keys are masked before logs are stored (type is preserved).
    REDACT_FIELDS: tuple = tuple(
        f.lower()
        for f in _env_list(
            "REDACT_FIELDS",
            "password,passwd,secret,token,access_token,refresh_token,api_key,apikey,authorization,"
            "credit_card,card_number,cvv,ssn",
        )
    )
    LOG_RETENTION_DAYS: int = _env_int("LOG_RETENTION_DAYS", 30)  # 0 keeps logs forever

    # Schema inference uses the most recent N samples per endpoint.
    INFERENCE_SAMPLE_LIMIT: int = _env_int("INFERENCE_SAMPLE_LIMIT", 500)

    # Background drift scan every N minutes (0 = off).
    AUTO_SCAN_INTERVAL_MINUTES: int = _env_int("AUTO_SCAN_INTERVAL_MINUTES", 0)

    # Alerts: Slack / Discord / generic JSON webhook for new drift events.
    ALERT_WEBHOOK_URL: str = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    ALERT_MIN_SEVERITY: str = os.getenv("ALERT_MIN_SEVERITY", "high").strip().lower() or "high"
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

    DEMO_ENABLED: bool = _env_bool("DEMO_ENABLED", True)
    GENERATED_SPEC_PATH: str = os.getenv("GENERATED_SPEC_PATH", "openapi.generated.json")
    CORS_ORIGINS: tuple = _env_list("CORS_ORIGINS", "")

    @property
    def auth_enabled(self) -> bool:
        return bool(self.ADMIN_PASSWORD)

    @property
    def ai_available(self) -> bool:
        if not (self.AI_ENABLED and self.GROQ_API_KEY):
            return False
        try:
            import groq  # noqa: F401
        except ImportError:
            return False
        return True

    @property
    def database_backend(self) -> str:
        return self.DATABASE_URL.split(":", 1)[0].split("+", 1)[0]


settings = Settings()
