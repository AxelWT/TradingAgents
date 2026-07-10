from pydantic import BaseModel, EmailStr
from typing import Optional


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    code: str


class SendCodeRequest(BaseModel):
    email: EmailStr


class SendCodeResponse(BaseModel):
    message: str
    expire_seconds: int


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    is_admin: bool = False
    is_active: bool = True
    is_whitelisted: bool = False

    class Config:
        from_attributes = True
