from functools import lru_cache
from urllib.parse import urlsplit

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

    # --- object storage (S3-compatible, e.g. Filebase) ---
    # `s3_url` is the public read base, e.g.
    # https://cheerful-aquamarine-deer.s3.filebase.io
    s3_url: str | None = None
    s3_endpoint_url: str = "https://s3.filebase.io"
    # Derived from `s3_url` when unset.
    s3_bucket: str | None = None
    region: str = "auto"
    signature_version: str = "v4"
    s3_access_token: str | None = None
    s3_secret_key: str | None = None
    # Folder inside the bucket that every object is written under.
    s3_prefix: str = "auction"
    s3_max_image_bytes: int = 5 * 1024 * 1024
    # Filebase only serves buckets publicly on a paid plan. While this is
    # False, responses carry a time-limited presigned URL instead.
    s3_public_read: bool = False
    s3_presign_ttl_seconds: int = 3600

    @property
    def s3_public_base(self) -> str:
        """Public base URL without a trailing slash."""
        return (self.s3_url or "").rstrip("/")

    @property
    def s3_resolved_bucket(self) -> str:
        """Bucket name, taken from `s3_url`'s host when not set explicitly.

        ``https://cheerful-aquamarine-deer.s3.filebase.io`` -> ``cheerful-aquamarine-deer``
        """
        if self.s3_bucket:
            return self.s3_bucket
        if not self.s3_url:
            return ""
        host = urlsplit(self.s3_url).netloc
        return host.split(".")[0] if host else ""

    @property
    def storage_configured(self) -> bool:
        """True when every value needed to write an object is present."""
        return bool(
            self.s3_public_base
            and self.s3_resolved_bucket
            and self.s3_access_token
            and self.s3_secret_key
        )

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
