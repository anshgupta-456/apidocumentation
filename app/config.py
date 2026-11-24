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


def _env_list(name: str, default: str) -> tuple:
    raw = os.getenv(name)
    if raw is None:
        raw = default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


class Settings:
    APP_NAME: str = "API Contract Validator"
    VERSION: str = "2.0.0"

    # Database: PostgreSQL in production, SQLite fallback for local dev / tests.
    DATABASE_URL: str = os.getenv("DATABASE_URL") or "sqlite:///./api_validator.db"

    # AI (optional). Without a key the system uses the built-in rule-based engine.
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
    AI_MODEL: str = os.getenv("AI_MODEL", "llama-3.1-8b-instant")
    AI_ENABLED: bool = _env_bool("AI_ENABLED", True)
    AI_TIMEOUT_SECONDS: float = float(os.getenv("AI_TIMEOUT_SECONDS", "20"))

    # Traffic capture: only paths starting with these prefixes are logged.
    LOG_INCLUDE_PREFIXES: tuple = _env_list("LOG_INCLUDE_PREFIXES", "/api/")
    LOG_MAX_BODY_BYTES: int = int(os.getenv("LOG_MAX_BODY_BYTES", str(64 * 1024)))

    # Schema inference uses the most recent N samples per endpoint.
    INFERENCE_SAMPLE_LIMIT: int = int(os.getenv("INFERENCE_SAMPLE_LIMIT", "500"))

    GENERATED_SPEC_PATH: str = os.getenv("GENERATED_SPEC_PATH", "openapi.generated.json")

    CORS_ORIGINS: tuple = _env_list("CORS_ORIGINS", "")

    @property
    def ai_available(self) -> bool:
        if not (self.AI_ENABLED and self.GROQ_API_KEY):
            return False
        try:
            import groq  # noqa: F401
        except ImportError:
            return False
        return True


settings = Settings()
