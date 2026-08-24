# app/core/auth_deps.py
# 鉴权依赖：从 Authorization: Bearer <token> 解析当前用户，供路由按需使用。
#
# 提供两种粒度：
# - get_current_user：可选，缺失或无效返回 None（用于「可选登录」场景，如演示态）。
# - require_current_user：强制，缺失或无效直接 401（用于「必须登录」的生产接口）。

from fastapi import Depends, Header, HTTPException, status

from app.core.security import decode_access_token


async def get_current_user(authorization: str | None = Header(default=None)) -> str | None:
    """可选登录：解析 Bearer Token，失败/缺失返回 None（不抛错）。"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return decode_access_token(authorization[7:])


async def require_current_user(authorization: str | None = Header(default=None)) -> str:
    """强制登录：缺失或无效 Token 一律 401，并在响应头提示 Bearer 认证方式。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "缺少 Bearer Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = decode_access_token(authorization[7:])
    if not username:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
