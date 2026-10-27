"""ORM access for admin authentication. Business decisions belong to services."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.storage.database import Database
from backend.storage.models import (
    AdminAccount,
    AdminChallenge,
    AdminCredential,
    AdminOneTimeToken,
    AdminSession,
)


class AdminRecords:
    def __init__(self, session: Session) -> None:
        self.session = session

    def account(self) -> AdminAccount | None:
        return self.session.get(AdminAccount, 1)

    def create_account(self, user_handle: bytes, now: int) -> AdminAccount:
        account = AdminAccount(id=1, user_handle=user_handle, created_at=now)
        self.session.add(account)
        self.session.flush()
        return account

    def credentials(self) -> list[AdminCredential]:
        return list(
            self.session.scalars(
                select(AdminCredential).order_by(
                    AdminCredential.created_at, AdminCredential.credential_id
                )
            )
        )

    def credential_count(self) -> int:
        return self.session.scalar(select(func.count()).select_from(AdminCredential))

    def credential(self, credential_id: bytes) -> AdminCredential | None:
        return self.session.get(AdminCredential, credential_id)

    def add_credential(
        self,
        *,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        transports_json: str,
        label: str,
        created_at: int,
    ) -> None:
        self.session.add(
            AdminCredential(
                admin_id=1,
                credential_id=credential_id,
                public_key=public_key,
                sign_count=sign_count,
                transports_json=transports_json,
                label=label,
                created_at=created_at,
            )
        )

    def delete_credential(self, credential: AdminCredential) -> None:
        self.session.delete(credential)

    def login_session(self, session_id: str, now: int) -> AdminSession | None:
        record = self.session.get(AdminSession, session_id)
        return record if record is not None and record.expires_at > now else None

    def add_session(self, session_id: str, now: int, expires_at: int) -> None:
        self.session.add(
            AdminSession(session_id=session_id, admin_id=1, created_at=now, expires_at=expires_at)
        )

    def delete_session(self, session_id: str) -> None:
        self.session.execute(delete(AdminSession).where(AdminSession.session_id == session_id))

    def delete_sessions(self) -> None:
        self.session.execute(delete(AdminSession))

    def token(self, token_hash: str, purpose: str, now: int) -> AdminOneTimeToken | None:
        token = self.session.get(AdminOneTimeToken, token_hash)
        return (
            token
            if token is not None and token.purpose == purpose and token.expires_at > now
            else None
        )

    def add_token(self, token_hash: str, purpose: str, now: int, expires_at: int) -> None:
        self.session.add(
            AdminOneTimeToken(
                token_hash=token_hash, purpose=purpose, created_at=now, expires_at=expires_at
            )
        )

    def delete_token(self, token: AdminOneTimeToken) -> None:
        self.session.delete(token)

    def delete_tokens(self, purpose: str) -> None:
        self.session.execute(delete(AdminOneTimeToken).where(AdminOneTimeToken.purpose == purpose))

    def challenge(self, challenge_id: str, purpose: str, now: int) -> AdminChallenge | None:
        challenge = self.session.get(AdminChallenge, challenge_id)
        return (
            challenge
            if challenge is not None and challenge.purpose == purpose and challenge.expires_at > now
            else None
        )

    def add_challenge(
        self,
        *,
        challenge_id: str,
        challenge: bytes,
        purpose: str,
        binding_hash: str,
        created_at: int,
        expires_at: int,
    ) -> None:
        self.session.add(
            AdminChallenge(
                challenge_id=challenge_id,
                challenge=challenge,
                purpose=purpose,
                binding_hash=binding_hash,
                created_at=created_at,
                expires_at=expires_at,
            )
        )

    def delete_challenge(self, challenge: AdminChallenge) -> None:
        self.session.delete(challenge)

    def reset(self) -> None:
        for model in (
            AdminChallenge,
            AdminOneTimeToken,
            AdminSession,
            AdminCredential,
            AdminAccount,
        ):
            self.session.execute(delete(model), execution_options={"synchronize_session": False})


class AdminRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def transaction(self, *, write: bool = True) -> Iterator[AdminRecords]:
        with self.database.session(write=write) as session:
            yield AdminRecords(session)
