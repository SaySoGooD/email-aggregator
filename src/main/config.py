from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Runtime configuration, overridable via .env or environment variables."""

    ACCOUNTS_FILE: str = "accounts.json"
    ACCOUNTS_ENC: str = "accounts.enc"
    DEFAULT_FETCH_LIMIT: int = 15
    MESSAGES_DB: str = "messages.db"
    SETTINGS_FILE: str = "display_settings.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
