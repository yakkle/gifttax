import hashlib
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

import cbor2
import jwt
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from webauthn.helpers import bytes_to_base64url

from backend.admin import main
from backend.main import app
from backend.middleware.admin_security import MAX_ADMIN_BODY
from backend.middleware.rate_limit import RateLimiter
from backend.services.admin_auth import AdminAuthService, reset_admin_auth
from backend.services.admin_sessions import AdminAuthError, token_hash
from backend.settings import AdminSettings
from backend.storage.admin import AdminRepository
from backend.storage.models import (
    AdminAccount,
    AdminChallenge,
    AdminCredential,
    AdminOneTimeToken,
    AdminSession,
    Feedback,
)

ORIGIN = "https://admin.example.test"
RP_ID = "admin.example.test"
SECRET = "test-only-secret-with-at-least-32-bytes-and-no-production-use"
COOKIE = "__Host-gifttax-admin-session"
FLOW_COOKIE = "__Host-gifttax-admin-flow"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(tmp_path / "admin.sqlite3"))
    monkeypatch.setenv("GIFTTAX_ADMIN_ORIGIN", ORIGIN)
    monkeypatch.setenv("GIFTTAX_ADMIN_RP_ID", RP_ID)
    monkeypatch.setenv("GIFTTAX_ADMIN_JWT_SECRET", SECRET)
    monkeypatch.setenv("GIFTTAX_ADMIN_MODE", "webauthn")
    monkeypatch.setenv("GIFTTAX_ADMIN_ALLOW_INSECURE_LOCALHOST", "false")
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client


@pytest.fixture
def service(client):
    return AdminAuthService(AdminRepository(app.state.database), AdminSettings())


def post(client, path, data=None, *, csrf=None, **kwargs):
    headers = {"Origin": ORIGIN}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return client.post(f"/api/admin/auth/{path}", json=data or {}, headers=headers, **kwargs)


