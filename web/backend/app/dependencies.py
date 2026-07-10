import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.database import get_db
from app.db.models import User

logger = logging.getLogger(__name__)

security = HTTPBearer()


def _check_access(user: User) -> None:
    """Access control: admins always pass; blacklisted users and non-whitelisted users in whitelist mode are blocked."""
    if user.is_admin:
        return
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account has been disabled"
        )
    settings = get_settings()
    if settings.ACCESS_MODE == "whitelist" and not user.is_whitelisted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System is in whitelist mode, access denied",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    settings = get_settings()

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    _check_access(user)
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required"
        )
    return user
