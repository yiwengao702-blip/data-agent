from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import QuerySchema
from app.conf.app_config import app_config
from app.core.auth_deps import get_current_user
from app.services.query_service import QueryService

query_router = APIRouter()


# 定义POST接口/api/query   依赖
@query_router.post("/api/query")  # localhost:8001/api/query
async def query(
    query: QuerySchema,
    query_service: QueryService = Depends(get_query_service),
    username: str | None = Depends(get_current_user),
):
    # 生产环境可开启「必须登录」：require_auth=true 时未携带有效 Token 直接 401
    if app_config.auth.require_auth and username is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "请先登录后再问数",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # 127.0.0.1/api/query   传2个参数 第一个 问题   = Depends(get_query_service)
    # 调用服务处理查询，返回SSE流式响应
    return StreamingResponse(query_service.query(query.query), media_type="text/event-stream")




