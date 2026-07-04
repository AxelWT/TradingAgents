import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.supabase_client import get_supabase_client
from app.db.database import get_db
from app.db.models import User

logger = logging.getLogger(__name__)

security = HTTPBearer()


def upsert_user(db: Session, user_id: str, email: str) -> User:
    """Create or fetch a local User row for a Supabase user.

    Looks up by ``user_id`` first; if not found, checks whether the email is
    already taken by a *different* user (in which case that existing user is
    returned rather than silently merging accounts). Otherwise inserts a new row.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        return user

    existing_email = db.query(User).filter(User.email == email).first()
    if existing_email is not None and existing_email.id != user_id:
        logger.warning(
            "Email %s already used by user %s, returning existing instead of creating %s",
            email,
            existing_email.id,
            user_id,
        )
        return existing_email

    user = User(id=user_id, email=email)
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        user = db.query(User).filter(User.id == user_id).first()
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    sb = get_supabase_client()

    try:
        user_resp = sb.auth.get_user(token)
    except Exception as e:
        logger.warning("Supabase get_user failed: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if user_resp is None or user_resp.user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = user_resp.user.id
    email = user_resp.user.email or ""

    return upsert_user(db, user_id, email)
