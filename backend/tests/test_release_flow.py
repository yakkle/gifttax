"""배포 전 사용자 흐름, 재시작 및 인증을 폐기하는 복원 절차 검증."""

import sqlite3
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.admin import main as admin_command
from backend.main import app

ORIGIN = "https://admin.example.test"


@pytest.fixture
def database_path(tmp_path, monkeypatch):
    path = tmp_path / "release.sqlite3"
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(path))
    monkeypatch.setenv("GIFTTAX_ADMIN_ORIGIN", ORIGIN)
    monkeypatch.setenv("GIFTTAX_ADMIN_RP_ID", "admin.example.test")
    monkeypatch.setenv("GIFTTAX_ADMIN_MODE", "manual_jwt")
    monkeypatch.setenv("GIFTTAX_ADMIN_JWT_SECRET", "release-test-secret-with-more-than-32-bytes")
    monkeypatch.setattr("backend.api.backend.STORAGE_DIR", str(tmp_path / "pdf"))
    return path


def login_from_server_cli(client, capsys):
    assert admin_command(["issue-login-token"]) == 0
    token = capsys.readouterr().out.strip().splitlines()[-1]
    response = client.post(
        "/api/admin/auth/token/exchange", json={"token": token}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    assert (
        client.post(
            "/api/admin/auth/token/exchange", json={"token": token}, headers={"Origin": ORIGIN}
        ).status_code
        == 401
    )
    return response.json()["csrf_token"]


def submit_feedback(client):
    payload = {
        "submission_id": str(uuid4()),
        "satisfaction": "satisfied",
        "category": "suggestion",
        "message": "계산 결과를 비교하고 싶어요.",
        "source": "result",
        "email": "reply@example.com",
        "email_consent": True,
    }
    assert client.post("/api/feedback", json=payload).status_code == 201
    assert client.post("/api/feedback", json=payload).status_code == 200
    return payload["submission_id"]


def test_user_to_admin_flow_survives_restart(database_path, monkeypatch, capsys):
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
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/").status_code == 200
        assert (
            client.post(
                "/api/events", json={"event_id": str(uuid4()), "event_type": "page_view"}
            ).status_code
            == 204
        )
        calculation = client.post(
            "/api/calculate",
            json={
                "gift_date": "2025-11-06",
                "stocks": [{"ticker": "AAPL", "qty": 10, "currency": "USD"}],
            },
        )
        assert calculation.status_code == 200
        assert Decimal(calculation.json()["total_gift_amount_krw"]) == Decimal("2600000")
        for kind in ("gift", "rate"):
            file_id = calculation.json()[f"{kind}_pdf_file_id"]
            pdf = client.get(f"/api/download/{file_id}")
            assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        identifier = submit_feedback(client)
        assert (
            client.post(
                "/api/events",
                json={
                    "event_id": str(uuid4()),
                    "event_type": "support_click",
                    "source": "feedback",
                    "target": "github",
                },
            ).status_code
            == 204
        )
        assert client.get("/api/admin/feedback").status_code == 401
        csrf = login_from_server_cli(client, capsys)
        assert (
            client.patch(
                f"/api/admin/feedback/{identifier}",
                json={"status": "in_progress"},
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            ).status_code
            == 200
        )
        expected_totals = client.get("/api/admin/usage").json()["totals"]
        assert expected_totals == {
            "page_views": 1,
            "visitors": 1,
            "calculation_successes": 1,
            "calculation_failures": 0,
            "calculation_users": 1,
            "gift_pdf_downloads": 1,
            "rate_pdf_downloads": 1,
            "feedback_submissions": 1,
            "support_clicks": 1,
        }
        cookies = dict(client.cookies)

    assert database_path.is_file()
    with TestClient(app, base_url=ORIGIN, cookies=cookies) as restarted:
        feedback = restarted.get("/api/admin/feedback").json()
        assert feedback["total"] == 1
        assert feedback["items"][0]["id"] == identifier
        assert feedback["items"][0]["status"] == "in_progress"
        assert feedback["items"][0]["email"] == "reply@example.com"
        assert restarted.get("/api/admin/usage").json()["totals"] == expected_totals


def test_restore_resets_auth_before_serving_and_preserves_feedback(
    database_path,
    tmp_path,
    monkeypatch,
    capsys,
):
    backup_path = tmp_path / "backup.sqlite3"
    restored_path = tmp_path / "restored.sqlite3"
    with TestClient(app, base_url=ORIGIN) as client:
        identifier = submit_feedback(client)
        login_from_server_cli(client, capsys)
        cookies = dict(client.cookies)
        # 실행 중인 WAL의 변경 내용도 SQLite backup API로 스냅샷에 포함한다.
        with sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True) as source:
            with sqlite3.connect(backup_path) as destination:
                source.backup(destination)

    with sqlite3.connect(f"{backup_path.as_uri()}?mode=ro", uri=True) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert backup.execute("PRAGMA foreign_key_check").fetchall() == []
        with sqlite3.connect(restored_path) as destination:
            backup.backup(destination)
    monkeypatch.setenv("GIFTTAX_DATABASE_PATH", str(restored_path))
    # 복원한 앱을 공개하기 전에 실행하는 운영 절차와 같은 순서다.
    assert admin_command(["reset-auth"]) == 0
    capsys.readouterr()

    with TestClient(app, base_url=ORIGIN, cookies=cookies) as restored:
        assert restored.get("/api/admin/feedback").status_code == 401
        assert restored.get("/api/admin/usage").status_code == 401
        login_from_server_cli(restored, capsys)
        feedback = restored.get("/api/admin/feedback").json()
        assert feedback["total"] == 1
        assert feedback["items"][0]["id"] == identifier
        assert feedback["items"][0]["email"] == "reply@example.com"
        assert restored.get("/api/admin/usage").json()["totals"]["feedback_submissions"] == 1
