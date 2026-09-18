from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
import logging
from math import ceil
from pathlib import Path
import re
from string import Formatter
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import Admin, AdminSession, DailyMeal, Employee, Holiday, ServiceSetting, SmsLog
from .security import create_session, delete_session, get_session, hash_password, verify_password
from .services import (
    BusinessRuleError,
    CONFIRM_TIME,
    build_sms_message,
    confirm_and_send,
    get_or_create_daily_meal,
    get_or_create_service_settings,
    holiday_name,
    meal_summary,
    reset_mock_confirmation,
    retry_failed_sms,
    seoul_now,
    sync_holidays,
    toggle_absence,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
logger = logging.getLogger(__name__)


def initialize_database() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        admin_count = db.scalar(select(func.count(Admin.id))) or 0
        if admin_count == 0:
            db.add(
                Admin(
                    login_id=settings.admin_login_id,
                    display_name=settings.admin_display_name,
                    password_hash=hash_password(settings.admin_password),
                )
            )
            db.commit()
        get_or_create_service_settings(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="LunchCall", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def redirect(path: str, message: str | None = None, error: str | None = None):
    query = ""
    separator = "&" if "?" in path else "?"
    if message:
        query = f"{separator}message={quote(message)}"
    elif error:
        query = f"{separator}error={quote(error)}"
    return RedirectResponse(f"{path}{query}", status_code=303)


def require_auth(request: Request, db: Session):
    session = get_session(db, request.cookies.get("lunchcall_session"))
    if not session:
        raise HTTPException(status_code=401)
    request.state.auth_session = session
    return session


def require_csrf(session, csrf_token: str) -> None:
    if not csrf_token or csrf_token != session.csrf_token:
        raise HTTPException(status_code=403, detail="잘못된 요청입니다.")


def normalize_phone(phone: str) -> str | None:
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    if len(digits) != 11 or not digits.startswith("010"):
        raise ValueError("연락처는 010으로 시작하는 휴대전화 번호 11자리를 입력해 주세요.")
    return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"


def validate_sms_template(value: str) -> str:
    template = value.strip()
    if not template:
        raise ValueError("SMS 문구를 입력해 주세요.")
    if len(template) > 500:
        raise ValueError("SMS 문구는 500자 이내로 입력해 주세요.")

    allowed_fields = {"company_name", "date", "meal_count", "absent_count"}
    try:
        parsed = list(Formatter().parse(template))
    except ValueError as exc:
        raise ValueError("SMS 문구의 중괄호 형식을 확인해 주세요.") from exc

    fields = {field_name for _, field_name, _, _ in parsed if field_name}
    if not fields.issubset(allowed_fields):
        invalid_fields = ", ".join(sorted(fields - allowed_fields))
        raise ValueError(f"사용할 수 없는 SMS 변수입니다: {invalid_fields}")
    if "meal_count" not in fields:
        raise ValueError("SMS 문구에는 {meal_count} 변수가 필요합니다.")
    if any(format_spec or conversion for _, field_name, format_spec, conversion in parsed if field_name):
        raise ValueError("SMS 변수에는 서식 지정자를 사용할 수 없습니다.")
    return template


@app.exception_handler(401)
async def unauthorized_handler(request: Request, __: HTTPException):
    had_session_cookie = bool(request.cookies.get("lunchcall_session"))
    target = "/login?expired=1" if had_session_cookie else "/login"
    response = RedirectResponse(target, status_code=303)
    if had_session_cookie:
        response.delete_cookie("lunchcall_session")
    return response


def render_error_page(request: Request, status_code: int):
    error_content = {
        400: (
            "요청을 처리할 수 없습니다",
            "입력한 내용이나 요청 형식을 확인한 뒤 다시 시도해 주세요.",
        ),
        403: (
            "요청을 확인해 주세요",
            "페이지가 오래 열려 있었거나 유효하지 않은 요청입니다. 화면을 새로 연 뒤 다시 시도해 주세요.",
        ),
        404: (
            "페이지를 찾을 수 없습니다",
            "주소가 변경되었거나 존재하지 않는 페이지입니다.",
        ),
    }
    title, description = error_content.get(
        status_code,
        (
            "잠시 문제가 발생했습니다",
            "요청을 처리하는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        ),
    )

    auth_session = getattr(request.state, "auth_session", None)
    if auth_session is None and status_code < 500:
        try:
            with SessionLocal() as db:
                auth_session = get_session(
                    db, request.cookies.get("lunchcall_session")
                )
                if auth_session:
                    admin = auth_session.admin
                    csrf_token = auth_session.csrf_token
                else:
                    admin = None
                    csrf_token = None
        except Exception:
            admin = None
            csrf_token = None
    else:
        admin = auth_session.admin if auth_session else None
        csrf_token = auth_session.csrf_token if auth_session else None

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "admin": admin,
            "csrf_token": csrf_token,
            "status_code": status_code,
            "error_title": title,
            "error_description": description,
            "home_href": "/" if admin else "/login",
            "home_label": "오늘의 식수로 이동" if admin else "로그인 화면으로 이동",
        },
        status_code=status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    return render_error_page(request, exc.status_code)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled application error",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return render_error_page(request, 500)


@app.get("/health")
def health():
    return {"status": "ok", "time": seoul_now().isoformat()}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if get_session(db, request.cookies.get("lunchcall_session")):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": request.query_params.get("error"),
            "expired": request.query_params.get("expired") == "1",
            "settings": settings,
        },
    )


