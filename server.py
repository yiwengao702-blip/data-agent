# server.py
# 问数 API 服务入口：创建 FastAPI 应用，挂载 SSE 流式问数路由，并通过 lifespan 管理所有下游客户端连接
# 启动方式：
#   python server.py            # 使用 conf/app_config.yaml 的 server.host/port
#   uvicorn server:app          # 等价
#   DATA_AGENT_CONFIG=conf/app_config.e2e.yaml uvicorn server:app  # 指定配置

import os

import uvicorn

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.conf.app_config import app_config
from app.core.health import check_health
from app.core.lifespan import lifespan
from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.api.routers.query_router import query_router
from app.api.routers.auth_router import auth_router


# 创建 FastAPI 应用实例，并绑定 lifespan（启动时初始化 MySQL/Qdrant/ES/Embedding 客户端，关闭时释放）
app = FastAPI(
    title="data-agent 问数服务",
    description="基于 LangGraph + 元知识库的 NL2SQL 自然语言问数服务，提供 SSE 流式应答与可视化前端",
    version="0.1.0",
    lifespan=lifespan,
)

# ---- 企业级安全加固中间件（嵌套顺序：CORS 最外 → 限流 → 安全头 最内） ----
# 1) 安全响应头：仅补充响应头，不改动响应体，对 SSE 流式接口安全无副作用
app.add_middleware(SecurityHeadersMiddleware)

# 2) 鉴权接口限流：按客户端 IP 对 /api/auth/* 做固定窗口限流，抵御暴力破解与接口滥用
app.add_middleware(
    RateLimitMiddleware,
    paths=["/api/auth/"],
    limit_per_min=app_config.auth.rate_limit_per_min,
)

# 3) CORS：仅当显式配置了 allowed_origins 才开启（同源部署无需跨域）
if app_config.auth.allowed_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_config.auth.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 挂载问数路由（/api/query）
app.include_router(query_router)
# 挂载鉴权路由（/api/auth/register、/api/auth/login、/api/auth/me）
app.include_router(auth_router)


# 托管前端静态页面（frontend/ 下的 index.html / styles.css / app.js）。
# 挂载在 /ui 子路径，避免与 /api/* 路由冲突；根路径 / 重定向到 /ui/，访问更友好。
# 防御性判断目录存在，缺失时不影响 API 服务。
_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/ui", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        """根路径重定向到前端入口，方便直接打开浏览器访问。"""
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/ui/")


@app.get("/api/health", tags=["运维"])
async def health():
    """
    健康检查接口：用于容器探活、负载均衡与上线自检。
    返回各下游依赖（LLM / MySQL / Qdrant / ES / Embedding）的真实连通状态与耗时。
    """
    return await check_health()


if __name__ == '__main__':
    # 直接运行本文件时，使用配置中的 host/port 启动 uvicorn
    uvicorn.run(
        app,
        host=app_config.server.host,
        port=app_config.server.port,
    )
