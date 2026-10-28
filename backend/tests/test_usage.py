from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.integrations.scraper.yahoo import InvalidTickerError
from backend.main import app
from backend.middleware.rate_limit import RateLimiter
from backend.schemas.usage import ClientUsageEvent, UsageCounts, UsageEventType
from backend.services.admin_sessions import AdminSessionService
from backend.services.retention import cleanup_expired_data
from backend.services.usage import KOREA, UsageService
from backend.settings import AdminSettings
from backend.storage.admin import AdminRepository
from backend.storage.models import DailyUsageCount, UsageEvent
from backend.storage.usage import UsageRepository

ORIGIN = "https://admin.example.test"
NOW = datetime(2026, 10, 27, 12, tzinfo=KOREA)
CALCULATION = {
    "gift_date": "2025-11-06",
    "stocks": [{"ticker": "AAPL", "qty": 10, "currency": "USD"}],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("GIFTTAX_ADMIN_ORIGIN", ORIGIN)
    monkeypatch.setenv("GIFTTAX_ADMIN_RP_ID", "admin.example.test")
    monkeypatch.setenv("GIFTTAX_ADMIN_MODE", "manual_jwt")
    monkeypatch.setenv("GIFTTAX_ADMIN_JWT_SECRET", "test-only-secret-with-more-than-32-bytes")
    monkeypatch.setattr("backend.api.backend.STORAGE_DIR", str(tmp_path / "pdf"))
    with TestClient(app, base_url=ORIGIN) as test_client:
        yield test_client


def event(**changes):
    return {"event_id": str(uuid4()), "event_type": "page_view", **changes}


def totals():
    return app.state.usage_service.summary().totals


def authenticate(client):
    sessions = AdminSessionService(AdminRepository(app.state.database), AdminSettings())
    token = sessions.issue_login_token()
    response = client.post(
        "/api/admin/auth/token/exchange", json={"token": token}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200


def test_cookie_is_opaque_secure_reused_and_not_renewed(client):
    assert "set-cookie" not in client.get("/api/health").headers
    response = client.get("/")
    cookie = response.headers["set-cookie"]
    assert all(
        part in cookie
        for part in ("HttpOnly", "Secure", "SameSite=lax", "Max-Age=7776000", "Path=/")
    )
    identifier = client.cookies.get("__Host-gifttax-visitor")
    assert UUID(identifier).version == 4
    assert "set-cookie" not in client.get("/index").headers
    assert totals().page_views == 0
    for _ in range(2):
        response = client.post("/api/events", json=event())
        assert response.status_code == 204
        assert "set-cookie" not in response.headers
        assert response.headers["cache-control"] == "no-store"
    assert (totals().page_views, totals().visitors) == (2, 1)
    with app.state.database.session() as session:
        assert set(session.scalars(select(UsageEvent.visitor_id))) == {identifier}
    response = client.get("/", headers={"Cookie": "__Host-gifttax-visitor=not-an-id"})
    assert "set-cookie" in response.headers


def test_local_http_cookie_can_be_sent_back(client):
    local = TestClient(app, base_url="http://testserver")
    try:
        response = local.get("/")
        assert "Secure" not in response.headers["set-cookie"]
        assert local.cookies.get("gifttax-visitor")
        assert local.post("/api/events", json=event()).status_code == 204
        assert local.post("/api/events", json=event()).status_code == 204
        assert totals().visitors == 1
    finally:
        local.close()


def test_client_retries_and_support_targets_are_allowlisted(client):
    payload = event()
    for _ in range(2):
        assert client.post("/api/events", json=payload).status_code == 204
    for source, target in [("header", "fairy"), ("feedback", "github")]:
        assert (
            client.post(
                "/api/events",
                json=event(
                    event_type="support_click",
                    source=source,
                    target=target,
                ),
            ).status_code
            == 204
        )
    assert (totals().page_views, totals().support_clicks) == (1, 2)


@pytest.mark.parametrize(
    "changes",
    [
        {"event_type": "calculation_success"},
        {"event_type": "gift_pdf_download"},
        {"event_type": "feedback_submitted"},
        {"event_type": "calculation_failure"},
        {"source": "header"},
        {"target": "fairy"},
        {"event_type": "support_click"},
        {"event_type": "support_click", "source": "header", "target": "other"},
        {"visitor_id": "private@example.com"},
        {"email": "private@example.com"},
        {"event_id": "private@example.com"},
        {"occurred_at": 1},
    ],
)
def test_forged_server_events_or_private_data_are_rejected(client, changes):
    response = client.post("/api/events", json=event(**changes))
    assert response.status_code == 422
    assert "private@example.com" not in response.text
    assert totals() == UsageCounts()


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
        [("Origin", ORIGIN), ("Origin", ORIGIN)],
    ],
)
def test_external_origins_cannot_record_events(client, headers):
    assert client.post("/api/events", json=event(), headers=headers).status_code == 403
    assert totals().page_views == 0


