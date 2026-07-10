from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

_ROOT_ENV = str(Path(__file__).resolve().parents[3] / ".env")
_BACKEND_ENV = str(Path(__file__).resolve().parents[1] / ".env")

load_dotenv(_ROOT_ENV, override=False)
load_dotenv(_BACKEND_ENV, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[_ROOT_ENV, _BACKEND_ENV],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "TradingAgents API"
    VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    DATABASE_URL: str = "sqlite:///./tradingagents_web.db"

    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # SMTP email configuration
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USE_SSL: bool = True
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "TradingAgents"
    SMTP_FROM_EMAIL: str = ""

    # Email verification code configuration
    VERIFY_CODE_LENGTH: int = 6
    VERIFY_CODE_EXPIRE_MINUTES: int = 10
    VERIFY_CODE_RESEND_SECONDS: int = 60
    VERIFY_CODE_MAX_ATTEMPTS: int = 5

    # Admin & access control configuration
    # ACCESS_MODE: open = all non-blacklisted users can log in; whitelist = only whitelisted users can log in
    ACCESS_MODE: str = "open"
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""


@lru_cache()
def get_settings() -> Settings:
    return Settings()
