from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegistrationStart(AdminRequest):
    registration_code: str | None = Field(default=None, min_length=1, max_length=256)


class RegistrationFinish(RegistrationStart):
    challenge_id: str = Field(min_length=1, max_length=128)
    credential: dict[str, Any]
    label: str = Field(default="패스키", min_length=1, max_length=80)


class AuthenticationFinish(AdminRequest):
    challenge_id: str = Field(min_length=1, max_length=128)
    credential: dict[str, Any]


class LoginTokenInput(AdminRequest):
    token: str = Field(min_length=1, max_length=4096)


class SessionStatus(BaseModel):
    csrf_token: str
    expires_at: int


class AdminConfig(BaseModel):
    mode: Literal["webauthn", "manual_jwt"]
    has_passkey: bool


class WebAuthnOptions(BaseModel):
    challenge_id: str
    options: dict[str, Any]


class CredentialSummary(BaseModel):
    id: str
    label: str
    created_at: int
    last_used_at: int | None
    can_delete: bool
