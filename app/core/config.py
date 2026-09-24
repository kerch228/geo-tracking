from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    app_name: str = "Geo-Tracking Service"
    debug: bool = False

    postgres_user: str = "postgres"
    postgres_password: SecretStr
    postgres_db: str = "geotracking"
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)

    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0)
    db_pool_recycle_seconds: int = Field(default=1800, ge=1)
    db_connect_max_attempts: int = Field(default=10, ge=1)
    db_connect_retry_seconds: float = Field(default=2.0, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