@app.post("/login")
def login(
    login_id: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = db.scalar(select(Admin).where(Admin.login_id == login_id.strip()))
    if not admin or not admin.is_active or not verify_password(admin.password_hash, password):
        return redirect("/login", error="아이디 또는 비밀번호가 올바르지 않습니다.")
    admin.last_login_at = seoul_now()
    raw_token, _ = create_session(db, admin)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "lunchcall_session",
        raw_token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@app.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    delete_session(db, request.cookies.get("lunchcall_session"))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("lunchcall_session")
    return response


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, db: Session = Depends(get_db)):
    require_auth(request, db)
    return RedirectResponse("/settings?section=account", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    section: str = "general",
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    allowed_sections = {"general", "sms", "departments", "holidays", "account"}
    active_section = section if section in allowed_sections else "general"
    department_rows = db.execute(
        select(Employee.department, func.count(Employee.id))
        .where(Employee.status != "DELETED")
        .group_by(Employee.department)
    ).all()
    department_counts = {department: count for department, count in department_rows}
    holiday_count = db.scalar(select(func.count(Holiday.id))) or 0
    last_holiday_sync = db.scalar(select(func.max(Holiday.synced_at)))
    service_settings = get_or_create_service_settings(db)
    preview_date = seoul_now()

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "admin": session.admin,
            "csrf_token": session.csrf_token,
            "active_section": active_section,
            "departments": settings.departments,
            "department_counts": department_counts,
            "holiday_count": holiday_count,
            "last_holiday_sync": last_holiday_sync,
            "preview_date": preview_date,
            "settings_sms_preview": build_sms_message(
                service_settings, preview_date.date(), 17, 3
            ),
            "service_settings": service_settings,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "settings": settings,
        },
    )


