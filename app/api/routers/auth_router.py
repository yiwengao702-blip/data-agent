# app/api/routers/auth_router.py
# 真实鉴权接口：注册 / 登录（签发 JWT）/ 当前用户（校验 Token）。
# 用户数据落在独立 SQLite（见 app.db.auth_db），与业务 MySQL 解耦。

import re

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.auth_db import SessionLocal, User, init_auth_db

auth_router = APIRouter()

# 轻量格式校验（避免额外依赖 email-validator，同时覆盖常见非法输入）
_USER_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- 请求 / 响应模型 ----------
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    email: str = Field(max_length=254)
    password: str = Field(min_length=6, max_length=64)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=64)


class UserOut(BaseModel):
    username: str
    email: str


class TokenOut(BaseModel):
    token: str
    user: UserOut


# ---------- 依赖 ----------
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _validate_registration(body: RegisterIn) -> None:
    if not _USER_RE.match(body.username):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户名仅允许字母、数字、下划线，长度 3-32")
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "邮箱格式不正确")
    if len(body.password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "密码至少 6 位")


# ---------- 接口 ----------
@auth_router.post(
    "/api/auth/register",
    response_model=TokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册新账户并签发 Token",
)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    init_auth_db()
    _validate_registration(body)
    # 用户名 / 邮箱 唯一性校验（大小写敏感，保持简单）
    exists = db.scalar(
        select(User).where((User.username == body.username) | (User.email == body.email))
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名或邮箱已存在")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.username)
    return TokenOut(token=token, user=UserOut(username=user.username, email=user.email))


@auth_router.post("/api/auth/login", response_model=TokenOut, summary="登录并签发 Token")
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    init_auth_db()
    user = db.scalar(select(User).where(User.username == body.username))
    # 统一返回「用户名或密码错误」，避免泄露用户名是否存在
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    token = create_access_token(user.username)
    return TokenOut(token=token, user=UserOut(username=user.username, email=user.email))


@auth_router.get("/api/auth/me", response_model=UserOut, summary="校验 Token 并返回当前用户")
def me(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> UserOut:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 Bearer Token")
    username = decode_access_token(authorization[7:])
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token 无效或已过期")
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return UserOut(username=user.username, email=user.email)
