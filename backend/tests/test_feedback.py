import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.main import app
from backend.middleware.feedback import MAX_FEEDBACK_BODY
from backend.middleware.rate_limit import RateLimiter
from backend.schemas.feedback import FeedbackCreate
from backend.services.feedback import FeedbackService
from backend.services.retention import cleanup_expired_data
from backend.storage.feedback import FeedbackRepository
from backend.storage.models import Feedback, FeedbackContact

NOW = datetime(2026, 10, 27, tzinfo=UTC)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(tmp_path / "feedback.sqlite3"))
    monkeypatch.setenv("GIFTTAX_ADMIN_ORIGIN", "")
    monkeypatch.setenv("GIFTTAX_ADMIN_JWT_SECRET", "")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def database(client):
    return app.state.database


def payload(**changes):
    return {"submission_id": str(uuid4()), "satisfaction": "satisfied", **changes}


def counts(database):
    with database.session() as session:
        return (
            session.scalar(select(func.count()).select_from(Feedback)),
            session.scalar(select(func.count()).select_from(FeedbackContact)),
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"satisfaction": "satisfied"},
        {"satisfaction": "neutral"},
        {"satisfaction": "dissatisfied"},
        {"satisfaction": None, "message": "개선해 주세요"},
        {"satisfaction": "satisfied", "message": "  도움이 됐습니다  "},
    ],
)
def test_anonymous_feedback_accepts_rating_or_text(client, database, fields):
    data = payload(**fields)
    response = client.post("/api/feedback", json=data)
    assert response.status_code == 201
    assert response.json() == {
        "id": data["submission_id"],
        "message": "의견을 남겨 주셔서 감사합니다.",
    }
    assert response.headers["cache-control"] == "no-store"
    with database.session() as session:
        row = session.get(Feedback, data["submission_id"])
        assert row.satisfaction == fields.get("satisfaction")
        assert row.message == fields.get("message", "").strip()
        assert (row.category, row.source, row.status) == ("review", "general", "new")
        assert row.contact is None
    assert counts(database) == (1, 0)


@pytest.mark.parametrize(
    "category,source",
    [
        ("review", "general"),
        ("problem", "error"),
        ("suggestion", "result"),
    ],
)
def test_feedback_category_and_entry_point(client, database, category, source):
    data = payload(category=category, source=source)
    assert client.post("/api/feedback", json=data).status_code == 201
    with database.session() as session:
        row = session.get(Feedback, data["submission_id"])
        assert (row.category, row.source) == (category, source)


@pytest.mark.parametrize(
    "fields",
    [
        {"satisfaction": None},
        {"satisfaction": None, "message": " \n\t "},
        {"satisfaction": None, "email": "reader@example.com", "email_consent": True},
    ],
)
def test_empty_feedback_is_rejected(client, database, fields):
    response = client.post("/api/feedback", json=payload(**fields))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EMPTY_FEEDBACK"
    assert counts(database) == (0, 0)


@pytest.mark.parametrize(
    "fields",
    [
        {"submission_id": "not-a-uuid"},
        {"satisfaction": "excellent"},
        {"category": "other"},
        {"source": "unknown"},
        {"message": "가" * 2001},
        {"message": ["unexpected"]},
        {"email": ["private@example.com"]},
        {"email": "x" * 255},
        {"email_consent": "true"},
        {"email_consent": 1},
        {"website": 123},
        {"created_at": 1},
        {"status": "resolved"},
    ],
)
def test_invalid_contract_is_rejected_without_echoing_input(client, database, fields):
    response = client.post("/api/feedback", json=payload(**fields))
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "INVALID_REQUEST",
        "message": "입력 내용을 확인해 주세요.",
    }
    assert "private@example.com" not in response.text
    assert counts(database) == (0, 0)


def test_email_is_normalized_and_saved_separately_with_90_day_expiry(client, database):
    data = payload(email="  Reply@EXAMPLE.COM  ", email_consent=True)
    before = int(datetime.now(UTC).timestamp())
    with patch(
        "email_validator.deliverability.validate_email_deliverability",
        side_effect=AssertionError("DNS must not be used"),
    ):
        response = client.post("/api/feedback", json=data)
    after = int(datetime.now(UTC).timestamp())
    assert response.status_code == 201
    assert "example.com" not in response.text
    with database.session() as session:
        row = session.get(Feedback, data["submission_id"])
        assert row.contact.email == "Reply@example.com"
        assert before <= row.created_at == row.contact.consented_at <= after
        assert row.contact.expires_at - row.contact.consented_at == 90 * 24 * 60 * 60
        assert row.message == ""