def test_same_origin_json_size_limits_and_rate_limit(client, monkeypatch):
    assert client.post("/api/events", json=event(), headers={"Origin": ORIGIN}).status_code == 204
    assert client.post("/api/events", content="private@example.com").status_code == 415
    assert (
        client.post(
            "/api/events",
            content=iter([b"x" * 2048, b"x" * 2049]),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    response = client.post(
        "/api/events",
        content='{"email":"private@example.com",',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422 and "private@example.com" not in response.text
    clock = [1000.0]
    monkeypatch.setattr("backend.middleware.rate_limit.monotonic", lambda: clock[0])
    app.state.usage_limiter = RateLimiter(per_client=1, total=2)
    assert client.post("/api/events", json=event()).status_code == 204
    blocked = client.post("/api/events", json=event())
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"
    clock[0] += 61
    assert client.post("/api/events", json=event()).status_code == 204


def test_calculation_and_both_pdf_downloads_are_counted_on_server(client, monkeypatch):
    monkeypatch.setattr(
        "backend.services.calculator.scraper.get_stock_prices",
        lambda *args: [(date(2025, 9, 7), Decimal("200"))],
    )
    monkeypatch.setattr(
        "backend.services.calculator.smbs.get_exchange_rate",
        lambda *args: (Decimal("1300"), date(2025, 11, 5)),
    )
    monkeypatch.setattr(
        "backend.services.calculator.smbs.get_exchange_rates",
        lambda *args: [(date(2025, 11, 5), Decimal("1300"))],
    )
    response = client.post("/api/calculate", json=CALCULATION)
    assert response.status_code == 200
    data = response.json()
    for kind in ("gift", "rate"):
        file_id = data[f"{kind}_pdf_file_id"]
        assert file_id.startswith(f"{kind}-")
        assert client.get(f"/api/download/{file_id}").status_code == 200
        assert client.get(f"/api/download/{file_id}").status_code == 404
    assert (
        totals().calculation_successes,
        totals().calculation_users,
        totals().gift_pdf_downloads,
        totals().rate_pdf_downloads,
    ) == (1, 1, 1, 1)
    assert totals().visitors == 0  # A calculation alone is not a page view.


@pytest.mark.parametrize(
    "error,status", [(InvalidTickerError("invalid"), 400), (RuntimeError("failed"), 500)]
)
def test_calculation_failures_and_validation_errors_are_counted(client, monkeypatch, error, status):
    def fail(*args):
        raise error

    monkeypatch.setattr("backend.services.calculator.calculate_total_gift", fail)
    assert client.post("/api/calculate", json=CALCULATION).status_code == status
    assert client.post("/api/calculate", json={}).status_code == 422
    assert (totals().calculation_failures, totals().calculation_successes) == (2, 0)


def test_only_real_new_feedback_counts(client):
    payload = {"submission_id": str(uuid4()), "satisfaction": "satisfied"}
    assert client.post("/api/feedback", json=payload).status_code == 201
    assert client.post("/api/feedback", json=payload).status_code == 200
    assert (
        client.post(
            "/api/feedback", json={**payload, "submission_id": str(uuid4()), "website": "bot"}
        ).status_code
        == 201
    )
    assert client.post("/api/feedback", json={"submission_id": str(uuid4())}).status_code == 422
    assert totals().feedback_submissions == 1


def test_stats_failure_does_not_block_business_responses(client, monkeypatch, tmp_path, caplog):
    from backend.api import backend

    def fail(*args, **kwargs):
        raise OperationalError("private database data", {}, Exception("private"))

    monkeypatch.setattr(app.state.usage_service.repository, "record", fail)
    feedback = client.post(
        "/api/feedback", json={"submission_id": str(uuid4()), "satisfaction": "satisfied"}
    )
    assert feedback.status_code == 201
    assert client.post("/api/calculate", json={}).status_code == 422
    file_id = f"gift-{uuid4()}"
    pdf = tmp_path / f"{file_id}.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    monkeypatch.setattr(backend, "STORAGE_DIR", str(tmp_path))
    assert client.get(f"/api/download/{file_id}").status_code == 200
    assert not pdf.exists()
    response = client.post("/api/events", json=event())
    assert response.status_code == 503 and "private" not in response.text
    assert "private" not in caplog.text


def test_delete_and_untyped_pdf_download_do_not_count(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.api.backend.STORAGE_DIR", str(tmp_path))
    for file_id in (str(uuid4()), f"gift-{uuid4()}"):
        (tmp_path / f"{file_id}.pdf").write_bytes(b"pdf")
    assert client.get(f"/api/download/{file_id}").status_code == 200
    # Only the typed download above is counted; a legacy opaque UUID still works.
    legacy = next(tmp_path.glob("*.pdf"))
    assert client.get(f"/api/download/{legacy.stem}").status_code == 200
    assert client.delete(f"/api/download/rate-{uuid4()}").status_code == 204
    assert (totals().gift_pdf_downloads, totals().rate_pdf_downloads) == (1, 0)


def test_concurrent_event_retries_are_atomic(client):
    service = app.state.usage_service
    payload = ClientUsageEvent(**event())
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: service.record_client(payload, str(uuid4())), range(6)))
    assert totals().page_views == 1
    with app.state.database.session(write=True) as session:
        session.connection().exec_driver_sql(
            "CREATE TRIGGER fail_daily BEFORE UPDATE ON daily_usage_counts "
            "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        )
    with pytest.raises(IntegrityError):
        service.record_client(ClientUsageEvent(**event()), str(uuid4()))
    with app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 1
        assert session.scalar(select(DailyUsageCount.event_count)) == 1


@pytest.mark.parametrize("days", [7, 30, 90])
def test_korean_calendar_boundaries_zero_days_and_unique_visitors(client, days):
    service = UsageService(UsageRepository(app.state.database), clock=lambda: NOW.timestamp())
    visitor = str(uuid4())
    first = (NOW - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0)
    for moment in [
        first - timedelta(seconds=1),
        first,
        NOW - timedelta(days=1),
        NOW,
        NOW.replace(hour=0) + timedelta(days=1),
    ]:
        service.clock = lambda moment=moment: moment.timestamp()
        service.record(UsageEventType.PAGE_VIEW, visitor)
        service.record(UsageEventType.CALCULATION_SUCCESS, visitor)
    service.clock = lambda: NOW.timestamp()
    summary = service.summary(days)
    assert len(summary.daily) == days
    assert summary.timezone == "Asia/Seoul"
    assert summary.period_start == first.date() and summary.period_end == NOW.date()
    assert (
        summary.totals.page_views,
        summary.totals.visitors,
        summary.totals.calculation_successes,
        summary.totals.calculation_users,
    ) == (3, 1, 3, 1)
    assert sum(day.visitors for day in summary.daily) == 3
    assert summary.daily[1].page_views == 0
    assert summary.daily[0].visitors == 1


def test_retention_removes_raw_ids_and_keeps_aggregate_counts(client):
    service = UsageService(
        UsageRepository(app.state.database), clock=lambda: (NOW - timedelta(days=91)).timestamp()
    )
    service.record(UsageEventType.PAGE_VIEW, str(uuid4()))
    cleanup_expired_data(app.state.database, now=NOW.astimezone(UTC))
    with app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(UsageEvent)) == 0
        assert session.scalar(select(DailyUsageCount.event_count)) == 1


def test_summary_requires_admin_and_allowed_periods(client, monkeypatch):
    assert client.get("/api/admin/usage").status_code == 401
    authenticate(client)
    for days in (7, 30, 90):
        response = client.get(f"/api/admin/usage?days={days}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert len(response.json()["daily"]) == days
        assert "visitor_id" not in response.text
    assert client.get("/api/admin/usage?days=8").status_code == 422
    assert client.get("/api/admin/usage?days=oops").status_code == 422
    assert (
        client.get("/api/admin/usage", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert totals().page_views == 0
    monkeypatch.setenv("GIFTTAX_ADMIN_JWT_SECRET", "")
    assert client.get("/api/admin/usage").status_code == 503
