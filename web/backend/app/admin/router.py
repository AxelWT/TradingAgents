import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.admin.schemas import (
    AccessModeResponse,
    AccessModeUpdateRequest,
    AdminStatsResponse,
    AdminUserInfo,
    AdminUserListResponse,
    AdminUserUpdateRequest,
)
from app.config import get_settings
from app.db.database import get_db
from app.db.models import AnalysisTask, EmailVerificationCode, User
from app.dependencies import get_current_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _user_to_admin_info(user: User, task_count: int = 0) -> AdminUserInfo:
    return AdminUserInfo(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_active=user.is_active,
        is_whitelisted=user.is_whitelisted,
        created_at=user.created_at,
        task_count=task_count,
    )


@router.get("/stats", response_model=AdminStatsResponse)
def get_stats(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    total = db.query(User).count()
    active = db.query(User).filter(User.is_active == True).count()  # noqa: E712
    blacklisted = db.query(User).filter(User.is_active == False).count()  # noqa: E712
    whitelisted = db.query(User).filter(User.is_whitelisted == True).count()  # noqa: E712
    admins = db.query(User).filter(User.is_admin == True).count()  # noqa: E712
    total_tasks = db.query(AnalysisTask).count()
    return AdminStatsResponse(
        total_users=total,
        active_users=active,
        blacklisted_users=blacklisted,
        whitelisted_users=whitelisted,
        admin_users=admins,
        total_tasks=total_tasks,
        access_mode=settings.ACCESS_MODE,
    )


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(None),
    status_filter: str = Query(None),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if search:
        query = query.filter(User.email.ilike(f"%{search}%"))
    if status_filter == "active":
        query = query.filter(User.is_active == True)  # noqa: E712
    elif status_filter == "blacklisted":
        query = query.filter(User.is_active == False)  # noqa: E712
    elif status_filter == "whitelisted":
        query = query.filter(User.is_whitelisted == True)  # noqa: E712
    elif status_filter == "admin":
        query = query.filter(User.is_admin == True)  # noqa: E712

    total = query.count()
    users = (
        query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    )

    user_ids = [u.id for u in users]
    task_counts = {}
    if user_ids:
        from sqlalchemy import func

        rows = (
            db.query(AnalysisTask.user_id, func.count(AnalysisTask.id))
            .filter(AnalysisTask.user_id.in_(user_ids))
            .group_by(AnalysisTask.user_id)
            .all()
        )
        task_counts = dict(rows)

    return AdminUserListResponse(
        users=[_user_to_admin_info(u, task_counts.get(u.id, 0)) for u in users],
        total=total,
    )


@router.get("/users/{user_id}", response_model=AdminUserInfo)
def get_user(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    task_count = db.query(AnalysisTask).filter(AnalysisTask.user_id == user_id).count()
    return _user_to_admin_info(user, task_count)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    if user.is_admin:
        admin_count = db.query(User).filter(User.is_admin == True).count()  # noqa: E712
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin")

    db.query(AnalysisTask).filter(AnalysisTask.user_id == user_id).delete()
    db.query(EmailVerificationCode).filter(EmailVerificationCode.email == user.email).delete()
    db.delete(user)
    db.commit()
    logger.info("admin %s deleted user %s (%s)", admin.email, user.id, user.email)


@router.patch("/users/{user_id}", response_model=AdminUserInfo)
def update_user(
    user_id: str,
    req: AdminUserUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == admin.id and req.is_admin is False:
        raise HTTPException(status_code=400, detail="Cannot revoke your own admin privileges")

    if user.is_admin and req.is_admin is False:
        admin_count = db.query(User).filter(User.is_admin == True).count()  # noqa: E712
        if admin_count <= 1:
            raise HTTPException(
                status_code=400, detail="Cannot revoke admin privileges from the last admin"
            )

    if req.is_active is not None:
        user.is_active = req.is_active
    if req.is_whitelisted is not None:
        user.is_whitelisted = req.is_whitelisted
    if req.is_admin is not None:
        user.is_admin = req.is_admin

    db.commit()
    db.refresh(user)
    task_count = db.query(AnalysisTask).filter(AnalysisTask.user_id == user_id).count()
    return _user_to_admin_info(user, task_count)


@router.post("/users/{user_id}/blacklist", response_model=AdminUserInfo)
def add_to_blacklist(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_admin:
        raise HTTPException(status_code=400, detail="Cannot blacklist an admin")

    user.is_active = False
    db.commit()
    db.refresh(user)
    task_count = db.query(AnalysisTask).filter(AnalysisTask.user_id == user_id).count()
    return _user_to_admin_info(user, task_count)


@router.delete("/users/{user_id}/blacklist", response_model=AdminUserInfo)
def remove_from_blacklist(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = True
    db.commit()
    db.refresh(user)
    task_count = db.query(AnalysisTask).filter(AnalysisTask.user_id == user_id).count()
    return _user_to_admin_info(user, task_count)


@router.post("/users/{user_id}/whitelist", response_model=AdminUserInfo)
def add_to_whitelist(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_whitelisted = True
    db.commit()
    db.refresh(user)
    task_count = db.query(AnalysisTask).filter(AnalysisTask.user_id == user_id).count()
    return _user_to_admin_info(user, task_count)


@router.delete("/users/{user_id}/whitelist", response_model=AdminUserInfo)
def remove_from_whitelist(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_whitelisted = False
    db.commit()
    db.refresh(user)
    task_count = db.query(AnalysisTask).filter(AnalysisTask.user_id == user_id).count()
    return _user_to_admin_info(user, task_count)


@router.get("/access-mode", response_model=AccessModeResponse)
def get_access_mode(
    admin: User = Depends(get_current_admin),
):
    settings = get_settings()
    return AccessModeResponse(access_mode=settings.ACCESS_MODE)


@router.put("/access-mode", response_model=AccessModeResponse)
def update_access_mode(
    req: AccessModeUpdateRequest,
    admin: User = Depends(get_current_admin),
):
    if req.access_mode not in ("open", "whitelist"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="access_mode must be 'open' or 'whitelist'",
        )

    import app.config as _config_module

    cached = _config_module.get_settings()
    cached.ACCESS_MODE = req.access_mode
    logger.info("admin %s switched access mode to %s", admin.email, req.access_mode)
    return AccessModeResponse(access_mode=req.access_mode)
