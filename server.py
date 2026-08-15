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
from app.api.routers.query_router import query_router


# 创建 FastAPI 应用实例，并绑定 lifespan（启动时初始化 MySQL/Qdrant/ES/Embedding 客户端，关闭时释放）
app = FastAPI(
    title="data-agent 问数服务",
    description="基于 LangGraph + 元知识库的 NL2SQL 自然语言问数服务，提供 SSE 流式应答与可视化前端",
    version="0.1.0",
    lifespan=lifespan,
)

# 挂载问数路由（/api/query）
app.include_router(query_router)


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
