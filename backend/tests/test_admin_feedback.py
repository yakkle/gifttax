from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from dateutil.relativedelta import relativedelta
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from backend.api.dependencies import admin_feedback_service
from backend.main import app
from backend.services.admin_feedback import AdminFeedbackService
from backend.services.admin_sessions import AdminSessionService
from backend.services.usage import KOREA
from backend.settings import AdminSettings
from backend.storage.admin import AdminRepository
from backend.storage.feedback import AdminFeedbackRepository
from backend.storage.models import Feedback, FeedbackContact

ORIGIN = "https://admin.example.test"
NOW = datetime(2026, 10, 27, 12, tzinfo=KOREA)
API = "/api/admin/feedback"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(tmp_path / "admin-feedback.sqlite3"))
    monkeypatch.setenv("GIFTTAX_ADMIN_ORIGIN", ORIGIN)
    monkeypatch.setenv("GIFTTAX_ADMIN_RP_ID", "admin.example.test")
    monkeypatch.setenv("GIFTTAX_ADMIN_MODE", "manual_jwt")
    monkeypatch.setenv("GIFTTAX_ADMIN_JWT_SECRET", "test-only-secret-with-more-than-32-bytes")
    with TestClient(app, base_url=ORIGIN) as test_client:
        service = AdminFeedbackService(
            AdminFeedbackRepository(app.state.database), clock=lambda: NOW.timestamp()
        )
        app.dependency_overrides[admin_feedback_service] = lambda: service
        try:
            yield test_client
        finally:
            app.dependency_overrides.pop(admin_feedback_service, None)


def authenticate(client):
    sessions = AdminSessionService(AdminRepository(app.state.database), AdminSettings())
    response = client.post(
        "/api/admin/auth/token/exchange",
        json={"token": sessions.issue_login_token()},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def seed(*, identifier=None, created=NOW, email=None, expires=None, **changes):
    identifier = identifier or str(uuid4())
    with app.state.database.session(write=True) as session:
        row = Feedback(
            id=identifier,
            satisfaction="satisfied",
            category="review",
            message="사용하기 좋아요 <script>alert(1)</script>",
            source="general",
            created_at=int(created.timestamp()),
        )
        for key, value in changes.items():
            setattr(row, key, value)
        if email:
            row.contact = FeedbackContact(
                email=email,
                consented_at=int((NOW - timedelta(days=89)).timestamp()),
                expires_at=int((expires or NOW + timedelta(days=1)).timestamp()),
            )
        session.add(row)
    return identifier


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_all_operations_require_session_and_same_origin(client, method):
    identifier = seed(email="private@example.com")
    path = API if method == "GET" else f"{API}/{identifier}"
    kwargs = {} if method == "GET" else {"json": {"status": "resolved"}}
    response = client.request(method, path, headers={"Origin": ORIGIN}, **kwargs)
    assert response.status_code == 401
    assert "private@example.com" not in response.text
    assert response.headers["cache-control"] == "no-store"
    headers = authenticate(client)
    for origin in ("https://evil.example", "null"):
        response = client.request(method, path, headers={**headers, "Origin": origin}, **kwargs)
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers
    if method != "GET":
        for csrf in (None, "wrong"):
            headers = {"Origin": ORIGIN}
            if csrf:
                headers["X-CSRF-Token"] = csrf
            assert client.request(method, path, headers=headers, **kwargs).status_code == 403


def test_stable_pagination_and_all_filters(client):
    authenticate(client)
    ids = [seed(identifier=str(UUID(int=i)), message="") for i in range(1, 52)]
    target = seed(category="problem", satisfaction="dissatisfied", status="in_progress")
    seed(created=NOW - timedelta(days=1), category="suggestion", satisfaction=None)
    first = client.get(API).json()
    second = client.get(API, params={"page": 2}).json()
    assert (first["total"], first["page_size"], len(first["items"]), len(second["items"])) == (
        53,
        50,
        50,
        3,
    )
    all_ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(all_ids)) == 53
    assert all_ids[1:52] == ids[::-1]  # Same timestamp is ordered by id descending.
    assert all(item["email"] is None for item in first["items"])
    params = {
        "start_date": "2026-10-27",
        "end_date": "2026-10-27",
        "category": "problem",
        "satisfaction": "dissatisfied",
        "status": "in_progress",
    }
    filtered = client.get(API, params=params).json()
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == target
    assert client.get(API, params={"page": 999}).json()["items"] == []
    assert client.get(API, params={"status": "resolved"}).json()["total"] == 0


