"""Passwordless enrollment, authentication, credential management, and recovery."""

import hmac
import json
import secrets
import time
from dataclasses import dataclass, field

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url, options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.parse_authentication_credential_json import (
    parse_authentication_credential_json,
)
from webauthn.helpers.parse_registration_credential_json import parse_registration_credential_json
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from backend.schemas.admin import CredentialSummary
from backend.services.admin_sessions import (
    AdminAuthError,
    AdminSessionService,
    SessionGrant,
    token_hash,
)
from backend.settings import AdminSettings
from backend.storage.admin import AdminRecords, AdminRepository

REGISTRATION_CODE_SECONDS = 10 * 60
CHALLENGE_SECONDS = 5 * 60


def reset_admin_auth(repository: AdminRepository) -> None:
    """Server recovery must remain available even with missing auth settings."""
    with repository.transaction() as records:
        records.reset()


def require_same_origin_client_data(value: bytes) -> None:
    data = json.loads(value)
    if not isinstance(data, dict) or data.get("crossOrigin", False) is not False:
        raise ValueError("Cross-origin WebAuthn is not allowed")


@dataclass(frozen=True)
class CeremonyOptions:
    challenge_id: str
    options: dict
    flow_token: str = field(repr=False)


@dataclass(frozen=True)
class RegistrationAuthority:
    user_handle: bytes
    binding: str
    session_id: str | None


