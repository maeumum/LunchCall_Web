from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    login_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    admin: Mapped[Admin] = relationship()


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    department: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DailyMeal(Base):
    __tablename__ = "daily_meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    active_count: Mapped[int | None] = mapped_column(Integer)
    absent_count: Mapped[int | None] = mapped_column(Integer)
    meal_count: Mapped[int | None] = mapped_column(Integer)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    absences: Mapped[list[MealAbsence]] = relationship(
        back_populates="daily_meal", cascade="all, delete-orphan"
    )
    sms_logs: Mapped[list[SmsLog]] = relationship(back_populates="daily_meal")
    confirmer: Mapped[Admin | None] = relationship()


class MealAbsence(Base):
    __tablename__ = "meal_absences"
    __table_args__ = (UniqueConstraint("daily_meal_id", "employee_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_meal_id: Mapped[int] = mapped_column(ForeignKey("daily_meals.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))
    employee_name_snapshot: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    daily_meal: Mapped[DailyMeal] = relationship(back_populates="absences")
    employee: Mapped[Employee] = relationship()


class SmsLog(Base):
    __tablename__ = "sms_logs"
    __table_args__ = (UniqueConstraint("daily_meal_id", "attempt_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    daily_meal_id: Mapped[int] = mapped_column(ForeignKey("daily_meals.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    recipient: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    provider_message_id: Mapped[str | None] = mapped_column(String(120))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    daily_meal: Mapped[DailyMeal] = relationship(back_populates="sms_logs")


class Holiday(Base):
    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(80), default="KASI")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

