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
from app.main import app, initialize_database  # noqa: E402


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

        settings_page = client.get("/settings")
        assert settings_page.status_code == 200
        assert "기본 설정" in settings_page.text
        assert "SMS 설정" in settings_page.text
        assert "부서 관리" in settings_page.text
        assert "공휴일" in settings_page.text
        assert "관리자 계정" in settings_page.text

        sms_settings = client.get("/settings?section=sms")
        assert "발송 미리보기" in sms_settings.text
        assert "data-sms-template" in sms_settings.text
        assert "data-sms-preview-message" in sms_settings.text

        department_settings = client.get("/settings?section=departments")
        assert "AISW연구개발팀" in department_settings.text
        assert "부서 저장 기능" in department_settings.text

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
        assert "이름, 부서 또는 연락처 검색" in created.text
        assert "data-employee-search-form" in created.text
        assert "data-employee-department-filter" in created.text
        assert "data-employee-status-filter" in created.text
        assert 'data-search-text="홍길동 AISW연구개발팀 010-1234-5678"' in created.text
        assert 'data-department="AISW연구개발팀"' in created.text
        assert 'data-status="ACTIVE"' in created.text

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
                "status": "ACTIVE",
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
                "status": "ACTIVE",
            },
            follow_redirects=True,
        )
        assert "김길동님의 정보를 수정했습니다" in edited.text
        assert "교육운영홍보팀" in edited.text
        assert "010-8765-4321" in edited.text

        dashboard = client.get("/")
        assert "김길동" in dashboard.text
        assert "data-meal-search-form" in dashboard.text
        assert 'data-meal-filter-value="MEAL"' in dashboard.text
        assert 'data-meal-filter-value="ABSENT"' in dashboard.text
        assert 'data-meal-status="MEAL"' in dashboard.text
        assert 'id="confirm-sms-dialog"' in dashboard.text
        assert "실제 발송 문구" in dashboard.text
        assert "010-0000-0000" in dashboard.text
        assert "식사 인원은 1명입니다" in dashboard.text
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
        assert 'data-meal-status="ABSENT"' in toggled.text
        assert "식사 인원은 0명입니다" in toggled.text

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
        assert "data-history-open" in history.text
        assert "확정 관리자" in history.text
        assert "김길동" in history.text
        assert "실제 발송 문구" in history.text
        assert "010-0000-0000" in history.text
        assert "식사 인원은 0명입니다" in history.text
        assert "1차" in history.text
        assert "MOCK" in history.text
        assert "mock-" in history.text

        csrf = csrf_from(confirmed.text)
        duplicate = client.post(
            "/confirm", data={"csrf_token": csrf}, follow_redirects=True
        )
        assert "이미 확정된 식수입니다" in duplicate.text

        csrf = csrf_from(duplicate.text)
        reset_today = client.post(
            "/prototype/reset-today",
            data={"csrf_token": csrf},
            follow_redirects=True,
        )
        assert "오늘의 목업 확정을 초기화했습니다" in reset_today.text
        assert "불참 선택은 유지됩니다" in reset_today.text
        assert 'data-meal-status="ABSENT"' in reset_today.text
        assert "아직 발송 내역이 없습니다" in reset_today.text

        csrf = csrf_from(reset_today.text)
        deleted = client.post(
            f"/employees/{dashboard_employee_id.group(1)}/delete",
            data={"csrf_token": csrf},
            follow_redirects=True,
        )
        assert "직원 목록에서 삭제했습니다" in deleted.text
        employee_list = client.get("/employees")
        assert f"/employees/{dashboard_employee_id.group(1)}/status" not in employee_list.text

        account = client.get("/account")
        assert account.status_code == 200
        assert "section=account" in str(account.url)
        assert "관리자 계정" in account.text
        csrf = csrf_from(account.text)

        wrong_password = client.post(
            "/account",
            data={
                "csrf_token": csrf,
                "login_id": "meal-admin",
                "current_password": "wrong",
                "new_password": "NewStrongPassword123!",
                "new_password_confirm": "NewStrongPassword123!",
            },
            follow_redirects=True,
        )
        assert "현재 비밀번호가 올바르지 않습니다" in wrong_password.text

        updated_account = client.post(
            "/account",
            data={
                "csrf_token": csrf,
                "login_id": "meal-admin",
                "current_password": "StrongPrototype123!",
                "new_password": "NewStrongPassword123!",
                "new_password_confirm": "NewStrongPassword123!",
            },
            follow_redirects=True,
        )
        assert "관리자 계정 정보를 변경했습니다" in updated_account.text
        assert 'value="meal-admin"' in updated_account.text

        initialize_database()

        csrf = csrf_from(updated_account.text)
        client.post("/logout", data={"csrf_token": csrf}, follow_redirects=True)
        old_login = client.post(
            "/login",
            data={"login_id": "admin", "password": "StrongPrototype123!"},
            follow_redirects=True,
        )
        assert "아이디 또는 비밀번호가 올바르지 않습니다" in old_login.text
        new_login = client.post(
            "/login",
            data={"login_id": "meal-admin", "password": "NewStrongPassword123!"},
            follow_redirects=True,
        )
        assert "오늘의 식수" in new_login.text


def teardown_module() -> None:
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
