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
os.environ["DEPARTMENTS"] = "교육운영홍보팀,콘텐츠연구개발팀,경영지원팀,AISW연구개발팀"
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

        holiday_sync = client.post(
            "/holidays/sync",
            data={"csrf_token": csrf},
            follow_redirects=True,
        )
        assert "HOLIDAY_API_KEY가 설정되지 않았습니다" in holiday_sync.text

        invalid_department = client.post(
            "/employees",
            data={
                "csrf_token": csrf,
                "name": "잘못된부서",
                "department": "목록에없는팀",
                "phone": "",
            },
            follow_redirects=True,
        )
        assert "목록에 있는 부서를 선택해 주세요" in invalid_department.text

        invalid_phone = client.post(
            "/employees",
            data={
                "csrf_token": csrf,
                "name": "잘못된번호",
                "department": "경영지원팀",
                "phone": "010123456789",
            },
            follow_redirects=True,
        )
        assert "휴대전화 번호 11자리" in invalid_phone.text

        created = client.post(
            "/employees",
            data={
                "csrf_token": csrf,
                "name": "홍길동",
                "department": "AISW연구개발팀",
                "phone": "01012345678",
            },
            follow_redirects=True,
        )
        assert "홍길동님을 추가했습니다" in created.text
        assert "010-1234-5678" in created.text

        employee_id = re.search(r'data-employee-id="(\d+)"', created.text)
        assert employee_id
        csrf = csrf_from(created.text)

        invalid_edit = client.post(
            f"/employees/{employee_id.group(1)}/edit",
            data={
                "csrf_token": csrf,
                "name": "김길동",
                "department": "교육운영홍보팀",
                "phone": "010123456789",
            },
            follow_redirects=True,
        )
        assert "휴대전화 번호 11자리" in invalid_edit.text

        edited = client.post(
            f"/employees/{employee_id.group(1)}/edit",
            data={
                "csrf_token": csrf,
                "name": "김길동",
                "department": "교육운영홍보팀",
                "phone": "01087654321",
            },
            follow_redirects=True,
        )
        assert "김길동님의 정보를 수정했습니다" in edited.text
        assert "교육운영홍보팀" in edited.text
        assert "010-8765-4321" in edited.text

        dashboard = client.get("/")
        assert "김길동" in dashboard.text
        csrf = csrf_from(dashboard.text)
        dashboard_employee_id = re.search(r"/absences/(\d+)/toggle", dashboard.text)
        assert dashboard_employee_id

        toggled = client.post(
            f"/absences/{dashboard_employee_id.group(1)}/toggle",
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

        csrf = csrf_from(duplicate.text)
        deleted = client.post(
            f"/employees/{dashboard_employee_id.group(1)}/delete",
            data={"csrf_token": csrf},
            follow_redirects=True,
        )
        assert "직원 목록에서 삭제했습니다" in deleted.text
        employee_list = client.get("/employees")
        assert f"/employees/{dashboard_employee_id.group(1)}/status" not in employee_list.text


def teardown_module() -> None:
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
