from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "data-api"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    environment: str = "local"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/data_api"
    pii_database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/pii_mapping"
    )

    jwt_secret_key: SecretStr = Field(
        default=SecretStr("change-me-in-production-use-a-real-secret"),
        min_length=32,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 60 * 24 * 7

    password_bcrypt_rounds: int = 12

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8000"]
    log_level: str = "INFO"
    log_format: str = "text"
    log_file_path: str | None = "/var/log/data-api/data-api.log"
    log_file_max_mb: int = Field(default=10, gt=0)
    log_file_backup_count: int = Field(default=5, ge=0)

    metrics_enabled: bool = True
    metrics_host: str = "127.0.0.1"
    metrics_port: int = Field(default=9000, ge=1, le=65535)

    trino_host: str = "localhost"
    trino_port: int = 8080
    trino_user: str = "data-api"
    trino_password: SecretStr | None = None
    trino_http_scheme: str = "http"

    pii_mapping_missing_ttl_seconds: float = Field(default=60.0, gt=0)
    pii_mapping_snapshot_batch_size: int = Field(default=500, gt=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
