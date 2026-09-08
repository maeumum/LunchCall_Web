from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Admin, AdminSession

password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, admin: Admin) -> tuple[str, AdminSession]:
    raw_token = secrets.token_urlsafe(32)
    session = AdminSession(
        token_hash=_token_hash(raw_token),
        csrf_token=secrets.token_urlsafe(24),
        admin_id=admin.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_hours),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw_token, session


def get_session(db: Session, raw_token: str | None) -> AdminSession | None:
    if not raw_token:
        return None
    session = db.scalar(
        select(AdminSession).where(AdminSession.token_hash == _token_hash(raw_token))
    )
    if not session:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc) or not session.admin.is_active:
        db.delete(session)
        db.commit()
        return None
    return session


def delete_session(db: Session, raw_token: str | None) -> None:
    if raw_token:
        db.execute(
            delete(AdminSession).where(AdminSession.token_hash == _token_hash(raw_token))
        )
        db.commit()