class Authenticator:
    """A real P-256 credential, encoded as WebAuthn CBOR and signed assertions."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        self.user_handle = None

    def client_data(self, options, operation, origin, challenge, cross_origin):
        return json.dumps(
            {
                "type": f"webauthn.{operation}",
                "challenge": challenge or options["challenge"],
                "origin": origin,
                "crossOrigin": cross_origin,
            }
        ).encode()

    def registration(
        self, options, *, origin=ORIGIN, rp_id=RP_ID, uv=True, challenge=None, cross_origin=False
    ):
        self.user_handle = options["user"]["id"]
        public = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {1: 2, 3: -7, -1: 1, -2: public.x.to_bytes(32), -3: public.y.to_bytes(32)}
        )
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([0x41 | (0x04 if uv else 0)])
            + bytes(4)
            + bytes(16)
            + len(self.id).to_bytes(2)
            + self.id
            + cose
        )
        return {
            "id": bytes_to_base64url(self.id),
            "rawId": bytes_to_base64url(self.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(
                    self.client_data(options, "create", origin, challenge, cross_origin)
                ),
                "attestationObject": bytes_to_base64url(
                    cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
                ),
                "transports": ["internal"],
            },
        }

    def assertion(
        self,
        options,
        *,
        origin=ORIGIN,
        rp_id=RP_ID,
        uv=True,
        counter=1,
        challenge=None,
        wrong_signature=False,
        cross_origin=False,
    ):
        client = self.client_data(options, "get", origin, challenge, cross_origin)
        auth_data = (
            hashlib.sha256(rp_id.encode()).digest()
            + bytes([0x01 | (0x04 if uv else 0)])
            + counter.to_bytes(4)
        )
        signer = ec.generate_private_key(ec.SECP256R1()) if wrong_signature else self.key
        signature = signer.sign(
            auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": bytes_to_base64url(self.id),
            "rawId": bytes_to_base64url(self.id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": self.user_handle,
            },
        }


def enroll(client, service, authenticator=None, *, code=None, label="내 패스키", csrf=None):
    authenticator = authenticator or Authenticator()
    payload = (
        {"registration_code": code or service.issue_registration_code()} if csrf is None else {}
    )
    start = post(client, "registration/options", payload, csrf=csrf)
    assert start.status_code == 200, start.text
    data = start.json()
    finish = post(
        client,
        "registration/verify",
        {
            **payload,
            "challenge_id": data["challenge_id"],
            "label": label,
            "credential": authenticator.registration(data["options"]),
        },
        csrf=csrf,
    )
    assert finish.status_code == 200, finish.text
    return authenticator, finish


def login(client, authenticator, **assertion_options):
    start = post(client, "authentication/options")
    assert start.status_code == 200, start.text
    data = start.json()
    payload = {
        "challenge_id": data["challenge_id"],
        "credential": authenticator.assertion(data["options"], **assertion_options),
    }
    return post(client, "authentication/verify", payload), payload


def manual(service, monkeypatch):
    monkeypatch.setenv("GIFTTAX_ADMIN_MODE", "manual_jwt")
    return AdminAuthService(service.repository, AdminSettings())


def test_bootstrap_login_logout_and_revocation(client, service):
    key, registered = enroll(client, service)
    assert set(registered.json()) == {"csrf_token", "expires_at"}
    assert registered.json()["expires_at"] - int(time.time()) in range(28795, 28801)
    cookie_headers = registered.headers.get_list("set-cookie")
    assert any(
        COOKIE in value
        and "HttpOnly" in value
        and "Secure" in value
        and "SameSite=strict" in value
        and "Path=/" in value
        for value in cookie_headers
    )
    assert not client.cookies.get(FLOW_COOKIE)
    cookie = client.cookies.get(COOKIE)
    assert client.get("/api/admin/auth/session").status_code == 200
    with service.repository.transaction(write=False) as records:
        account = records.account()
        assert len(account.user_handle) == 32
        credential = records.credential(key.id)
        assert credential.sign_count == 0
        assert credential.transports_json == '["internal"]'
    csrf = registered.json()["csrf_token"]
    assert post(client, "logout", csrf=csrf).status_code == 204
    assert client.get("/api/admin/auth/session").status_code == 401
    with pytest.raises(AdminAuthError):
        service.sessions.authenticate(cookie)
    authenticated, payload = login(client, key)
    assert authenticated.status_code == 200, authenticated.text
    assert post(client, "authentication/verify", payload).status_code == 401
    with service.repository.transaction(write=False) as records:
        credential = records.credential(key.id)
        assert credential.sign_count == 1 and credential.last_used_at


@pytest.mark.parametrize(
    "kwargs",
    [
        {"origin": "https://evil.example.test"},
        {"rp_id": "evil.example.test"},
        {"uv": False},
        {"challenge": bytes_to_base64url(b"wrong-challenge")},
    ],
)
def test_registration_verifies_origin_rp_uv_and_challenge(client, service, kwargs):
    code = service.issue_registration_code()
    start = post(client, "registration/options", {"registration_code": code}).json()
    key = Authenticator()
    payload = {
        "registration_code": code,
        "challenge_id": start["challenge_id"],
        "credential": key.registration(start["options"], **kwargs),
    }
    assert post(client, "registration/verify", payload).status_code == 401
    payload["credential"] = key.registration(start["options"])
    assert post(client, "registration/verify", payload).status_code == 401
    assert not service.has_credentials()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"origin": "https://evil.example.test"},
        {"rp_id": "evil.example.test"},
        {"uv": False},
        {"challenge": bytes_to_base64url(b"wrong-challenge")},
        {"wrong_signature": True},
    ],
)
def test_authentication_rejects_invalid_proofs_and_consumes_challenge(client, service, kwargs):
    key, _ = enroll(client, service)
    response, payload = login(client, key, **kwargs)
    assert response.status_code == 401
    assert post(client, "authentication/verify", payload).status_code == 401
    assert login(client, key)[0].status_code == 200


def test_counter_rollback_and_wrong_user_are_rejected(client, service):
    key, _ = enroll(client, service)
    assert login(client, key, counter=5)[0].status_code == 200
    assert login(client, key, counter=5)[0].status_code == 401
    assert login(client, key, counter=4)[0].status_code == 401
    key.user_handle = bytes_to_base64url(b"other-user")
    assert login(client, key, counter=6)[0].status_code == 401


def test_zero_counter_synced_passkeys_are_supported(client, service):
    key, _ = enroll(client, service)
    assert login(client, key, counter=0)[0].status_code == 200
    assert login(client, key, counter=0)[0].status_code == 200


def test_bootstrap_code_is_hashed_replaced_and_single_use(client, service):
    old_code = service.issue_registration_code()
    code = service.issue_registration_code()
    with service.repository.transaction(write=False) as records:
        assert records.token(token_hash(code), "registration", int(time.time()))
        assert not records.token(code, "registration", int(time.time()))
    assert post(client, "registration/options", {"registration_code": old_code}).status_code == 401
    enroll(client, service, code=code)
    assert post(client, "registration/options", {"registration_code": code}).status_code == 401
    with pytest.raises(AdminAuthError, match="이미 패스키"):
        service.issue_registration_code()


def test_flow_cookie_is_required_and_bound_to_ceremony(client, service):
    key, _ = enroll(client, service)
    first = post(client, "authentication/options").json()
    first_cookie = client.cookies.get(FLOW_COOKIE)
    post(client, "authentication/options")
    payload = {"challenge_id": first["challenge_id"], "credential": key.assertion(first["options"])}
    assert post(client, "authentication/verify", payload).status_code == 401
    client.cookies.delete(FLOW_COOKIE)
    assert post(client, "authentication/verify", payload).status_code == 401
    client.cookies.set(FLOW_COOKIE, first_cookie, domain=RP_ID, path="/")
    assert post(client, "authentication/verify", payload).status_code == 200


@pytest.mark.parametrize(
    "kind",
    [
        "registration_code",
        "registration_challenge",
        "authentication_challenge",
        "session",
        "login_token",
    ],
)
def test_expiry_is_enforced_without_retention_cleanup(client, service, monkeypatch, kind):
    now = int(time.time())
    if kind == "registration_code":
        code = service.issue_registration_code()
        with app.state.database.session(write=True) as db:
            row = db.get(AdminOneTimeToken, token_hash(code))
            row.created_at, row.expires_at = now - 601, now - 1
        response = post(client, "registration/options", {"registration_code": code})
    elif kind == "login_token":
        service = manual(service, monkeypatch)
        token = service.sessions.issue_login_token()
        with app.state.database.session(write=True) as db:
            row = db.get(AdminOneTimeToken, token_hash(token))
            row.created_at, row.expires_at = now - 301, now - 1
        response = post(client, "token/exchange", {"token": token})
    elif kind == "session":
        enroll(client, service)
        with app.state.database.session(write=True) as db:
            row = db.scalar(select(AdminSession))
            row.created_at, row.expires_at = now - 28801, now - 1
        response = client.get("/api/admin/auth/session")
    else:
        key = Authenticator()
        payload = {}
        if kind == "registration_challenge":
            payload["registration_code"] = service.issue_registration_code()
            start = post(client, "registration/options", payload).json()
            credential = key.registration(start["options"])
            path = "registration/verify"
        else:
            enroll(client, service, key)
            start = post(client, "authentication/options").json()
            credential = key.assertion(start["options"])
            path = "authentication/verify"
        with app.state.database.session(write=True) as db:
            row = db.get(AdminChallenge, start["challenge_id"])
            row.created_at, row.expires_at = now - 301, now - 1
        response = post(
            client,
            path,
            {**payload, "challenge_id": start["challenge_id"], "credential": credential},
        )
    assert response.status_code == 401, response.text


def test_add_delete_passkeys_rotate_and_revoke_sessions(client, service):
    first, registered = enroll(client, service, label="첫 기기")
    old_cookie = client.cookies.get(COOKIE)
    csrf = registered.json()["csrf_token"]
    assert post(client, "registration/options").status_code == 403
    second, added = enroll(client, service, label="예비 키", csrf=csrf)
    csrf = added.json()["csrf_token"]
    with pytest.raises(AdminAuthError):
        service.sessions.authenticate(old_cookie)
    keys = client.get("/api/admin/auth/credentials").json()
    assert {row["label"] for row in keys} == {"첫 기기", "예비 키"}
    assert all(row["can_delete"] for row in keys)
    path = f"/api/admin/auth/credentials/{bytes_to_base64url(first.id)}"
    assert client.delete(path).status_code == 403
    response = client.request(
        "DELETE", path, json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
    )
    assert response.status_code == 204, response.text
    assert client.get("/api/admin/auth/session").status_code == 401
    assert login(client, first)[0].status_code == 401
    response, _ = login(client, second)
    assert response.status_code == 200
    keys = client.get("/api/admin/auth/credentials").json()
    assert len(keys) == 1 and not keys[0]["can_delete"]
    response = client.request(
        "DELETE",
        f"/api/admin/auth/credentials/{keys[0]['id']}",
        json={},
        headers={"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]},
    )
    assert response.status_code == 409


def test_manual_jwt_is_explicit_and_token_is_single_use(client, service, monkeypatch):
    assert post(client, "token/exchange", {"token": "arbitrary"}).status_code == 403
    with pytest.raises(AdminAuthError):
        service.sessions.issue_login_token()
    service = manual(service, monkeypatch)
    replaced = service.sessions.issue_login_token()
    token = service.sessions.issue_login_token()
    assert post(client, "token/exchange", {"token": replaced}).status_code == 401
    assert post(client, "registration/options", {"registration_code": "code"}).status_code == 403
    assert post(client, "authentication/options").status_code == 403
    assert post(client, "token/exchange", {"token": token}).status_code == 200
    assert post(client, "token/exchange", {"token": token}).status_code == 401
    assert client.get("/api/admin/auth/session").status_code == 200
    assert token != client.cookies.get(COOKIE)
    with pytest.raises(AdminAuthError):
        service.sessions.authenticate(token)
    monkeypatch.setenv("GIFTTAX_ADMIN_MODE", "webauthn")
    assert client.get("/api/admin/auth/session").status_code == 401


def test_concurrent_manual_exchange_creates_only_one_session(client, service, monkeypatch):
    service = manual(service, monkeypatch)
    token = service.sessions.issue_login_token()

    def exchange(_):
        try:
            return service.sessions.exchange_login_token(token)
        except AdminAuthError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        grants = list(pool.map(exchange, range(4)))
    assert sum(value is not None for value in grants) == 1
    with app.state.database.session() as db:
        assert db.scalar(select(func.count()).select_from(AdminSession)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"exp": 1},
        {"iss": "https://evil.test"},
        {"aud": "other"},
        {"sub": "2"},
        {"token_use": "login"},
        {"auth_mode": "manual_jwt"},
        {"jti": ["invalid"]},
    ],
)
def test_jwt_claims_are_verified(client, service, change):
    enroll(client, service)
    claims = jwt.decode(client.cookies.get(COOKIE), options={"verify_signature": False})
    token = jwt.encode({**claims, **change}, SECRET, algorithm="HS256")
    with pytest.raises(AdminAuthError):
        service.sessions.authenticate(token)


@pytest.mark.parametrize("algorithm", ["none", "HS384"])
def test_jwt_algorithm_is_pinned(client, service, algorithm):
    enroll(client, service)
    claims = jwt.decode(client.cookies.get(COOKIE), options={"verify_signature": False})
    token = jwt.encode(claims, "" if algorithm == "none" else SECRET, algorithm=algorithm)
    with pytest.raises(AdminAuthError):
        service.sessions.authenticate(token)


def test_reset_preserves_feedback_and_invalidates_all_auth(client, service):
    key, _ = enroll(client, service)
    cookie = client.cookies.get(COOKIE)
    start = post(client, "authentication/options").json()
    with app.state.database.session(write=True) as db:
        db.add(
            Feedback(
                id="keep",
                category="review",
                source="general",
                message="보존",
                created_at=int(time.time()),
            )
        )
    reset_admin_auth(service.repository)
    with app.state.database.session() as db:
        assert db.get(Feedback, "keep").message == "보존"
        for model in [
            AdminAccount,
            AdminCredential,
            AdminSession,
            AdminChallenge,
            AdminOneTimeToken,
        ]:
            assert db.scalar(select(func.count()).select_from(model)) == 0
    with pytest.raises(AdminAuthError):
        service.sessions.authenticate(cookie)
    assert (
        post(
            client,
            "authentication/verify",
            {"challenge_id": start["challenge_id"], "credential": key.assertion(start["options"])},
        ).status_code
        == 401
    )
    enroll(client, service)


@pytest.mark.parametrize(
    "origin", [None, "null", "https://evil.test", "https://child.admin.example.test"]
)
def test_cross_origin_mutations_are_blocked_without_cors(client, origin):
    response = client.post(
        "/api/admin/auth/authentication/options",
        json={},
        headers={} if origin is None else {"Origin": origin},
    )
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_private_get_preflight_public_cors_and_security_headers(client):
    assert (
        client.get("/api/admin/auth/config", headers={"Origin": "https://evil.test"}).status_code
        == 403
    )
    response = client.options(
        "/api/admin/auth/session",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 403 and "access-control-allow-origin" not in response.headers
    response = client.get("/api/health", headers={"Origin": "https://other.test"})
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == "*"
    for path in ["/admin", "/admin/", "/admin.js", "/admin.css", "/api/admin/auth/session"]:
        response = client.get(path)
        assert response.status_code in {200, 401}
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert "access-control-allow-origin" not in response.headers


def test_csrf_required_and_bad_input_not_reflected(client, service):
    _, response = enroll(client, service)
    assert post(client, "logout").status_code == 403
    assert post(client, "logout", csrf="incorrect").status_code == 403
    assert client.get("/api/admin/auth/session").status_code == 200
    secret = "sensitive-invalid-token"
    response = post(client, "token/exchange", {"token": {secret: secret}})
    assert response.status_code == 422 and secret not in response.text


def test_request_body_bound_and_content_type(client):
    response = client.post(
        "/api/admin/auth/token/exchange",
        content='{"token":"' + "a" * MAX_ADMIN_BODY + '"}',
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    response = client.post(
        "/api/admin/auth/token/exchange", content="token=x", headers={"Origin": ORIGIN}
    )
    assert response.status_code == 415


def test_rate_limit_and_window(client):
    app.state.admin_limiter = RateLimiter(per_client=2)
    assert post(client, "authentication/options").status_code == 409
    assert post(client, "authentication/options").status_code == 409
    response = post(client, "authentication/options")
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    limiter = RateLimiter(per_client=2, total=3)
    assert limiter.allow("a", now=0) and limiter.allow("a", now=1)
    assert not limiter.allow("a", now=2)
    assert limiter.allow("b", now=3)
    assert not limiter.allow("c", now=4)
    assert limiter.allow("a", now=61)


def test_unconfigured_admin_does_not_break_public_api(client, monkeypatch):
    monkeypatch.delenv("GIFTTAX_ADMIN_JWT_SECRET")
    assert client.get("/api/admin/auth/session").status_code == 503
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


@pytest.mark.parametrize(
    "kwargs",
    [
        {"origin": "http://admin.example.test"},
        {"origin": "https://user:pass@admin.example.test"},
        {"origin": ORIGIN + "/path"},
        {"origin": ORIGIN + "?q=x"},
        {"origin": ORIGIN + "#fragment"},
        {"origin": ORIGIN + ":invalid"},
        {"rp_id": "example.test"},
        {"jwt_secret": "short"},
        {"origin": "http://localhost", "rp_id": "localhost"},
        {"mode": "invalid"},
    ],
)
def test_invalid_admin_settings_fail_closed(kwargs):
    with pytest.raises(ValidationError):
        AdminSettings(**{"origin": ORIGIN, "rp_id": RP_ID, "jwt_secret": SECRET, **kwargs})


def test_local_http_requires_explicit_loopback_exception():
    settings = AdminSettings(
        origin="http://localhost:8000/",
        rp_id="localhost",
        jwt_secret=SECRET,
        allow_insecure_localhost=True,
    )
    assert settings.is_local_http and settings.canonical_origin == "http://localhost:8000"
    assert not settings.session_cookie_name.startswith("__Host-")
    with pytest.raises(ValidationError):
        AdminSettings(
            origin="http://admin.example.test",
            rp_id=RP_ID,
            jwt_secret=SECRET,
            allow_insecure_localhost=True,
        )


def test_cli_bootstrap_manual_and_recovery(client, monkeypatch, capsys):
    assert main(["issue-registration-code"]) == 0
    output = capsys.readouterr().out
    code = output.splitlines()[-1]
    assert post(client, "registration/options", {"registration_code": code}).status_code == 200
    monkeypatch.setenv("GIFTTAX_ADMIN_MODE", "manual_jwt")
    assert main(["issue-login-token"]) == 0
    token = capsys.readouterr().out.splitlines()[-1]
    assert post(client, "token/exchange", {"token": token}).status_code == 200
    monkeypatch.delenv("GIFTTAX_ADMIN_JWT_SECRET")
    assert main(["reset-auth"]) == 0
    capsys.readouterr()
    assert main(["issue-login-token"]) == 1
    errors = capsys.readouterr().err
    assert token not in errors and SECRET not in errors


def test_cli_handles_unknown_schema_without_traceback(client, capsys):
    from sqlalchemy import text

    with app.state.database.session(write=True) as db:
        db.execute(text("UPDATE alembic_version SET version_num='unknown'"))
    assert main(["issue-registration-code"]) == 1
    assert "마이그레이션" in capsys.readouterr().err


@pytest.mark.parametrize("operation", ["registration", "authentication"])
def test_cross_origin_webauthn_client_data_is_rejected(client, service, operation):
    key = Authenticator()
    payload = {}
    if operation == "registration":
        payload["registration_code"] = service.issue_registration_code()
        start = post(client, "registration/options", payload).json()
        credential = key.registration(start["options"], cross_origin=True)
    else:
        enroll(client, service, key)
        start = post(client, "authentication/options").json()
        credential = key.assertion(start["options"], cross_origin=True)
    response = post(
        client,
        f"{operation}/verify",
        {**payload, "challenge_id": start["challenge_id"], "credential": credential},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("operation", ["registration", "authentication"])
@pytest.mark.parametrize(
    "credential",
    [
        {},
        {"id": "broken", "rawId": "_", "type": "public-key", "response": {}},
    ],
)
def test_malformed_webauthn_input_is_rejected_safely(client, service, operation, credential):
    payload = {}
    if operation == "registration":
        payload["registration_code"] = service.issue_registration_code()
        start = post(client, "registration/options", payload).json()
    else:
        enroll(client, service)
        start = post(client, "authentication/options").json()
    response = post(
        client,
        f"{operation}/verify",
        {**payload, "challenge_id": start["challenge_id"], "credential": credential},
    )
    assert response.status_code == 401


def test_concurrent_bootstrap_registration_has_only_one_winner(client, service):
    code = service.issue_registration_code()
    starts = [service.registration_options(code, None, None) for _ in range(2)]
    credentials = [Authenticator().registration(start.options) for start in starts]

    def register(index):
        start = starts[index]
        try:
            return service.register(
                start.challenge_id, credentials[index], "패스키", start.flow_token, code, None, None
            )
        except AdminAuthError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        grants = list(pool.map(register, range(2)))
    assert sum(value is not None for value in grants) == 1
    with app.state.database.session() as db:
        assert db.scalar(select(func.count()).select_from(AdminCredential)) == 1
        assert db.scalar(select(func.count()).select_from(AdminSession)) == 1


def test_duplicate_origin_headers_are_rejected(client):
    response = client.post(
        "/api/admin/auth/authentication/options",
        json={},
        headers=[("Origin", ORIGIN), ("Origin", ORIGIN)],
    )
    assert response.status_code == 403


def test_database_error_response_hides_storage_details(client):
    from sqlalchemy import text

    with app.state.database.session(write=True) as db:
        db.execute(text("DROP TABLE admin_sessions"))
    response = client.get("/api/admin/auth/session")
    # Missing auth is rejected before the session lookup.
    assert response.status_code == 401
    with app.state.database.session(write=True) as db:
        db.execute(text("DROP TABLE admin_credentials"))
    response = client.get("/api/admin/auth/config")
    assert response.status_code == 503
    assert "admin_credentials" not in response.text and "SELECT" not in response.text
