"""Production configuration via environment variables with Pydantic v2."""

from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from cryptography.fernet import Fernet


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "YouTube-Instagram Bot"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    secret_key: str = Field(default="change-me-in-production", min_length=32)

    # ── Auth / session ────────────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440    # 24 hours
    jwt_refresh_token_expire_days:   int = 30       # 30 days
    # Default admin credentials — CHANGE IN PRODUCTION
    admin_username: str = "admin"
    admin_password_hash: str = ""    # bcrypt hash; empty = use default password
    admin_default_password: str = "BotPlatform@2024"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./bot.db"

    # ── Encryption ───────────────────────────────────────────────────────────
    bot_master_key: str = ""

    # ── API server ────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1
    cors_origins: list[str] = ["http://localhost:8080", "http://localhost:3000"]

    # ── Instagram credentials ─────────────────────────────────────────────────
    instagram_access_token: str = ""
    instagram_user_id: str = ""
    instagram_app_id: str = ""
    instagram_app_secret: str = ""

    # ── YouTube credentials (OAuth 2.0) ───────────────────────────────────────
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_channel_id: str = ""       # e.g. UCxxxxxx  (optional, auto-fetched)

    # ── Rate limits ───────────────────────────────────────────────────────────
    # Instagram
    instagram_requests_per_hour: int = 15
    instagram_follows_per_day: int = 150
    instagram_unfollows_per_day: int = 150
    instagram_likes_per_day: int = 300
    instagram_comments_per_day: int = 30
    instagram_min_delay_seconds: float = 90.0
    instagram_max_delay_seconds: float = 180.0
    # YouTube  — YouTube Data API v3 quota: 10,000 units/day
    # Upload   = 1,600 units  → safe max = 6 uploads/day
    # Like     = 50 units
    # Comment  = 50 units
    # Subscribe= 50 units
    youtube_requests_per_hour: int = 10
    youtube_uploads_per_day: int = 6
    youtube_likes_per_day: int = 50
    youtube_comments_per_day: int = 20
    youtube_subscribes_per_day: int = 30
    youtube_min_delay_seconds: float = 30.0
    youtube_max_delay_seconds: float = 90.0
    # Rumble
    rumble_requests_per_hour: int = 50

    # ── Retry ─────────────────────────────────────────────────────────────────
    retry_max_attempts: int = 3
    retry_initial_delay: float = 2.0
    retry_max_delay: float = 60.0

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler_check_interval_seconds: int = 60

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    # ── Feature flags ─────────────────────────────────────────────────────────
    youtube_enabled: bool = True
    instagram_enabled: bool = True
    rumble_enabled: bool = True

    @field_validator("bot_master_key", mode="before")
    @classmethod
    def ensure_master_key(cls, v: str) -> str:
        if not v:
            return Fernet.generate_key().decode()
        try:
            Fernet(v.encode() if isinstance(v, str) else v)
        except Exception as exc:
            raise ValueError(f"BOT_MASTER_KEY is not a valid Fernet key: {exc}") from exc
        return v

    @property
    def master_key_bytes(self) -> bytes:
        return self.bot_master_key.encode()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def instagram_configured(self) -> bool:
        return bool(self.instagram_access_token and self.instagram_user_id)

    @property
    def youtube_configured(self) -> bool:
        return bool(self.youtube_client_id and self.youtube_client_secret
                    and self.youtube_refresh_token)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