@pytest.mark.parametrize(
    "email",
    ["not-email", "a@@example.com", "a @example.com", "Name <a@example.com>", "a@localhost"],
)
def test_invalid_email_is_rejected(client, database, email):
    response = client.post("/api/feedback", json=payload(email=email, email_consent=True))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_EMAIL"
    assert email not in response.text
    assert counts(database) == (0, 0)


def test_email_requires_explicit_consent(client, database):
    response = client.post("/api/feedback", json=payload(email="private@example.com"))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EMAIL_CONSENT_REQUIRED"
    assert "private@example.com" not in response.text
    assert counts(database) == (0, 0)


@pytest.mark.parametrize("email,consent", [(None, False), ("  ", False), (None, True)])
def test_optional_blank_email_does_not_store_a_contact(client, database, email, consent):
    response = client.post("/api/feedback", json=payload(email=email, email_consent=consent))
    assert response.status_code == 201
    assert counts(database) == (1, 0)


def test_repeated_id_returns_same_receipt_without_overwriting(client, database):
    data = payload(message="원래 의견", email="first@example.com", email_consent=True)
    first = client.post("/api/feedback", json=data)
    retry = client.post(
        "/api/feedback", json={**data, "message": "변경 의견", "email": "second@example.com"}
    )
    assert (first.status_code, retry.status_code) == (201, 200)
    assert first.json() == retry.json()
    with database.session() as session:
        row = session.get(Feedback, data["submission_id"])
        assert row.message == "원래 의견"
        assert row.contact.email == "first@example.com"
    assert counts(database) == (1, 1)


def test_retry_does_not_extend_or_recreate_expired_email(database):
    service = FeedbackService(FeedbackRepository(database), clock=lambda: NOW.timestamp())
    data = FeedbackCreate(**payload(email="reader@example.com", email_consent=True))
    assert service.submit(data).created
    with database.session() as session:
        expires_at = session.get(FeedbackContact, str(data.submission_id)).expires_at
    service.clock = lambda: (NOW + timedelta(days=1)).timestamp()
    assert not service.submit(data).created
    with database.session() as session:
        assert session.get(FeedbackContact, str(data.submission_id)).expires_at == expires_at
    cleanup_expired_data(database, now=NOW + timedelta(days=90))
    service.clock = lambda: (NOW + timedelta(days=90)).timestamp()
    assert not service.submit(data).created
    assert counts(database) == (1, 0)


def test_concurrent_retries_store_feedback_and_contact_once(database):
    service = FeedbackService(FeedbackRepository(database))
    data = FeedbackCreate(**payload(email="reader@example.com", email_consent=True))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: service.submit(data), range(6)))
    assert sum(result.created for result in results) == 1
    assert {result.id for result in results} == {data.submission_id}
    assert counts(database) == (1, 1)


def test_contact_failure_rolls_back_feedback_and_masks_storage_details(client, database):
    with database.session(write=True) as session:
        session.connection().exec_driver_sql(
            "CREATE TRIGGER fail_contact BEFORE INSERT ON feedback_contacts "
            "BEGIN SELECT RAISE(ABORT, 'private storage detail'); END"
        )
    data = payload(email="private@example.com", email_consent=True)
    response = client.post("/api/feedback", json=data)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "STORAGE_UNAVAILABLE"
    assert "private@example.com" not in response.text
    assert "private storage detail" not in response.text
    assert counts(database) == (0, 0)
    with database.session(write=True) as session:
        session.connection().exec_driver_sql("DROP TRIGGER fail_contact")
    assert client.post("/api/feedback", json=data).status_code == 201
    assert counts(database) == (1, 1)


def test_honeypot_returns_receipt_without_storing_anything(client, database):
    data = payload(website="https://bot.example.com", email="invalid-without-consent")
    with patch.object(
        FeedbackRepository, "transaction", side_effect=AssertionError("must not write")
    ):
        response = client.post("/api/feedback", json=data)
    assert response.status_code == 201
    assert response.json()["id"] == data["submission_id"]
    assert counts(database) == (0, 0)


