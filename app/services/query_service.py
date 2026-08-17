# app/services/query_service.py
# 问数业务服务：把用户问题交给 LangGraph 工作流，并以 SSE 流式返回。
# 关键工程约束：无论链路正常还是异常，流都必须以 data: [DONE] 收尾，客户端永不挂起。
import json
import time

from langchain_huggingface import HuggingFaceEndpointEmbeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.llm import describe_llm_error
from app.agent.state import DataAgentState
from app.core.log import logger
from app.repositories.es.value_es_repository import ValueEsRepository
from app.repositories.mysql.dw_mysql_repository import DwMysqlRepository
from app.repositories.mysql.meta_mysql_repository import MetaMysqlRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


# 服务类：持有各类客户端连接，把「问题 + 连接」交给工作流执行
class QueryService:
    def __init__(self,
                 embedding_client: HuggingFaceEndpointEmbeddings,
                 column_qdrant_repository: ColumnQdrantRepository,
                 value_es_repository: ValueEsRepository,
                 metric_qdrant_repository: MetricQdrantRepository,
                 meta_mysql_repository: MetaMysqlRepository,
                 dw_mysql_repository: DwMysqlRepository):

        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

    async def query(self, query: str):
        """
        用户查询的业务处理，返回 SSE 事件生成器。
        正常结束与异常分支都会下发 data: [DONE]，确保流被正确关闭。
        """
        # 创建上下文对象（注入所有下游客户端连接）
        context = DataAgentContext(
            embedding_client=self.embedding_client,
            column_qdrant_repository=self.column_qdrant_repository,
            value_es_repository=self.value_es_repository,
            metric_qdrant_repository=self.metric_qdrant_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository,
        )
        # 创建状态对象（初始仅有用户问题）
        state = DataAgentState(query=query)
        try:
            # 链路计时：记录起点与上一个事件时刻，用于给每个 SSE 事件注入耗时埋点
            _start = time.monotonic()
            _last = _start
            # 调用图流式输出（节点通过 stream_writer 推送自定义事件）
            async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
                _now = time.monotonic()
                # 给每个事件补充耗时字段：elapsed_ms=链路累计耗时，delta_ms=距上一事件耗时（近似本阶段耗时）
                # 便于前端时间线展示每阶段耗时、形成性能基线，且不破坏原有事件结构（前端忽略未知字段）
                if isinstance(chunk, dict):
                    chunk = {
                        **chunk,
                        "elapsed_ms": round((_now - _start) * 1000, 1),
                        "delta_ms": round((_now - _last) * 1000, 1),
                    }
                _last = _now
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"

            # 正常结束：下发终止符，客户端据此关闭流
            yield "data: [DONE]\n\n"

        except Exception as e:
            # 链路任意节点异常都会在此被捕获：记录完整堆栈，并下发结构化错误事件
            logger.exception("问数链路执行异常")
            error_event = {
                "type": "error",
                "stage": "pipeline",
                "message": "问数链路执行失败",
                # 把上游异常（尤其 LLM 401/403/429）转成中文可操作提示
                "detail": describe_llm_error(e),
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False, default=str)}\n\n"
            # 异常分支同样下发终止符，保证流正常关闭，客户端不挂起
            yield "data: [DONE]\n\n"
