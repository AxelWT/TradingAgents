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
from app.dependencies import get_current_user
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

    # 同邮箱重发限频
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
                detail=f"请求过于频繁，请 {wait} 秒后再试",
            )

    # 生成验证码
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

    # 发送邮件（失败则回滚记录，避免占用记录但未送达）
    try:
        await send_verification_email(req.email, code)
    except RuntimeError as e:
        logger.warning("send-code email failed for %s: %s", req.email, e)
        db.delete(record)
        db.commit()
        raise HTTPException(status_code=503, detail="验证码邮件发送失败，请稍后重试")

    return SendCodeResponse(
        message="验证码已发送，请查收邮件",
        expire_seconds=settings.VERIFY_CODE_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    now = _utcnow()

    existing = db.query(User).filter(User.email == req.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="该邮箱已注册")

    # 校验验证码：取该邮箱最新未消费记录
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
        raise HTTPException(status_code=400, detail="请先获取验证码")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now > expires_at:
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")

    # 试错次数累加
    record.attempts = (record.attempts or 0) + 1
    if record.attempts > settings.VERIFY_CODE_MAX_ATTEMPTS:
        record.consumed = True
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="验证码错误次数过多，请重新获取",
        )

    if not _verify_code(req.code, record.code_hash):
        db.commit()
        raise HTTPException(status_code=400, detail="验证码错误")

    # 验证通过，标记消费
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
        user=UserInfo(id=user.id, email=user.email, display_name=user.display_name),
    )


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        user=UserInfo(id=user.id, email=user.email, display_name=user.display_name),
    )


@router.post("/logout")
def logout():
    return {"message": "Logged out"}


@router.get("/me", response_model=UserInfo)
def get_me(current_user: User = Depends(get_current_user)):
    return UserInfo(
        id=current_user.id, email=current_user.email, display_name=current_user.display_name
    )
