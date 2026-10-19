from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GIFTTAX_", frozen=True)

    database_path: Path = Path("/tmp/gifttax/feedback.sqlite3")
    retention_interval_seconds: int = Field(default=86400, ge=60)

    @field_validator("database_path")
    @classmethod
    def require_absolute_database_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("database_path must be an absolute file path")
        return value
