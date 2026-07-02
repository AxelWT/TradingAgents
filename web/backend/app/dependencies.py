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

    user = db.query(User).filter((User.id == user_id) | (User.email == email)).first()
    if user is None:
        user = User(id=user_id, email=email)
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
        except IntegrityError:
            db.rollback()
            user = db.query(User).filter(User.email == email).first()

    return user
