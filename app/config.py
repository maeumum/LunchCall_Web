from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./lunchcall.db")
    admin_login_id: str = os.getenv("ADMIN_LOGIN_ID", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "LunchCall123!")
    admin_display_name: str = os.getenv("ADMIN_DISPLAY_NAME", "식수 관리자")
    session_hours: int = int(os.getenv("SESSION_HOURS", "8"))
    sms_mode: str = os.getenv("SMS_MODE", "mock")
    sms_recipient: str = os.getenv("SMS_RECIPIENT", "010-0000-0000")
    sms_company_name: str = os.getenv("SMS_COMPANY_NAME", "회사명")
    holiday_api_key: str = os.getenv("HOLIDAY_API_KEY", "")
    allow_early_confirm: bool = _as_bool(
        os.getenv("PROTOTYPE_ALLOW_EARLY_CONFIRM"), False
    )

    @property
    def cookie_secure(self) -> bool:
        return self.app_env.lower() == "production"


settings = Settings()
