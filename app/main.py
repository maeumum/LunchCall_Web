from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
import re
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import Admin, AdminSession, DailyMeal, Employee, Holiday, SmsLog
from .security import create_session, delete_session, get_session, hash_password, verify_password
from .services import (
    BusinessRuleError,
    confirm_and_send,
    get_or_create_daily_meal,
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="LunchCall", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def redirect(path: str, message: str | None = None, error: str | None = None):
    query = ""
    if message:
        query = f"?message={quote(message)}"
    elif error:
        query = f"?error={quote(error)}"
    return RedirectResponse(f"{path}{query}", status_code=303)


def require_auth(request: Request, db: Session):
    session = get_session(db, request.cookies.get("lunchcall_session"))
    if not session:
        raise HTTPException(status_code=401)
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


@app.exception_handler(401)
async def unauthorized_handler(_: Request, __: HTTPException):
    return RedirectResponse("/login", status_code=303)


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
        {"error": request.query_params.get("error"), "settings": settings},
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
    session = require_auth(request, db)
    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "admin": session.admin,
            "csrf_token": session.csrf_token,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


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

    if not verify_password(admin.password_hash, current_password):
        return redirect("/account", error="현재 비밀번호가 올바르지 않습니다.")

    normalized_login_id = login_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", normalized_login_id):
        return redirect(
            "/account",
            error="로그인 아이디는 영문, 숫자, 마침표, 밑줄, 하이픈으로 3~40자까지 입력해 주세요.",
        )

    duplicate_admin = db.scalar(
        select(Admin).where(
            Admin.login_id == normalized_login_id,
            Admin.id != admin.id,
        )
    )
    if duplicate_admin:
        return redirect("/account", error="이미 사용 중인 로그인 아이디입니다.")

    if new_password or new_password_confirm:
        if len(new_password) < 12:
            return redirect("/account", error="새 비밀번호는 12자 이상이어야 합니다.")
        if new_password != new_password_confirm:
            return redirect("/account", error="새 비밀번호 확인이 일치하지 않습니다.")

    login_id_changed = admin.login_id != normalized_login_id
    password_changed = bool(new_password)
    if not login_id_changed and not password_changed:
        return redirect("/account", error="변경할 아이디 또는 새 비밀번호를 입력해 주세요.")

    admin.login_id = normalized_login_id
    if password_changed:
        admin.password_hash = hash_password(new_password)
    db.commit()

    db.execute(delete(AdminSession).where(AdminSession.admin_id == admin.id))
    db.commit()
    raw_token, _ = create_session(db, admin)
    response = redirect("/account", message="관리자 계정 정보를 변경했습니다.")
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
    daily = get_or_create_daily_meal(db, now.date())
    summary = meal_summary(db, daily)
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
            "daily": daily,
            "summary": summary,
            "confirmed_absent_names": [
                absence.employee_name_snapshot for absence in daily.absences
            ],
            "holiday": holiday_name(db, now.date()),
            "logs": logs,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "settings": settings,
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
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404)
    daily = get_or_create_daily_meal(db, seoul_now().date())
    try:
        toggle_absence(db, daily, employee)
        return redirect("/", message=f"{employee.name}님의 식사 상태를 변경했습니다.")
    except BusinessRuleError as exc:
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
    db: Session = Depends(get_db),
):
    session = require_auth(request, db)
    require_csrf(session, csrf_token)
    try:
        count = sync_holidays(db, seoul_now().year)
        return redirect("/", message=f"공휴일 {count}건을 동기화했습니다.")
    except (BusinessRuleError, httpx.HTTPError, ValueError, KeyError) as exc:
        return redirect("/", error=f"공휴일 동기화 실패: {exc}")
