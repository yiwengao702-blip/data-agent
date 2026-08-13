from fastapi import APIRouter
from fastapi.params import Depends
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import QuerySchema
from app.services.query_service import QueryService

query_router = APIRouter()


# 定义POST接口/api/query   依赖
@query_router.post("/api/query")  # localhost:8001/api/query
async def query(query: QuerySchema, query_service: QueryService = Depends(get_query_service)):
    # 127.0.0.1/api/query   传2个参数 第一个 问题   = Depends(get_query_service)
    # 调用服务处理查询，返回SSE流式响应
    return StreamingResponse(query_service.query(query.query), media_type="text/event-stream")




