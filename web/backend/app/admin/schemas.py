from datetime import datetime

from pydantic import BaseModel


class AdminUserInfo(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    is_admin: bool = False
    is_active: bool = True
    is_whitelisted: bool = False
    created_at: datetime | None = None
    task_count: int = 0

    class Config:
        from_attributes = True


class AdminUserListResponse(BaseModel):
    users: list[AdminUserInfo]
    total: int


class AdminUserUpdateRequest(BaseModel):
    is_active: bool | None = None
    is_whitelisted: bool | None = None
    is_admin: bool | None = None


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    blacklisted_users: int
    whitelisted_users: int
    admin_users: int
    total_tasks: int
    access_mode: str


class AccessModeResponse(BaseModel):
    access_mode: str


class AccessModeUpdateRequest(BaseModel):
    access_mode: str
