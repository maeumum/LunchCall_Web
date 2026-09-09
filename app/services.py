from __future__ import annotations

import secrets
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .config import settings
from .models import DailyMeal, Employee, Holiday, MealAbsence, SmsLog

SEOUL = ZoneInfo("Asia/Seoul")
CONFIRM_TIME = time(9, 50)


class BusinessRuleError(Exception):
    pass


def seoul_now() -> datetime:
    return datetime.now(SEOUL)


def get_or_create_daily_meal(db: Session, meal_date: date) -> DailyMeal:
    daily = db.scalar(select(DailyMeal).where(DailyMeal.meal_date == meal_date))
    if daily:
        return daily
    daily = DailyMeal(meal_date=meal_date)
    db.add(daily)
    db.commit()
    db.refresh(daily)
    return daily


def holiday_name(db: Session, target: date) -> str | None:
    if target.weekday() == 5:
        return "토요일"
    if target.weekday() == 6:
        return "일요일"
    holiday = db.scalar(select(Holiday).where(Holiday.holiday_date == target))
    return holiday.name if holiday else None


def meal_summary(db: Session, daily: DailyMeal) -> dict[str, object]:
    active_employees = list(
        db.scalars(
            select(Employee)
            .where(Employee.status == "ACTIVE")
            .order_by(Employee.name)
        )
    )
    active_ids = {employee.id for employee in active_employees}
    absence_rows = list(
        db.scalars(
            select(MealAbsence).where(MealAbsence.daily_meal_id == daily.id)
        )
    )
    absent_ids = {row.employee_id for row in absence_rows if row.employee_id in active_ids}
    return {
        "employees": active_employees,
        "absent_ids": absent_ids,
        "active_count": len(active_employees),
        "absent_count": len(absent_ids),
        "meal_count": len(active_employees) - len(absent_ids),
    }


def toggle_absence(db: Session, daily: DailyMeal, employee: Employee) -> bool:
    if daily.status != "DRAFT":
        raise BusinessRuleError("이미 확정된 식수는 수정할 수 없습니다.")
    if employee.status != "ACTIVE":
        raise BusinessRuleError("재직 중인 직원만 변경할 수 있습니다.")
    existing = db.scalar(
        select(MealAbsence).where(
            MealAbsence.daily_meal_id == daily.id,
            MealAbsence.employee_id == employee.id,
        )
    )
    if existing:
        db.delete(existing)
        is_absent = False
    else:
        db.add(
            MealAbsence(
                daily_meal_id=daily.id,
                employee_id=employee.id,
                employee_name_snapshot=employee.name,
            )
        )
        is_absent = True
    db.commit()
    return is_absent


def build_sms_message(meal_date: date, meal_count: int) -> str:
    return (
        f"[{settings.sms_company_name}] {meal_date.year}년 {meal_date.month}월 "
        f"{meal_date.day}일 식사 인원은 {meal_count}명입니다."
    )


def send_sms(db: Session, daily: DailyMeal, attempt_number: int) -> SmsLog:
    message = build_sms_message(daily.meal_date, daily.meal_count or 0)
    log = SmsLog(
        daily_meal_id=daily.id,
        attempt_number=attempt_number,
        recipient=settings.sms_recipient,
        message=message,
        status="PENDING",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    if settings.sms_mode == "mock":
        log.status = "SUCCESS"
        log.provider_message_id = f"mock-{secrets.token_hex(6)}"
        log.sent_at = seoul_now()
    else:
        log.status = "FAILED"
        log.error_message = "실제 SMS 업체가 아직 설정되지 않았습니다."
    db.commit()
    db.refresh(log)
    return log


def confirm_and_send(db: Session, daily: DailyMeal, admin_id: int) -> SmsLog:
    now = seoul_now()
    reason = holiday_name(db, now.date())
    if reason:
        raise BusinessRuleError(f"오늘은 {reason}이므로 식수를 확정할 수 없습니다.")
    if now.time() < CONFIRM_TIME and not settings.allow_early_confirm:
        raise BusinessRuleError("오전 9시 50분부터 최종 확정할 수 있습니다.")

    summary = meal_summary(db, daily)
    result = db.execute(
        update(DailyMeal)
        .where(DailyMeal.id == daily.id, DailyMeal.status == "DRAFT")
        .values(
            status="CONFIRMED",
            active_count=summary["active_count"],
            absent_count=summary["absent_count"],
            meal_count=summary["meal_count"],
            confirmed_by=admin_id,
            confirmed_at=now,
            updated_at=now,
        )
    )
    db.commit()
    if result.rowcount != 1:
        raise BusinessRuleError("이미 확정된 식수입니다.")
    db.refresh(daily)
    return send_sms(db, daily, 1)


def retry_failed_sms(db: Session, daily: DailyMeal) -> SmsLog:
    latest = db.scalar(
        select(SmsLog)
        .where(SmsLog.daily_meal_id == daily.id)
        .order_by(SmsLog.attempt_number.desc())
    )
    if not latest or latest.status != "FAILED":
        raise BusinessRuleError("실패한 문자만 재전송할 수 있습니다.")
    return send_sms(db, daily, latest.attempt_number + 1)


def reset_mock_confirmation(db: Session, daily: DailyMeal) -> None:
    if settings.app_env != "development" or settings.sms_mode != "mock":
        raise BusinessRuleError("목업 환경에서만 오늘 확정을 초기화할 수 있습니다.")
    if daily.status != "CONFIRMED":
        raise BusinessRuleError("오늘은 아직 확정되지 않았습니다.")

    db.execute(delete(SmsLog).where(SmsLog.daily_meal_id == daily.id))
    daily.status = "DRAFT"
    daily.active_count = None
    daily.absent_count = None
    daily.meal_count = None
    daily.confirmed_by = None
    daily.confirmed_at = None
    db.commit()


def sync_holidays(db: Session, year: int) -> int:
    if not settings.holiday_api_key:
        raise BusinessRuleError("HOLIDAY_API_KEY가 설정되지 않았습니다.")
    response = httpx.get(
        "https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo",
        params={
            "serviceKey": settings.holiday_api_key,
            "solYear": str(year),
            "numOfRows": "100",
            "_type": "json",
        },
        timeout=15,
    )
    response.raise_for_status()
    body = response.json().get("response", {}).get("body", {})
    items = body.get("items", {}).get("item", [])
    if isinstance(items, dict):
        items = [items]
    count = 0
    for item in items:
        if item.get("isHoliday") != "Y":
            continue
        raw = str(item["locdate"])
        target = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        holiday = db.scalar(select(Holiday).where(Holiday.holiday_date == target))
        if holiday:
            holiday.name = item["dateName"]
            holiday.synced_at = seoul_now()
        else:
            db.add(
                Holiday(
                    holiday_date=target,
                    name=item["dateName"],
                    source="KASI",
                    synced_at=seoul_now(),
                )
            )
        count += 1
    db.commit()
    return count
