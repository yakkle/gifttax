from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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


class AdminSettings(BaseSettings):
    """Validated only at the admin boundary; missing settings leave public APIs available."""

    model_config = SettingsConfigDict(env_prefix="GIFTTAX_ADMIN_", frozen=True)

    mode: Literal["webauthn", "manual_jwt"] = "webauthn"
    origin: str = ""
    rp_id: str = ""
    jwt_secret: SecretStr = SecretStr("")
    allow_insecure_localhost: bool = False

    @field_validator("origin", "rp_id")
    @classmethod
    def strip_setting(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_admin_settings(self) -> Self:
        parsed = urlsplit(self.origin)
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or any(ord(char) <= 32 or ord(char) >= 127 for char in self.origin)
        ):
            raise ValueError("A single valid admin origin is required")
        # Accessing port also rejects malformed port numbers.
        _ = parsed.port
        if parsed.scheme != "https" and not self.is_local_http:
            raise ValueError("Admin origin must use HTTPS")
        if self.mode == "webauthn" and self.rp_id.lower() != parsed.hostname:
            raise ValueError("RP ID must match the admin origin hostname")
        if len(self.jwt_secret.get_secret_value().encode()) < 32:
            raise ValueError("Admin JWT secret must contain at least 32 bytes")
        return self

    @property
    def is_local_http(self) -> bool:
        parsed = urlsplit(self.origin)
        return (
            self.allow_insecure_localhost
            and parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )

    @property
    def canonical_origin(self) -> str:
        parsed = urlsplit(self.origin)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        default_port = 443 if parsed.scheme == "https" else 80
        port = f":{parsed.port}" if parsed.port not in (None, default_port) else ""
        return f"{parsed.scheme}://{host}{port}"

    @property
    def session_cookie_name(self) -> str:
        prefix = "" if self.is_local_http else "__Host-"
        return f"{prefix}gifttax-admin-session"

    @property
    def flow_cookie_name(self) -> str:
        prefix = "" if self.is_local_http else "__Host-"
        return f"{prefix}gifttax-admin-flow"
