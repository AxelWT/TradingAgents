from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.schemas import LoginRequest, RegisterRequest, AuthResponse, UserInfo
from app.auth.supabase_client import get_supabase_client
from app.db.database import get_db
from app.db.models import User
from supabase import Client

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    sb: Client = get_supabase_client()
    try:
        resp = sb.auth.sign_up(
            {
                "email": req.email,
                "password": req.password,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if resp.user is None:
        raise HTTPException(status_code=400, detail="Registration failed")

    if resp.session is None:
        try:
            login_resp = sb.auth.sign_in_with_password(
                {"email": req.email, "password": req.password}
            )
            if login_resp.session is not None:
                user_id = login_resp.user.id
                db_user = (
                    db.query(User).filter((User.id == user_id) | (User.email == req.email)).first()
                )
                if db_user is None:
                    db_user = User(id=user_id, email=req.email)
                    try:
                        db.add(db_user)
                        db.commit()
                        db.refresh(db_user)
                    except IntegrityError:
                        db.rollback()
                        db_user = db.query(User).filter(User.email == req.email).first()
                return AuthResponse(
                    access_token=login_resp.session.access_token,
                    user=UserInfo(id=user_id, email=req.email),
                )
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail="Registration succeeded but session is unavailable. Please confirm your email and try logging in.",
        )

    user_id = resp.user.id
    db_user = db.query(User).filter((User.id == user_id) | (User.email == req.email)).first()
    if db_user is None:
        db_user = User(id=user_id, email=req.email)
        try:
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
        except IntegrityError:
            db.rollback()
            db_user = db.query(User).filter(User.email == req.email).first()

    return AuthResponse(
        access_token=resp.session.access_token,
        user=UserInfo(id=user_id, email=req.email),
    )


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    sb: Client = get_supabase_client()
    try:
        resp = sb.auth.sign_in_with_password(
            {
                "email": req.email,
                "password": req.password,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if resp.user is None:
        raise HTTPException(status_code=401, detail="Login failed")

    if resp.session is None:
        raise HTTPException(status_code=401, detail="Login failed: no session returned")

    user_id = resp.user.id
    db_user = db.query(User).filter((User.id == user_id) | (User.email == req.email)).first()
    if db_user is None:
        db_user = User(id=user_id, email=req.email)
        try:
            db.add(db_user)
            db.commit()
        except IntegrityError:
            db.rollback()
            db_user = db.query(User).filter(User.email == req.email).first()

    return AuthResponse(
        access_token=resp.session.access_token,
        user=UserInfo(id=user_id, email=db_user.email, display_name=db_user.display_name),
    )


@router.post("/logout")
def logout():
    sb: Client = get_supabase_client()
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    return {"message": "Logged out"}


@router.get("/me", response_model=UserInfo)
def get_me(current_user: User = Depends(lambda: None)):
    from app.dependencies import get_current_user

    return UserInfo(
        id=current_user.id, email=current_user.email, display_name=current_user.display_name
    )
