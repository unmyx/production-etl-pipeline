from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy import URL

load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    api_base_url: str
    api_page_size: int
    request_timeout: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_host=os.getenv("DB_HOST", "localhost"),
            db_port=_env_int("DB_PORT", 5432),
            db_name=os.getenv("DB_NAME", "etl_demo"),
            db_user=os.getenv("DB_USER", "etl_user"),
            db_password=os.getenv("DB_PASSWORD", "etl_password"),
            api_base_url=os.getenv("API_BASE_URL", "https://dummyjson.com"),
            api_page_size=_env_int("API_PAGE_SIZE", 30),
            request_timeout=_env_int("REQUEST_TIMEOUT", 30),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )
