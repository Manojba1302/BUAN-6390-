"""Registration, login, logout, and emailed password recovery."""
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import COOKIE, check_origin, current_customer, digest, password_hash, password_matches
from app.db.models import AuthAccount, AuthSession, Customer, PasswordReset
from app.db.session import get_db

# Rate-limit public authentication operations per direct client IP.
from collections import OrderedDict
from threading import Lock
from time import monotonic
_auth_hits = OrderedDict()
_auth_lock = Lock()

def limit_auth(request: Request):
    if request.method != "POST":
        return
    key = request.client.host if request.client else "unknown"
    now = monotonic()
    with _auth_lock:
        recent = [t for t in _auth_hits.pop(key, []) if t > now - 60]
        if len(recent) >= 15:
            _auth_hits[key] = recent
            raise HTTPException(429, "Too many requests. Please wait a minute.")
        _auth_hits[key] = recent + [now]
        while len(_auth_hits) > 10000:
            _auth_hits.popitem(last=False)



router = APIRouter(prefix="/auth", tags=["authentication"], dependencies=[Depends(check_origin), Depends(limit_auth)])

class EmailBody(BaseModel):
    email: str = Field(max_length=254)
    @field_validator("email")
    @classmethod
    def normalize(cls, value):
        value = value.strip().lower()
        if "@" not in value or any(c.isspace() for c in value) or value.count("@") != 1:
            raise ValueError("Enter a valid email")
        return value

class Credentials(EmailBody):
    password: str = Field(min_length=1, max_length=128)

def validate_new_password(value):
    if not all(re.search(pattern, value) for pattern in (r"[A-Z]", r"[a-z]", r"[0-9]", r"[!-/:-@\[-`{-~]")):
        raise ValueError("Use uppercase, lowercase, a number and a symbol such as @")
    return value

class Registration(Credentials):
    password: str = Field(min_length=9, max_length=128)
    _password_policy = field_validator("password")(validate_new_password)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)

class ResetBody(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=9, max_length=128)
    _password_policy = field_validator("password")(validate_new_password)

def profile(customer):
    return {"customer_id": str(customer.customer_id), "email": customer.email,
            "first_name": customer.first_name, "last_name": customer.last_name}

def establish(db, response, customer):
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=digest(token), customer_id=customer.customer_id,
                       expires_at=datetime.now(timezone.utc) + timedelta(hours=8)))
    db.commit()
    response.set_cookie(COOKIE, token, max_age=28800, httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return profile(customer)

@router.post("/register", status_code=201)
def register(body: Registration, response: Response, db: Session = Depends(get_db)):
    # Never allow public registration to claim existing email-only demo data.
    if db.scalar(select(Customer).where(Customer.email == body.email)):
        raise HTTPException(409, "Account cannot be created with this email. Log in or contact support.")
    customer = Customer(email=body.email, first_name=body.first_name.strip(), last_name=body.last_name.strip())
    db.add(customer)
    db.flush()
    db.add(AuthAccount(customer_id=customer.customer_id, email=body.email, password_hash=password_hash(body.password)))
    try:
        return establish(db, response, customer)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Account cannot be created with this email")

@router.post("/login")
def login(body: Credentials, response: Response, db: Session = Depends(get_db)):
    account = db.scalar(select(AuthAccount).where(AuthAccount.email == body.email).with_for_update())
    now = datetime.now(timezone.utc)
    if not account:
        password_hash(body.password)  # Comparable password work for unknown accounts.
        raise HTTPException(401, "Email or password is incorrect")
    if account.locked_until and account.locked_until.replace(tzinfo=timezone.utc) > now:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    if not password_matches(body.password, account.password_hash):
        account.failed_attempts += 1
        if account.failed_attempts >= 5:
            account.locked_until = now + timedelta(minutes=15)
        db.commit()
        raise HTTPException(401, "Email or password is incorrect")
    account.failed_attempts = 0
    account.locked_until = None
    return establish(db, response, db.get(Customer, account.customer_id))

@router.get("/me")
def me(response: Response, customer: Customer = Depends(current_customer)):
    response.headers["Cache-Control"] = "no-store"
    return profile(customer)

@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(request.cookies.get(COOKIE, ""))))
    db.commit()
    response.delete_cookie(COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")
    return {"message": "Logged out"}

@router.post("/forgot-password")
def forgot(body: EmailBody, db: Session = Depends(get_db)):
    account = db.scalar(select(AuthAccount).where(AuthAccount.email == body.email))
    if account:
        now = datetime.now(timezone.utc)
        # Limit each account to one email per minute, including consumed links.
        recent = db.scalar(select(PasswordReset).where(PasswordReset.customer_id == account.customer_id,
                            PasswordReset.expires_at > now + timedelta(minutes=29)))
        if not recent:
            send_reset(db, account, now)
    return {"message": "If an account exists, a password reset link will be emailed to you."}

def send_reset(db, account, now):
    token = secrets.token_urlsafe(32)
    message = EmailMessage()
    message["Subject"] = "Reset your HomeFlow password"
    message["From"] = settings.smtp_from
    message["To"] = account.email
    message.set_content(f"Reset your password within 30 minutes:\n{settings.frontend_url}/#reset={token}\nIgnore this email if you did not request it.")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise HTTPException(503, "Password recovery email is temporarily unavailable")
    db.add(PasswordReset(token_hash=digest(token), customer_id=account.customer_id,
                         expires_at=now + timedelta(minutes=30)))
    db.commit()

@router.post("/reset-password")
def reset(body: ResetBody, db: Session = Depends(get_db)):
    link = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == digest(body.token)).with_for_update())
    if not link or link.used or link.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(400, "Reset link is invalid or expired. Request a new one.")
    account = db.get(AuthAccount, link.customer_id)
    account.password_hash = password_hash(body.password)
    account.failed_attempts = 0
    account.locked_until = None
    db.execute(delete(AuthSession).where(AuthSession.customer_id == link.customer_id))
    links = db.scalars(select(PasswordReset).where(PasswordReset.customer_id == link.customer_id)).all()
    for item in links:
        item.used = True
    db.commit()
    return {"message": "Password updated. Log in with your new password."}


