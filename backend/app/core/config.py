from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_database_url(url: str) -> str:
    """Convert a raw postgres/sqlite URL into the async-driver form SQLAlchemy needs.

    Accepts Neon-console-style URLs as-is, e.g.
      postgresql://user:pass@host/db?sslmode=require&channel_binding=require
    and rewrites the scheme to use asyncpg. Query params unrelated to asyncpg
    (sslmode, channel_binding) are stripped since asyncpg takes ssl via connect_args.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
        # strip query string; asyncpg ssl is handled via connect_args in db/session.py
        url = re.sub(r"\?.*$", "", url)
    elif url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
        url = "sqlite+aiosqlite://" + url[len("sqlite://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "AI-Native BI Platform"
    ENV: Literal["dev", "test", "prod"] = "dev"
    DEBUG: bool = True

    DATABASE_URL: str = "sqlite+aiosqlite:///./bi_platform.db"
    DATABASE_URL_READONLY: str | None = None

    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4.1"
    OPENAI_IMAGE_MODEL: str = "gpt-image-2"

    SEED_SIZE: Literal["small", "medium", "large"] = "medium"
    AUTO_SEED_ON_BOOT: bool = True

    SQL_QUERY_TIMEOUT_MS: int = 8000
    SQL_MAX_ROWS: int = 5000
    SQL_MAX_RETRY: int = 2

    JOB_TTL_SECONDS: int = 3600

    CORS_ORIGINS: str = "http://localhost:3000"

    FRONTEND_PROXY_URL: str | None = None

    @property
    def database_url_effective(self) -> str:
        return _normalize_database_url(self.DATABASE_URL)

    @property
    def database_url_readonly_effective(self) -> str:
        if self.DATABASE_URL_READONLY:
            return _normalize_database_url(self.DATABASE_URL_READONLY)
        return self.database_url_effective

    @property
    def is_sqlite(self) -> bool:
        return self.database_url_effective.startswith("sqlite")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
