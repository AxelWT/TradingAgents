import uuid

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.auth.schemas import LoginRequest, RegisterRequest, AuthResponse, UserInfo
from app.auth.security import hash_password, verify_password, create_access_token
from app.dependencies import get_current_user
from app.db.database import get_db
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Email already registered")

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
        raise HTTPException(status_code=401, detail="Invalid email or password")

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