def test_feedback_is_private_and_receipt_does_not_echo_content(client, database):
    data = payload(
        message='<script>alert("private")</script>', email="private@example.com", email_consent=True
    )
    response = client.post("/api/feedback", json=data)
    assert response.status_code == 201
    assert "private" not in response.text
    assert client.get("/api/feedback").status_code == 405
    assert client.get(f"/api/feedback/{data['submission_id']}").status_code == 404
    with database.session() as session:
        assert session.get(Feedback, data["submission_id"]).message == data["message"]


def test_json_only_and_malformed_json_are_safe(client, database):
    assert client.post("/api/feedback", data={"email": "private@example.com"}).status_code == 415
    response = client.post(
        "/api/feedback",
        content='{"email":"private@example.com",',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "private@example.com" not in response.text
    assert counts(database) == (0, 0)


@pytest.mark.parametrize("streamed", [False, True])
def test_large_requests_are_rejected_before_validation(client, database, streamed):
    content = b"x" * (MAX_FEEDBACK_BODY + 1)
    if streamed:
        content = iter([content[:100], content[100:]])
    response = client.post(
        "/api/feedback", content=content, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert counts(database) == (0, 0)


def test_maximum_length_unicode_message_fits_json_limit(client, database):
    data = payload(message="😀" * 2000)
    response = client.post(
        "/api/feedback",
        content=json.dumps(data, ensure_ascii=True),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 201
    assert counts(database) == (1, 0)


def test_rate_limit_returns_retry_after_and_resets(client, database, monkeypatch):
    current = [1000.0]
    monkeypatch.setattr("backend.middleware.rate_limit.monotonic", lambda: current[0])
    for _ in range(5):
        assert client.post("/api/feedback", json=payload()).status_code == 201
    blocked = client.post("/api/feedback", json=payload())
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"
    assert client.get("/api/health").status_code == 200
    current[0] += 61
    assert client.post("/api/feedback", json=payload()).status_code == 201
    assert counts(database) == (6, 0)


def test_invalid_requests_also_consume_rate_limit(client, database):
    for _ in range(5):
        assert client.post("/api/feedback", content="not-json").status_code == 415
    assert client.post("/api/feedback", json=payload()).status_code == 429
    assert counts(database) == (0, 0)


def test_untrusted_forwarded_headers_cannot_bypass_limit(client):
    for index in range(5):
        assert (
            client.post(
                "/api/feedback", json=payload(), headers={"X-Forwarded-For": f"203.0.113.{index}"}
            ).status_code
            == 201
        )
    assert (
        client.post(
            "/api/feedback", json=payload(), headers={"X-Forwarded-For": "203.0.113.99"}
        ).status_code
        == 429
    )


def test_trusted_proxy_partitions_limits_by_actual_client(client):
    proxied = TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"))
    try:
        for _ in range(5):
            assert (
                proxied.post(
                    "/api/feedback", json=payload(), headers={"X-Forwarded-For": "203.0.113.10"}
                ).status_code
                == 201
            )
        assert (
            proxied.post(
                "/api/feedback", json=payload(), headers={"X-Forwarded-For": "203.0.113.10"}
            ).status_code
            == 429
        )
        assert (
            proxied.post(
                "/api/feedback", json=payload(), headers={"X-Forwarded-For": "203.0.113.11"}
            ).status_code
            == 201
        )
    finally:
        proxied.close()


def test_global_feedback_limit_and_concurrent_limit(client):
    app.state.feedback_limiter = RateLimiter(per_client=10, total=1)
    proxied = TestClient(ProxyHeadersMiddleware(app, trusted_hosts="*"))
    try:
        assert (
            proxied.post(
                "/api/feedback", json=payload(), headers={"X-Forwarded-For": "203.0.113.10"}
            ).status_code
            == 201
        )
        assert (
            proxied.post(
                "/api/feedback", json=payload(), headers={"X-Forwarded-For": "203.0.113.11"}
            ).status_code
            == 429
        )
    finally:
        proxied.close()
    limiter = RateLimiter(per_client=2, total=10)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(lambda _: limiter.allow("same", now=0), range(20))) == 2


def test_missing_storage_returns_retryable_error(client):
    database = app.state.database
    del app.state.database
    try:
        response = client.post("/api/feedback", json=payload())
        assert response.status_code == 503
    finally:
        app.state.database = database
