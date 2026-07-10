import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.auth.email import send_verification_email
from app.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    AuthResponse,
    UserInfo,
    SendCodeRequest,
    SendCodeResponse,
)
from app.auth.security import hash_password, verify_password, create_access_token
from app.config import get_settings
from app.dependencies import get_current_user, _check_access
from app.db.database import get_db
from app.db.models import User, EmailVerificationCode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_code(code: str, code_hash: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode("utf-8"), code_hash.encode("utf-8"))
    except ValueError:
        return False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/send-code", response_model=SendCodeResponse)
async def send_code(req: SendCodeRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    now = _utcnow()

    # Rate limit: resend cooldown per email
    latest = (
        db.query(EmailVerificationCode)
        .filter(EmailVerificationCode.email == req.email)
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )
    if latest is not None:
        created = latest.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (now - created).total_seconds()
        if elapsed < settings.VERIFY_CODE_RESEND_SECONDS:
            wait = int(settings.VERIFY_CODE_RESEND_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests, please try again in {wait} seconds",
            )

    # Generate verification code
    digits = settings.VERIFY_CODE_LENGTH
    code = "".join(secrets.choice("0123456789") for _ in range(digits))

    record = EmailVerificationCode(
        id=str(uuid.uuid4()),
        email=req.email,
        code_hash=_hash_code(code),
        attempts=0,
        expires_at=now + timedelta(minutes=settings.VERIFY_CODE_EXPIRE_MINUTES),
        consumed=False,
        created_at=now,
    )
    db.add(record)
    db.commit()

    # Send email (roll back the record on failure to avoid a stored code that was never delivered)
    try:
        await send_verification_email(req.email, code)
    except RuntimeError as e:
        logger.warning("send-code email failed for %s: %s", req.email, e)
        db.delete(record)
        db.commit()
        raise HTTPException(
            status_code=503, detail="Failed to send verification email, please try again later"
        )

    return SendCodeResponse(
        message="Verification code sent, please check your email",
        expire_seconds=settings.VERIFY_CODE_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    now = _utcnow()

    existing = db.query(User).filter(User.email == req.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Validate verification code: get the latest unconsumed record for this email
    record = (
        db.query(EmailVerificationCode)
        .filter(
            EmailVerificationCode.email == req.email,
            EmailVerificationCode.consumed == False,  # noqa: E712
        )
        .order_by(EmailVerificationCode.created_at.desc())
        .first()
    )

    if record is None:
        raise HTTPException(status_code=400, detail="Please request a verification code first")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        raise HTTPException(
            status_code=400, detail="Verification code expired, please request a new one"
        )

    # Increment attempt count
    record.attempts = (record.attempts or 0) + 1
    if record.attempts > settings.VERIFY_CODE_MAX_ATTEMPTS:
        record.consumed = True
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect attempts, please request a new code",
        )

    if not _verify_code(req.code, record.code_hash):
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid verification code")

    # Verification passed, mark as consumed
    record.consumed = True

    user = User(
        id=str(uuid.uuid4()),
        email=req.email,
        password_hash=hash_password(req.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        user=UserInfo(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            is_whitelisted=user.is_whitelisted,
        ),
    )


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _check_access(user)

    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        user=UserInfo(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            is_whitelisted=user.is_whitelisted,
        ),
    )


@router.post("/logout")
def logout():
    return {"message": "Logged out"}


@router.get("/me", response_model=UserInfo)
def get_me(current_user: User = Depends(get_current_user)):
    return UserInfo(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        is_admin=current_user.is_admin,
        is_active=current_user.is_active,
        is_whitelisted=current_user.is_whitelisted,
    )
