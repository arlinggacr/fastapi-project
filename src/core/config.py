from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---
    app_name: str = "Auction API"
    debug: bool = False
    enable_docs: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # --- database ---
    db_url: str = ""
    db_echo: bool = False

    # --- redis ---
    # Preferred: native TCP/TLS endpoint (rediss://default:pass@host:6379).
    # Enables real pub/sub push. Falls back to Upstash REST when absent.
    redis_url: str | None = None
    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: str | None = None
    key_prefix: str = "auction"
    # Polling interval (seconds) used only in REST fallback mode.
    rest_poll_interval: float = 0.5

    # --- auth ---
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7

    # --- auction rules ---
    # Anti-sniping: a bid inside the last `extension_window_seconds`
    # pushes the end time out by `extension_seconds`.
    extension_seconds: int = 60
    extension_window_seconds: int = 60
    scheduler_interval: float = 1.0

    @property
    def sqlalchemy_url(self) -> str:
        url = self.db_url
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://") :]
        elif url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://") :]
        return url

    @property
    def redis_mode(self) -> str:
        if self.redis_url:
            return "pubsub"
        if self.upstash_redis_rest_url and self.upstash_redis_rest_token:
            return "rest"
        return "none"


@lru_cache
def get_settings() -> Settings:
    return Settings()
