"""Cookie-based account authentication with revocable opaque sessions."""
from datetime import datetime, timedelta, timezone
from typing import Literal
import hashlib
import hmac
import re
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_db
from app.models.chat import AuthSession, ChatArtifact, ChatSession, ChatUser

router = APIRouter(prefix="/auth", tags=["authentication"])
COOKIE_NAME = "lenny_session"
CSRF_COOKIE = "lenny_csrf"


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Enter your name")
        return normalized

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value


class LoginCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Password cannot be blank")
        return value


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    display_name: str | None
    created_at: datetime
    appearance_mode: Literal["light", "dark"]
    pastel_palette: Literal["blue", "lavender", "mint", "pink", "peach", "cream"]


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Enter your name")
        return normalized


class AccountDeletion(BaseModel):
    confirmation: str
    password: str = Field(min_length=1, max_length=256)


class AppearanceUpdate(BaseModel):
    appearance_mode: Literal["light", "dark"]
    pastel_palette: Literal["blue", "lavender", "mint", "pink", "peach", "cream"]


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"


def _verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt_hex, expected_hex = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=64)
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in {item.rstrip("/") for item in get_settings().cors_origins}:
        raise HTTPException(status_code=403, detail="Request origin is not allowed")


def _set_login_cookies(response: Response, db: Session, user: ChatUser, request: Request) -> None:
    settings = get_settings()
    old_token = request.cookies.get(COOKIE_NAME)
    old_session = db.get(AuthSession, _token_hash(old_token)) if old_token else None
    if old_session is not None:
        db.delete(old_session)
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    db.add(AuthSession(
        token_hash=_token_hash(token), user_id=user.id,
        expires_at=now + timedelta(days=settings.auth_session_days), created_at=now,
    ))
    db.commit()
    cookie_options = {
        "max_age": settings.auth_session_days * 86400,
        "secure": settings.auth_cookie_secure or request.url.scheme == "https",
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(COOKIE_NAME, token, httponly=True, **cookie_options)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **cookie_options)
    response.headers["X-CSRF-Token"] = csrf


def get_current_user(request: Request, db: Session = Depends(get_db)) -> ChatUser:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    now = datetime.now(timezone.utc)
    expires_at = auth_session.expires_at if auth_session else now
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if auth_session is None or expires_at.astimezone(timezone.utc) <= now:
        raise HTTPException(status_code=401, detail="Your session expired. Sign in again")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
        csrf_header = request.headers.get("x-csrf-token", "")
        if not csrf_cookie or not hmac.compare_digest(csrf_cookie, csrf_header):
            raise HTTPException(status_code=403, detail="Request verification failed. Refresh and try again")
        _check_origin(request)
    user = db.get(ChatUser, auth_session.user_id)
    if user is None or not user.email or not user.password_hash:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return user


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: Credentials, request: Request, db: Session = Depends(get_db)):
    _check_origin(request)
    if db.scalar(select(ChatUser.id).where(ChatUser.email == payload.email)):
        raise HTTPException(status_code=409, detail="Unable to create an account with these details. Try signing in or use another email.")
    user = ChatUser(
        id=str(uuid4()), email=payload.email,
        password_hash=_password_hash(payload.password),
        display_name=(payload.display_name or payload.email.split("@", 1)[0]).strip(),
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to create an account with these details. Try signing in or use another email.") from exc
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginCredentials, request: Request, response: Response, db: Session = Depends(get_db)):
    _check_origin(request)
    user = db.scalar(select(ChatUser).where(ChatUser.email == payload.email))
    # Verify a fixed dummy scrypt hash for unknown emails to reduce timing differences.
    if user is None:
        _verify_password(payload.password, "scrypt$16384$8$1$00112233445566778899aabbccddeeff$" + "00" * 64)
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if not _verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    _set_login_cookies(response, db, user, request)
    return user


@router.get("/me", response_model=UserOut)
def me(request: Request, response: Response, user: ChatUser = Depends(get_current_user)):
    csrf = request.cookies.get(CSRF_COOKIE)
    if csrf:
        response.headers["X-CSRF-Token"] = csrf
    return user


@router.patch("/me", response_model=UserOut)
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db), user: ChatUser = Depends(get_current_user)):
    user.display_name = payload.display_name
    db.commit()
    db.refresh(user)
    return user


@router.patch("/preferences", response_model=UserOut)
def update_preferences(payload: AppearanceUpdate, db: Session = Depends(get_db), user: ChatUser = Depends(get_current_user)):
    user.appearance_mode = payload.appearance_mode
    user.pastel_palette = payload.pastel_palette
    db.commit()
    db.refresh(user)
    return user


@router.delete("/account", status_code=204)
def delete_account(payload: AccountDeletion, request: Request, db: Session = Depends(get_db), user: ChatUser = Depends(get_current_user)):
    """Delete only this authenticated account and its owned workspace data."""
    if payload.confirmation != "DELETE" or not _verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Confirmation or password is incorrect")

    # Remove explicit ownership records first. ChatSession's ORM cascade removes
    # its messages; shared transcript/vector data has no relationship here.
    db.execute(delete(ChatArtifact).where(ChatArtifact.user_id == user.id))
    for chat_session in db.scalars(select(ChatSession).where(ChatSession.user_id == user.id)).all():
        db.delete(chat_session)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.delete(user)
    db.commit()

    settings = get_settings()
    response = Response(status_code=204)
    secure = settings.auth_cookie_secure or request.url.scheme == "https"
    response.delete_cookie(COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")
    return response


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)):
    """Revoke the caller's session when valid and always clear stale cookies."""
    _check_origin(request)
    token = request.cookies.get(COOKIE_NAME, "")
    session = db.get(AuthSession, _token_hash(token)) if token else None
    if session:
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at.astimezone(timezone.utc) > datetime.now(timezone.utc):
            csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
            csrf_header = request.headers.get("x-csrf-token", "")
            if not csrf_cookie or not hmac.compare_digest(csrf_cookie, csrf_header):
                raise HTTPException(status_code=403, detail="Request verification failed. Refresh and try again")
        db.delete(session)
        db.commit()
    settings = get_settings()
    logged_out = Response(status_code=204)
    secure = settings.auth_cookie_secure or request.url.scheme == "https"
    logged_out.delete_cookie(COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="lax")
    logged_out.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="lax")
    return logged_out
