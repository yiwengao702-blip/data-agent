# app/core/middleware.py
# 企业级 ASGI 中间件（零依赖实现，避免引入额外包）：
# - SecurityHeadersMiddleware：为 HTTP 响应补充基础安全头。仅修改响应头、不触碰响应体，
#   因此对 SSE（text/event-stream）流式接口安全无副作用。
# - RateLimitMiddleware：针对指定前缀路径（如 /api/auth/*）的简易固定窗口限流，
#   按客户端 IP 计数，用于抵御登录/注册接口的暴力破解与接口滥用。

import time
from collections import defaultdict
from typing import Dict, Tuple

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """为 HTTP 响应补充基础安全头（点击劫持防护 / MIME 嗅探防护 /  referrer 策略等）。"""

    _SECURITY_HEADERS = {
        b"x-content-type-options": b"nosniff",
        b"x-frame-options": b"DENY",
        b"referrer-policy": b"no-referrer",
        b"permissions-policy": b"geolocation=(), microphone=(), camera=()",
        # 说明：HSTS 仅在 HTTPS 部署时有意义；HTTP 下设置可能被反向代理拒绝，故此处不强制。
    }

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                for key, value in self._SECURITY_HEADERS.items():
                    if key not in headers:  # 不覆盖既有显式配置
                        headers[key] = value
                message["headers"] = [(k, v) for k, v in headers.items()]
            await send(message)

        await self.app(scope, receive, wrapper)


class RateLimitMiddleware:
    """针对指定前缀路径的简易固定窗口限流（按客户端 IP）。

    配置项：
    - paths：需要限流的路径前缀列表（如 ["/api/auth/"]）
    - limit_per_min：每个 (IP, 路径) 每分钟允许的最大请求数；<=0 表示不限流
    """

    def __init__(self, app: ASGIApp, paths: list, limit_per_min: int) -> None:
        self.app = app
        self.paths = paths or []
        self.limit_per_min = limit_per_min
        self._store: Dict[Tuple[str, str], Tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    @staticmethod
    def _client_ip(scope: Scope) -> str:
        client = scope.get("client")
        return client[0] if client else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.limit_per_min <= 0:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not any(path.startswith(p) for p in self.paths):
            await self.app(scope, receive, send)
            return

        ip = self._client_ip(scope)
        key = (ip, path)
        now = time.time()
        count, start = self._store[key]
        if now - start >= 60:
            count, start = 0, now
        if count >= self.limit_per_min:
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"retry-after", b"60"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": '{"detail":"请求过于频繁，请稍后再试"}'.encode("utf-8"),
                }
            )
            return
        self._store[key] = (count + 1, start)
        await self.app(scope, receive, send)
