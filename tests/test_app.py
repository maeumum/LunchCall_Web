from __future__ import annotations

import os
import re
from pathlib import Path

TEST_DB = Path(__file__).with_name("test_lunchcall.db")
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["ADMIN_LOGIN_ID"] = "admin"
os.environ["ADMIN_PASSWORD"] = "StrongPrototype123!"
os.environ["PROTOTYPE_ALLOW_EARLY_CONFIRM"] = "true"
os.environ["SMS_MODE"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_admin_meal_flow() -> None:
    with TestClient(app) as client:
        failed = client.post(
            "/login",
            data={"login_id": "admin", "password": "wrong"},
            follow_redirects=True,
        )
        assert "올바르지 않습니다" in failed.text

        login = client.post(
            "/login",
            data={"login_id": "admin", "password": "StrongPrototype123!"},
            follow_redirects=True,
        )
        assert login.status_code == 200
        assert "오늘의 식수" in login.text
        csrf = csrf_from(login.text)

        created = client.post(
            "/employees",
            data={
                "csrf_token": csrf,
                "name": "홍길동",
                "department": "개발팀",
                "phone": "",
            },
            follow_redirects=True,
        )
        assert "홍길동님을 추가했습니다" in created.text

        dashboard = client.get("/")
        assert "홍길동" in dashboard.text
        csrf = csrf_from(dashboard.text)
        employee_id = re.search(r"/absences/(\d+)/toggle", dashboard.text)
        assert employee_id

        toggled = client.post(
            f"/absences/{employee_id.group(1)}/toggle",
            data={"csrf_token": csrf},
            follow_redirects=True,
        )
        assert "식사 상태를 변경했습니다" in toggled.text
        assert "명이 식사합니다" in toggled.text

        csrf = csrf_from(toggled.text)
        confirmed = client.post(
            "/confirm", data={"csrf_token": csrf}, follow_redirects=True
        )
        assert "식수를 확정하고 문자를 전송했습니다" in confirmed.text
        assert "확정 완료" in confirmed.text
        assert "전송 성공" in confirmed.text

        history = client.get("/history")
        assert history.status_code == 200
        assert "발송 성공" in history.text

        csrf = csrf_from(confirmed.text)
        duplicate = client.post(
            "/confirm", data={"csrf_token": csrf}, follow_redirects=True
        )
        assert "이미 확정된 식수입니다" in duplicate.text


def teardown_module() -> None:
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