@app.post("/settings/general")
def general_settings_update(
    request: Request,
    csrf_token: str = Form(...),
    company_name: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    normalized_company_name = company_name.strip()
    if not normalized_company_name:
        return redirect("/settings?section=general", error="회사명을 입력해 주세요.")
    if len(normalized_company_name) > 30:
        return redirect(
            "/settings?section=general",
            error="회사명은 30자 이내로 입력해 주세요.",
        )
    service_settings = get_or_create_service_settings(db)
    service_settings.company_name = normalized_company_name
    db.commit()
    return redirect(
        "/settings?section=general",
        message="기본 설정을 저장했습니다.",
    )


@app.post("/settings/sms")
def sms_settings_update(
    request: Request,
    csrf_token: str = Form(...),
    company_name: str = Form(...),
    sms_recipient: str = Form(...),
    sms_template: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    normalized_company_name = company_name.strip()
    if not normalized_company_name:
        return redirect("/settings?section=sms", error="회사명을 입력해 주세요.")
    if len(normalized_company_name) > 30:
        return redirect(
            "/settings?section=sms",
            error="회사명은 30자 이내로 입력해 주세요.",
        )
    try:
        normalized_recipient = normalize_phone(sms_recipient)
        if normalized_recipient is None:
            raise ValueError("식당 수신 번호를 입력해 주세요.")
        normalized_template = validate_sms_template(sms_template)
    except ValueError as exc:
        return redirect("/settings?section=sms", error=str(exc))

    service_settings = get_or_create_service_settings(db)
    service_settings.company_name = normalized_company_name
    service_settings.sms_recipient = normalized_recipient
    service_settings.sms_template = normalized_template
    db.commit()
    return redirect("/settings?section=sms", message="SMS 설정을 저장했습니다.")


@app.post("/account")
def account_update(
    request: Request,
    csrf_token: str = Form(...),
    login_id: str = Form(...),
    current_password: str = Form(...),
    new_password: str = Form(""),
    new_password_confirm: str = Form(""),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    admin = session.admin
    account_path = "/settings?section=account"

    if not verify_password(admin.password_hash, current_password):
        return redirect(account_path, error="현재 비밀번호가 올바르지 않습니다.")

    normalized_login_id = login_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", normalized_login_id):
        return redirect(
            account_path,
            error="로그인 아이디는 영문, 숫자, 마침표, 밑줄, 하이픈으로 3~40자까지 입력해 주세요.",
        )

    duplicate_admin = db.scalar(
        select(Admin).where(
            Admin.login_id == normalized_login_id,
            Admin.id != admin.id,
        )
    )
    if duplicate_admin:
        return redirect(account_path, error="이미 사용 중인 로그인 아이디입니다.")

    if new_password or new_password_confirm:
        if len(new_password) < 12:
            return redirect(account_path, error="새 비밀번호는 12자 이상이어야 합니다.")
        if new_password != new_password_confirm:
            return redirect(account_path, error="새 비밀번호 확인이 일치하지 않습니다.")

    login_id_changed = admin.login_id != normalized_login_id
    password_changed = bool(new_password)
    if not login_id_changed and not password_changed:
        return redirect(account_path, error="변경할 아이디 또는 새 비밀번호를 입력해 주세요.")

    admin.login_id = normalized_login_id
    if password_changed:
        admin.password_hash = hash_password(new_password)
    db.commit()

    db.execute(delete(AdminSession).where(AdminSession.admin_id == admin.id))
    db.commit()
    raw_token, _ = create_session(db, admin)
    response = redirect(account_path, message="관리자 계정 정보를 변경했습니다.")
    response.set_cookie(
        "lunchcall_session",
        raw_token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    session = require_auth(request, db)
    now = seoul_now()
    confirm_opens_at = now.replace(
        hour=CONFIRM_TIME.hour,
        minute=CONFIRM_TIME.minute,
        second=0,
        microsecond=0,
    )
    confirmation_time_locked = (
        not settings.early_confirmation_enabled and now < confirm_opens_at
    )
    confirm_wait_seconds = (
        max(0, ceil((confirm_opens_at - now).total_seconds()))
        if confirmation_time_locked
        else 0
    )
    daily = get_or_create_daily_meal(db, now.date())
    summary = meal_summary(db, daily)
    service_settings = get_or_create_service_settings(db)
    logs = list(
        db.scalars(
            select(SmsLog)
            .where(SmsLog.daily_meal_id == daily.id)
            .order_by(SmsLog.attempt_number.desc())
        )
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "admin": session.admin,
            "csrf_token": session.csrf_token,
            "now": now,
            "confirmation_time_locked": confirmation_time_locked,
            "confirm_wait_seconds": confirm_wait_seconds,
            "daily": daily,
            "summary": summary,
            "draft_absent_names": [
                employee.name
                for employee in summary["employees"]
                if employee.id in summary["absent_ids"]
            ],
            "confirmed_absent_names": [
                absence.employee_name_snapshot for absence in daily.absences
            ],
            "sms_preview": build_sms_message(
                service_settings,
                now.date(),
                daily.meal_count
                if daily.status == "CONFIRMED" and daily.meal_count is not None
                else summary["meal_count"],
                daily.absent_count
                if daily.status == "CONFIRMED" and daily.absent_count is not None
                else summary["absent_count"],
            ),
            "holiday": holiday_name(db, now.date()),
            "logs": logs,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "settings": settings,
            "service_settings": service_settings,
        },
    )


@app.post("/absences/{employee_id}/toggle")
def absence_toggle(
    employee_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404)
    daily = get_or_create_daily_meal(db, seoul_now().date())
    try:
        is_absent = toggle_absence(db, daily, employee)
        message = f"{employee.name}님의 식사 상태를 변경했습니다."
        if wants_json:
            summary = meal_summary(db, daily)
            service_settings = get_or_create_service_settings(db)
            absent_names = [
                current.name
                for current in summary["employees"]
                if current.id in summary["absent_ids"]
            ]
            return JSONResponse(
                {
                    "message": message,
                    "employee_id": employee.id,
                    "employee_name": employee.name,
                    "is_absent": is_absent,
                    "active_count": summary["active_count"],
                    "absent_count": summary["absent_count"],
                    "meal_count": summary["meal_count"],
                    "absent_names": absent_names,
                    "sms_preview": build_sms_message(
                        service_settings,
                        daily.meal_date,
                        int(summary["meal_count"]),
                        int(summary["absent_count"]),
                    ),
                }
            )
        return redirect("/", message=message)
    except BusinessRuleError as exc:
        if wants_json:
            return JSONResponse({"error": str(exc)}, status_code=409)
        return redirect("/", error=str(exc))


@app.post("/confirm")
def confirm(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    daily = get_or_create_daily_meal(db, seoul_now().date())
    try:
        log = confirm_and_send(db, daily, session.admin.id)
        if log.status == "SUCCESS":
            return redirect("/", message="식수를 확정하고 문자를 전송했습니다.")
        return redirect("/", error="식수는 확정했지만 문자 전송에 실패했습니다.")
    except BusinessRuleError as exc:
        return redirect("/", error=str(exc))


@app.post("/sms/retry")
def retry_sms(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    daily = get_or_create_daily_meal(db, seoul_now().date())
    try:
        log = retry_failed_sms(db, daily)
        return redirect(
            "/",
            message="문자를 다시 전송했습니다." if log.status == "SUCCESS" else None,
            error="문자 재전송에 실패했습니다." if log.status == "FAILED" else None,
        )
    except BusinessRuleError as exc:
        return redirect("/", error=str(exc))


@app.post("/prototype/reset-today")
def prototype_reset_today(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    if not settings.prototype_tools_enabled:
        raise HTTPException(status_code=404, detail="페이지를 찾을 수 없습니다.")
    daily = get_or_create_daily_meal(db, seoul_now().date())
    try:
        reset_mock_confirmation(db, daily)
        return redirect(
            "/",
            message="오늘의 목업 확정을 초기화했습니다. 불참 선택은 유지됩니다.",
        )
    except BusinessRuleError as exc:
        return redirect("/", error=str(exc))


@app.get("/employees", response_class=HTMLResponse)
def employees_page(request: Request, db: Session = Depends(get_db)):
    session = require_auth(request, db)
    employees = list(
        db.scalars(
            select(Employee)
            .where(Employee.status != "DELETED")
            .order_by(Employee.status, Employee.name)
        )
    )
    return templates.TemplateResponse(
        request,
        "employees.html",
        {
            "admin": session.admin,
            "csrf_token": session.csrf_token,
            "employees": employees,
            "departments": settings.departments,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@app.post("/employees")
def employee_create(
    request: Request,
    csrf_token: str = Form(...),
    name: str = Form(...),
    department: str = Form(""),
    phone: str = Form(""),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    if not name.strip():
        return redirect("/employees", error="직원 이름을 입력해 주세요.")
    if department not in settings.departments:
        return redirect("/employees", error="목록에 있는 부서를 선택해 주세요.")
    try:
        normalized_phone = normalize_phone(phone)
    except ValueError as exc:
        return redirect("/employees", error=str(exc))
    db.add(
        Employee(
            name=name.strip(),
            department=department,
            phone=normalized_phone,
        )
    )
    db.commit()
    return redirect("/employees", message=f"{name.strip()}님을 추가했습니다.")


@app.post("/employees/{employee_id}/status")
def employee_status(
    employee_id: int,
    request: Request,
    csrf_token: str = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    if status not in {"ACTIVE", "LEAVE", "RETIRED"}:
        raise HTTPException(status_code=400)
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404)
    employee.status = status
    db.commit()
    return redirect("/employees", message=f"{employee.name}님의 상태를 변경했습니다.")


@app.post("/employees/{employee_id}/edit")
def employee_edit(
    employee_id: int,
    request: Request,
    csrf_token: str = Form(...),
    name: str = Form(...),
    department: str = Form(...),
    phone: str = Form(""),
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    employee = db.get(Employee, employee_id)
    if not employee or employee.status == "DELETED":
        raise HTTPException(status_code=404)

    normalized_name = name.strip()
    if not normalized_name:
        return redirect("/employees", error="직원 이름을 입력해 주세요.")
    if department not in settings.departments:
        return redirect("/employees", error="목록에 있는 부서를 선택해 주세요.")
    if status not in {"ACTIVE", "LEAVE", "RETIRED"}:
        return redirect("/employees", error="올바른 재직 상태를 선택해 주세요.")
    try:
        normalized_phone = normalize_phone(phone)
    except ValueError as exc:
        return redirect("/employees", error=str(exc))

    employee.name = normalized_name
    employee.department = department
    employee.phone = normalized_phone
    employee.status = status
    db.commit()
    return redirect("/employees", message=f"{employee.name}님의 정보를 수정했습니다.")


@app.post("/employees/{employee_id}/delete")
def employee_delete(
    employee_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    employee = db.get(Employee, employee_id)
    if not employee or employee.status == "DELETED":
        raise HTTPException(status_code=404)
    employee.status = "DELETED"
    db.commit()
    return redirect(
        "/employees",
        message=f"{employee.name}님을 직원 목록에서 삭제했습니다.",
    )


@app.get("/history", response_class=HTMLResponse)
def history(request: Request, db: Session = Depends(get_db)):
    session = require_auth(request, db)
    meals = list(
        db.scalars(
            select(DailyMeal)
            .where(DailyMeal.status == "CONFIRMED")
            .order_by(DailyMeal.meal_date.desc())
        )
    )
    return templates.TemplateResponse(
        request,
        "history.html",
        {"admin": session.admin, "csrf_token": session.csrf_token, "meals": meals},
    )


@app.post("/holidays/sync")
def holidays_sync(
    request: Request,
    csrf_token: str = Form(...),
    return_to: str = Form("/"),
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    redirect_path = (
        return_to
        if return_to in {"/", "/settings?section=holidays"}
        else "/"
    )
    try:
        count = sync_holidays(db, seoul_now().year)
        return redirect(redirect_path, message=f"공휴일 {count}건을 동기화했습니다.")
    except (BusinessRuleError, httpx.HTTPError, ValueError, KeyError) as exc:
        return redirect(redirect_path, error=f"공휴일 동기화 실패: {exc}")
