"""Password authentication with revocable, opaque cookie sessions."""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from threading import Lock
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.models import Customer, AuthSession
from app.db.session import get_db

COOKIE = "homeflow_session"

def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${value}"

def password_matches(password: str, stored: str) -> bool:
    _, salt, value = stored.split("$")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, value)

def check_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("origin") not in settings.cors_list:
        raise HTTPException(403, "Request origin is not allowed")

def current_customer(request: Request, db: Session = Depends(get_db)) -> Customer:
    check_origin(request)
    token = request.cookies.get(COOKIE, "")
    session = db.get(AuthSession, digest(token)) if token else None
    if not session or session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Please log in to continue")
    customer = db.get(Customer, session.customer_id)
    if not customer:
        raise HTTPException(401, "Please log in to continue")
    return customer