def test_korean_date_boundaries_and_retention_without_cleanup(client):
    authenticate(client)
    midnight = NOW.replace(hour=0)
    before = seed(created=midnight - timedelta(seconds=1))
    start = seed(created=midnight)
    end = seed(created=midnight + timedelta(days=1) - timedelta(seconds=1))
    seed(created=midnight + timedelta(days=1))
    cutoff = NOW.astimezone(UTC) - relativedelta(years=1)
    expired = seed(created=cutoff)
    alive = seed(created=cutoff + timedelta(seconds=1))
    result = client.get(API, params={"start_date": "2026-10-27", "end_date": "2026-10-27"}).json()
    assert {item["id"] for item in result["items"]} == {start, end}
    retained = {item["id"] for item in client.get(API).json()["items"]}
    assert before in retained and alive in retained and expired not in retained


def test_expired_contacts_are_not_returned_even_before_cleanup(client):
    authenticate(client)
    live = seed(email="live@example.com", expires=NOW + timedelta(seconds=1))
    expired = seed(email="expired@example.com", expires=NOW)
    response = client.get(API)
    records = {item["id"]: item for item in response.json()["items"]}
    assert records[live]["email"] == "live@example.com"
    assert records[expired]["email"] is None
    assert records[expired]["email_expires_at"] is None
    assert "expired@example.com" not in response.text
    with app.state.database.session() as session:
        assert session.get(FeedbackContact, expired) is not None


def test_status_changes_and_delete_cascade_preserve_usage_history(client):
    headers = authenticate(client)
    # Submit through the public API so that the historical counter is also exercised.
    identifier = str(uuid4())
    response = client.post(
        "/api/feedback",
        json={
            "submission_id": identifier,
            "message": "고쳐 주세요",
            "category": "problem",
            "email": "answer@example.com",
            "email_consent": True,
        },
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 201
    initial = app.state.usage_service.summary().totals.feedback_submissions
    for status in ("in_progress", "resolved", "new"):
        response = client.patch(f"{API}/{identifier}", json={"status": status}, headers=headers)
        assert response.status_code == 200 and response.json()["status"] == status
        with app.state.database.session() as session:
            record = session.get(Feedback, identifier)
            assert record.status == status and record.message == "고쳐 주세요"
    assert (
        client.request("DELETE", f"{API}/{identifier}", json={}, headers=headers).status_code == 204
    )
    with app.state.database.session() as session:
        assert session.get(Feedback, identifier) is None
        assert session.get(FeedbackContact, identifier) is None
    assert app.state.usage_service.summary().totals.feedback_submissions == initial == 1
    assert (
        client.request("DELETE", f"{API}/{identifier}", json={}, headers=headers).status_code == 404
    )


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page": 1000001},
        {"page": "invalid"},
        {"category": "other"},
        {"satisfaction": "other"},
        {"status": "other"},
        {"start_date": "invalid"},
        {"start_date": "2026-10-28"},
        {"end_date": "2026-10-28"},
        {"start_date": "2026-10-27", "end_date": "2026-10-26"},
    ],
)
def test_invalid_filters(client, params):
    authenticate(client)
    assert client.get(API, params=params).status_code == 422


def test_invalid_mutations_missing_or_expired_rows_and_revoked_session(client):
    headers = authenticate(client)
    identifier = seed()
    for body in ({"status": "other"}, {"status": "resolved", "message": "private@example.com"}, {}):
        response = client.patch(f"{API}/{identifier}", json=body, headers=headers)
        assert response.status_code == 422 and "private@example.com" not in response.text
    assert (
        client.patch(f"{API}/not-a-uuid", json={"status": "new"}, headers=headers).status_code
        == 422
    )
    expired = seed(created=NOW - relativedelta(years=1))
    for identifier in (expired, str(uuid4())):
        assert (
            client.patch(f"{API}/{identifier}", json={"status": "new"}, headers=headers).status_code
            == 404
        )
        assert (
            client.request("DELETE", f"{API}/{identifier}", json={}, headers=headers).status_code
            == 404
        )
    assert client.post("/api/admin/auth/logout", json={}, headers=headers).status_code == 204
    assert client.get(API).status_code == 401


def test_disabled_admin_storage_errors_and_static_security(client, monkeypatch):
    authenticate(client)
    service = app.dependency_overrides[admin_feedback_service]()

    def fail(**kwargs):
        raise OperationalError("SELECT private@example.com", {}, Exception("private database path"))

    monkeypatch.setattr(service.repository, "list", fail)
    response = client.get(API)
    assert response.status_code == 503
    assert "private@example.com" not in response.text and "database path" not in response.text
    monkeypatch.delenv("GIFTTAX_ADMIN_JWT_SECRET")
    assert client.get(API).status_code == 503
    response = client.get("/admin-dashboard.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    with app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(Feedback)) == 0