class AdminAuthService:
    def __init__(self, repository: AdminRepository, settings: AdminSettings) -> None:
        self.repository = repository
        self.settings = settings
        self.sessions = AdminSessionService(repository, settings)

    def _require_webauthn(self) -> None:
        if self.settings.mode != "webauthn":
            raise AdminAuthError("FORBIDDEN", "현재 인증 모드에서는 패스키를 사용할 수 없습니다.")

    def has_credentials(self) -> bool:
        with self.repository.transaction(write=False) as records:
            return records.credential_count() > 0

    def issue_registration_code(self) -> str:
        self._require_webauthn()
        now, code = int(time.time()), secrets.token_urlsafe(32)
        with self.repository.transaction() as records:
            if records.credential_count():
                raise AdminAuthError(
                    "CONFLICT",
                    "이미 패스키가 등록되어 있습니다. 로그인하거나 인증 복구 명령을 사용해 주세요.",
                )
            if records.account() is None:
                records.create_account(secrets.token_bytes(32), now)
            records.delete_tokens("registration")
            records.add_token(
                token_hash(code), "registration", now, now + REGISTRATION_CODE_SECONDS
            )
        return code

    def _registration_authority(
        self,
        records: AdminRecords,
        code: str | None,
        session_token: str | None,
        csrf: str | None,
        now: int,
    ) -> RegistrationAuthority:
        account = records.account()
        if code is not None:
            if (
                records.token(token_hash(code), "registration", now) is None
                or records.credential_count()
            ):
                raise AdminAuthError(
                    "UNAUTHENTICATED", "등록 코드가 만료되었거나 유효하지 않습니다."
                )
            session_id = None
            binding = f"setup:{token_hash(code)}"
        else:
            session = self.sessions.require_session(records, session_token, now)
            self.sessions.verify_csrf(session, csrf)
            session_id = session.session_id
            binding = f"session:{session_id}"
        if account is None:
            raise AdminAuthError("UNAUTHENTICATED", "서버에서 최초 등록 코드를 발급해 주세요.")
        return RegistrationAuthority(account.user_handle, binding, session_id)

    def _create_challenge(
        self, records: AdminRecords, purpose: str, binding: str, now: int
    ) -> tuple[str, bytes, str]:
        identifier, challenge, flow = (
            secrets.token_urlsafe(32),
            secrets.token_bytes(32),
            secrets.token_urlsafe(32),
        )
        records.add_challenge(
            challenge_id=identifier,
            challenge=challenge,
            purpose=purpose,
            binding_hash=token_hash(f"{binding}:{flow}"),
            created_at=now,
            expires_at=now + CHALLENGE_SECONDS,
        )
        return identifier, challenge, flow

    def _consume_challenge(
        self,
        records: AdminRecords,
        identifier: str,
        purpose: str,
        binding: str,
        flow: str | None,
        now: int,
    ) -> bytes:
        challenge = records.challenge(identifier, purpose, now)
        if (
            challenge is None
            or not flow
            or not hmac.compare_digest(challenge.binding_hash, token_hash(f"{binding}:{flow}"))
        ):
            raise AdminAuthError(
                "UNAUTHENTICATED",
                "인증 요청이 만료되었거나 이미 사용되었습니다. 다시 시작해 주세요.",
            )
        value = challenge.challenge
        records.delete_challenge(challenge)
        return value

    def registration_options(
        self, code: str | None, session_token: str | None, csrf: str | None
    ) -> CeremonyOptions:
        self._require_webauthn()
        now = int(time.time())
        with self.repository.transaction() as records:
            authority = self._registration_authority(records, code, session_token, csrf, now)
            identifier, challenge, flow = self._create_challenge(
                records, "registration", authority.binding, now
            )
            options = generate_registration_options(
                rp_id=self.settings.rp_id.lower(),
                rp_name="GiftTax 관리자",
                user_id=authority.user_handle,
                user_name="GiftTax 관리자",
                challenge=challenge,
                timeout=CHALLENGE_SECONDS * 1000,
                authenticator_selection=AuthenticatorSelectionCriteria(
                    resident_key=ResidentKeyRequirement.PREFERRED,
                    user_verification=UserVerificationRequirement.REQUIRED,
                ),
                exclude_credentials=[
                    PublicKeyCredentialDescriptor(id=row.credential_id)
                    for row in records.credentials()
                ],
            )
            return CeremonyOptions(identifier, json.loads(options_to_json(options)), flow)

    def register(
        self,
        identifier: str,
        credential: dict,
        label: str,
        flow: str | None,
        code: str | None,
        session_token: str | None,
        csrf: str | None,
    ) -> SessionGrant:
        self._require_webauthn()
        label = label.strip()
        if not 1 <= len(label) <= 80:
            raise AdminAuthError("INVALID_REQUEST", "패스키 이름은 1~80자로 입력해 주세요.")
        with self.repository.transaction() as records:
            authority = self._registration_authority(
                records, code, session_token, csrf, int(time.time())
            )
            challenge = self._consume_challenge(
                records, identifier, "registration", authority.binding, flow, int(time.time())
            )
        # A bound challenge is consumed even when cryptographic verification fails.
        try:
            parsed = parse_registration_credential_json(credential)
            require_same_origin_client_data(parsed.response.client_data_json)
            verified = verify_registration_response(
                credential=parsed,
                expected_challenge=challenge,
                expected_rp_id=self.settings.rp_id.lower(),
                expected_origin=self.settings.canonical_origin,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError) as error:
            raise AdminAuthError(
                "UNAUTHENTICATED", "패스키 등록을 확인할 수 없습니다. 다시 시작해 주세요."
            ) from error
        now = int(time.time())
        with self.repository.transaction() as records:
            current = self._registration_authority(records, code, session_token, csrf, now)
            if current != authority:
                raise AdminAuthError(
                    "UNAUTHENTICATED", "관리자 인증 상태가 변경되었습니다. 다시 시작해 주세요."
                )
            if records.credential(verified.credential_id) is not None:
                raise AdminAuthError("CONFLICT", "이미 등록된 패스키입니다.")
            records.add_credential(
                credential_id=verified.credential_id,
                public_key=verified.credential_public_key,
                sign_count=verified.sign_count,
                transports_json=json.dumps(
                    [value.value for value in (parsed.response.transports or [])]
                ),
                label=label,
                created_at=now,
            )
            if code is not None:
                records.delete_tokens("registration")
            return self.sessions.create_session(records, now, previous_id=authority.session_id)

    def authentication_options(self) -> CeremonyOptions:
        self._require_webauthn()
        with self.repository.transaction() as records:
            credentials = records.credentials()
            if not credentials:
                raise AdminAuthError(
                    "CONFLICT", "먼저 서버에서 등록 코드를 발급하고 패스키를 등록해 주세요."
                )
            identifier, challenge, flow = self._create_challenge(
                records, "authentication", "login", int(time.time())
            )
            options = generate_authentication_options(
                rp_id=self.settings.rp_id.lower(),
                challenge=challenge,
                timeout=CHALLENGE_SECONDS * 1000,
                allow_credentials=[
                    PublicKeyCredentialDescriptor(id=row.credential_id) for row in credentials
                ],
                user_verification=UserVerificationRequirement.REQUIRED,
            )
            return CeremonyOptions(identifier, json.loads(options_to_json(options)), flow)

    def authenticate(self, identifier: str, credential: dict, flow: str | None) -> SessionGrant:
        self._require_webauthn()
        with self.repository.transaction() as records:
            challenge = self._consume_challenge(
                records, identifier, "authentication", "login", flow, int(time.time())
            )
            account = records.account()
            if account is None:
                raise AdminAuthError("UNAUTHENTICATED", "패스키 인증을 다시 시작해 주세요.")
            user_handle = account.user_handle
        try:
            parsed = parse_authentication_credential_json(credential)
            require_same_origin_client_data(parsed.response.client_data_json)
            with self.repository.transaction() as records:
                account, key = records.account(), records.credential(parsed.raw_id)
                if account is None or account.user_handle != user_handle or key is None:
                    raise AdminAuthError("UNAUTHENTICATED", "등록된 패스키로 다시 로그인해 주세요.")
                if (
                    parsed.response.user_handle is not None
                    and parsed.response.user_handle != user_handle
                ):
                    raise AdminAuthError(
                        "UNAUTHENTICATED", "등록된 관리자 계정과 일치하지 않습니다."
                    )
                verified = verify_authentication_response(
                    credential=parsed,
                    expected_challenge=challenge,
                    expected_rp_id=self.settings.rp_id.lower(),
                    expected_origin=self.settings.canonical_origin,
                    credential_public_key=key.public_key,
                    credential_current_sign_count=key.sign_count,
                    require_user_verification=True,
                )
                now = int(time.time())
                key.sign_count, key.last_used_at = verified.new_sign_count, now
                return self.sessions.create_session(records, now)
        except (WebAuthnException, ValueError, TypeError, KeyError) as error:
            raise AdminAuthError(
                "UNAUTHENTICATED", "패스키 인증을 확인할 수 없습니다. 다시 시작해 주세요."
            ) from error

    def list_credentials(self, token: str | None) -> list[CredentialSummary]:
        with self.repository.transaction(write=False) as records:
            self.sessions.require_session(records, token, int(time.time()))
            credentials = records.credentials()
            return [
                CredentialSummary(
                    id=bytes_to_base64url(row.credential_id),
                    label=row.label,
                    created_at=row.created_at,
                    last_used_at=row.last_used_at,
                    can_delete=len(credentials) > 1,
                )
                for row in credentials
            ]

    def delete_credential(self, identifier: str, token: str | None, csrf: str | None) -> None:
        from webauthn.helpers import base64url_to_bytes

        self._require_webauthn()
        try:
            credential_id = base64url_to_bytes(identifier)
        except (ValueError, TypeError) as error:
            raise AdminAuthError("NOT_FOUND", "패스키를 찾을 수 없습니다.") from error
        with self.repository.transaction() as records:
            session = self.sessions.require_session(records, token, int(time.time()))
            self.sessions.verify_csrf(session, csrf)
            credential = records.credential(credential_id)
            if credential is None:
                raise AdminAuthError("NOT_FOUND", "패스키를 찾을 수 없습니다.")
            if records.credential_count() <= 1:
                raise AdminAuthError("CONFLICT", "마지막 패스키는 삭제할 수 없습니다.")
            records.delete_credential(credential)
            records.delete_sessions()
