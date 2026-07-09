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


@lru_cache()
def get_settings() -> Settings:
    return Settings()
