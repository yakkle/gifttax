"""Admin JWTs, revocable sessions, CSRF proofs, and one-time manual login."""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

import jwt

from backend.settings import AdminSettings
from backend.storage.admin import AdminRecords, AdminRepository

SESSION_SECONDS = 8 * 60 * 60
LOGIN_TOKEN_SECONDS = 5 * 60


class AdminAuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    created_at: int
    expires_at: int


@dataclass(frozen=True)
class SessionGrant:
    token: str = field(repr=False)
    csrf_token: str
    expires_at: int


class AdminSessionService:
    def __init__(self, repository: AdminRepository, settings: AdminSettings) -> None:
        self.repository = repository
        self.settings = settings

    def _encode(self, purpose: str, now: int, expires_at: int, identifier: str) -> str:
        return jwt.encode(
            {
                "sub": "1",
                "iss": self.settings.canonical_origin,
                "aud": "gifttax-admin",
                "iat": now,
                "exp": expires_at,
                "jti": identifier,
                "token_use": purpose,
                "auth_mode": self.settings.mode,
            },
            self.settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        )

    def _decode(self, token: str | None, purpose: str) -> dict:
        try:
            claims = jwt.decode(
                token or "",
                self.settings.jwt_secret.get_secret_value(),
                algorithms=["HS256"],
                audience="gifttax-admin",
                issuer=self.settings.canonical_origin,
                options={
                    "require": ["sub", "iss", "aud", "iat", "exp", "jti", "token_use", "auth_mode"]
                },
            )
            if (
                claims["sub"] != "1"
                or claims["token_use"] != purpose
                or claims["auth_mode"] != self.settings.mode
                or not isinstance(claims["jti"], str)
                or not 1 <= len(claims["jti"]) <= 128
            ):
                raise ValueError("Unexpected token claims")
            return claims
        except (jwt.InvalidTokenError, ValueError, TypeError) as error:
            raise AdminAuthError(
                "UNAUTHENTICATED", "인증이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요."
            ) from error

    def csrf_token(self, session_id: str) -> str:
        return hmac.new(
            self.settings.jwt_secret.get_secret_value().encode(),
            f"csrf:{session_id}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def require_session(self, records: AdminRecords, token: str | None, now: int) -> SessionInfo:
        claims = self._decode(token, "session")
        record = records.login_session(claims["jti"], now)
        if record is None or records.account() is None:
            raise AdminAuthError("UNAUTHENTICATED", "로그인이 필요합니다.")
        return SessionInfo(record.session_id, record.created_at, record.expires_at)

    def verify_csrf(self, session: SessionInfo, csrf: str | None) -> None:
        if not hmac.compare_digest(
            self.csrf_token(session.session_id).encode(), (csrf or "").encode()
        ):
            raise AdminAuthError(
                "FORBIDDEN", "요청을 확인할 수 없습니다. 화면을 새로고침해 주세요."
            )

    def create_session(
        self, records: AdminRecords, now: int, previous_id: str | None = None
    ) -> SessionGrant:
        identifier = secrets.token_urlsafe(32)
        expires_at = now + SESSION_SECONDS
        if previous_id:
            records.delete_session(previous_id)
        records.add_session(identifier, now, expires_at)
        return SessionGrant(
            self._encode("session", now, expires_at, identifier),
            self.csrf_token(identifier),
            expires_at,
        )

    def authenticate(self, token: str | None) -> SessionInfo:
        with self.repository.transaction(write=False) as records:
            return self.require_session(records, token, int(time.time()))

    def logout(self, token: str | None, csrf: str | None) -> None:
        with self.repository.transaction() as records:
            session = self.require_session(records, token, int(time.time()))
            self.verify_csrf(session, csrf)
            records.delete_session(session.session_id)

    def issue_login_token(self) -> str:
        if self.settings.mode != "manual_jwt":
            raise AdminAuthError("FORBIDDEN", "수동 JWT 인증 모드에서만 발급할 수 있습니다.")
        now = int(time.time())
        token = self._encode("login", now, now + LOGIN_TOKEN_SECONDS, secrets.token_urlsafe(32))
        with self.repository.transaction() as records:
            if records.account() is None:
                records.create_account(secrets.token_bytes(32), now)
            records.delete_tokens("login")
            records.add_token(token_hash(token), "login", now, now + LOGIN_TOKEN_SECONDS)
        return token

    def exchange_login_token(self, token: str) -> SessionGrant:
        if self.settings.mode != "manual_jwt":
            raise AdminAuthError(
                "FORBIDDEN", "패스키 인증 모드에서는 수동 토큰을 사용할 수 없습니다."
            )
        self._decode(token, "login")
        now = int(time.time())
        with self.repository.transaction() as records:
            record = records.token(token_hash(token), "login", now)
            if record is None or records.account() is None:
                raise AdminAuthError(
                    "UNAUTHENTICATED", "로그인 토큰이 만료되었거나 이미 사용되었습니다."
                )
            records.delete_token(record)
            return self.create_session(records, now)
