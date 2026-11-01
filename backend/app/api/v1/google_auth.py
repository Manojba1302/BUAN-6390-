"""Google Identity Services: verified ID tokens and single-use browser challenges."""
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from google.auth.exceptions import TransportError
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.v1.auth import establish, limit_auth
from app.core.config import settings
from app.core.security import check_origin, digest, password_matches
from app.db.models import AuthAccount, Customer, GoogleChallenge, GoogleIdentity
from app.db.session import get_db

router = APIRouter(prefix="/auth/google", dependencies=[Depends(check_origin), Depends(limit_auth)])
CHALLENGE_COOKIE = "homeflow_google_challenge"

class GoogleBody(BaseModel):
    credential: str = Field(min_length=1, max_length=12000)
    password: str = Field(default="", max_length=128)

@router.get("/config")
def configuration(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"client_id": settings.google_client_id}

@router.post("/challenge")
def challenge(response: Response, db: Session = Depends(get_db)):
    require_config()
    now, token = datetime.now(timezone.utc), secrets.token_urlsafe(32)
    db.execute(delete(GoogleChallenge).where(GoogleChallenge.expires_at <= now))
    db.add(GoogleChallenge(token_hash=digest(token), expires_at=now + timedelta(minutes=5)))
    db.commit()
    response.set_cookie(CHALLENGE_COOKIE, token, max_age=300, httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"nonce": digest(token)}

def require_config():
    if not settings.google_client_id:
        raise HTTPException(503, "Google sign-in is not configured yet. Use email and password.")

def verify(credential, nonce):
    try:
        claims = id_token.verify_oauth2_token(credential, GoogleRequest(), settings.google_client_id)
    except TransportError:
        raise HTTPException(503, "Google verification is temporarily unavailable. Please retry.")
    except ValueError:
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.")
    if claims.get("nonce") != nonce or claims.get("email_verified") is not True:
        raise HTTPException(401, "Google sign-in could not be verified. Please try again.")
    if not isinstance(claims.get("sub"), str) or not claims["sub"] or not isinstance(claims.get("email"), str) or "@" not in claims["email"]:
        raise HTTPException(401, "Google did not provide a verified identity.")
    return claims

def consume(db, request):
    token = request.cookies.get(CHALLENGE_COOKIE, "")
    nonce = digest(token)
    expiry = db.execute(delete(GoogleChallenge).where(GoogleChallenge.token_hash == nonce)
                        .returning(GoogleChallenge.expires_at)).scalar_one_or_none()
    db.commit()  # Consume before external verification: retries need a fresh challenge.
    if not token or not expiry or expiry.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Google sign-in expired. Please try again.")
    return nonce

def customer_for(db, claims, password):
    identity = db.get(GoogleIdentity, claims["sub"])
    if identity:
        return db.get(Customer, identity.customer_id)
    email = claims["email"].strip().lower()
    customer = db.scalar(select(Customer).where(Customer.email == email))
    if customer:
        prove_existing(db, customer, password)
    else:
        customer = Customer(email=email, first_name=str(claims.get("given_name") or "")[:80],
                            last_name=str(claims.get("family_name") or "")[:80])
        db.add(customer)
        db.flush()
    db.add(GoogleIdentity(subject=claims["sub"], customer_id=customer.customer_id))
    return customer

def prove_existing(db, customer, password):
    account = db.scalar(select(AuthAccount).where(AuthAccount.customer_id == customer.customer_id).with_for_update())
    if not account:
        raise HTTPException(409, "This email belongs to an existing HomeFlow profile without a password. Contact support to enable sign-in.")
    if not password:
        raise HTTPException(409, "Enter your existing HomeFlow password below, then select Google again to link your account.")
    now = datetime.now(timezone.utc)
    if account.locked_until and account.locked_until.replace(tzinfo=timezone.utc) > now:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    if not password_matches(password, account.password_hash):
        account.failed_attempts += 1
        if account.failed_attempts >= 5:
            account.locked_until = now + timedelta(minutes=15)
        db.commit()
        raise HTTPException(401, "HomeFlow password is incorrect.")
    account.failed_attempts, account.locked_until = 0, None

@router.post("/login")
def login(body: GoogleBody, request: Request, response: Response, db: Session = Depends(get_db)):
    require_config()
    claims = verify(body.credential, consume(db, request))
    try:
        customer = customer_for(db, claims, body.password)
        response.delete_cookie(CHALLENGE_COOKIE, path="/")
        return establish(db, response, customer)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Account linking could not be completed. Sign in with your existing method.")
