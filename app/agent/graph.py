import asyncio

from langgraph.constants import START, END
from langgraph.graph import StateGraph
from app.agent.context import DataAgentContext
from app.agent.nodes.add_extra_context import add_extra_context
from app.agent.nodes.correct_sql import correct_sql
from app.agent.nodes.execute_sql import execute_sql
from app.agent.nodes.extract_keywords import extract_keywords
from app.agent.nodes.filter_metric import filter_metric
from app.agent.nodes.filter_table import filter_table
from app.agent.nodes.generate_sql import generate_sql
from app.agent.nodes.merge_retrieved_info import merge_retrieved_info
from app.agent.nodes.recall_column import recall_column
from app.agent.nodes.recall_metric import recall_metric
from app.agent.nodes.recall_value import recall_value
from app.agent.nodes.validate_sql import validate_sql
from app.agent.state import DataAgentState
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueEsRepository
from app.repositories.mysql.dw_mysql_repository import DwMysqlRepository
from app.repositories.mysql.meta_mysql_repository import MetaMysqlRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


def route_after_validate(state: DataAgentState) -> str:
    """根据SQL校验结果路由：有错误则校正后重新校验，无错误则执行"""
    if state.get("error"):
        return "correct_sql"
    return "execute_sql"


def build_graph():
    """构建数据智能体工作流图"""
    # 创建状态图对象
    builder = StateGraph(DataAgentState, context_schema=DataAgentContext)
    # 注册节点
    builder.add_node("add_extra_context", add_extra_context)
    builder.add_node("extract_keywords", extract_keywords)
    builder.add_node("recall_column", recall_column)
    builder.add_node("recall_metric", recall_metric)
    builder.add_node("recall_value", recall_value)
    builder.add_node("merge_retrieved_info", merge_retrieved_info)
    builder.add_node("filter_table", filter_table)
    builder.add_node("filter_metric", filter_metric)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("validate_sql", validate_sql)
    builder.add_node("correct_sql", correct_sql)
    builder.add_node("execute_sql", execute_sql)
    # 编排边
    builder.add_edge(START, "add_extra_context")
    builder.add_edge("add_extra_context", "extract_keywords")
    # 三路召回并行执行
    builder.add_edge("extract_keywords", "recall_column")
    builder.add_edge("extract_keywords", "recall_metric")
    builder.add_edge("extract_keywords", "recall_value")
    # 三路召回全部完成后合并
    builder.add_edge("recall_column", "merge_retrieved_info")
    builder.add_edge("recall_metric", "merge_retrieved_info")
    builder.add_edge("recall_value", "merge_retrieved_info")
    # 表过滤和指标过滤并行执行
    builder.add_edge("merge_retrieved_info", "filter_table")
    builder.add_edge("merge_retrieved_info", "filter_metric")
    builder.add_edge("filter_table", "generate_sql")
    builder.add_edge("filter_metric", "generate_sql")
    # 生成 -> 校验 -> 条件路由（校正重试 / 执行）
    builder.add_edge("generate_sql", "validate_sql")
    builder.add_conditional_edges("validate_sql", route_after_validate)
    builder.add_edge("correct_sql", "validate_sql")
    builder.add_edge("execute_sql", END)
    # 编译为可调用的图对象
    return builder.compile()


# 编译后的图对象，供入口/服务层调用
graph = build_graph()


# 测试流式调用
if __name__ == '__main__':
    async def test():
        # 初始化客户端对象
        embedding_client_manager.init()
        qdrant_client_manager.init()
        es_client_manager.init()
        meta_mysql_client_manager.init()
        dw_mysql_client_manager.init()        # 构建操作持久层对象
        embedding_client=embedding_client_manager.client
        column_qdrant_repository=ColumnQdrantRepository(qdrant_client_manager.client)
        value_es_repository=ValueEsRepository(es_client_manager.client)
        metric_qdrant_repository=MetricQdrantRepository(qdrant_client_manager.client)
        # 创建操作元数据库的操作对象
        async with meta_mysql_client_manager.session_factory() as meta_session ,dw_mysql_client_manager.session_factory() as dw_session:
            # 创建操作对象
            meta_mysql_repository=MetaMysqlRepository(meta_session)
            dw_mysql_repository=DwMysqlRepository(dw_session)
            # 创建上下文对象
            context= DataAgentContext(
                embedding_client=embedding_client,
                column_qdrant_repository=column_qdrant_repository,
                value_es_repository=value_es_repository,
                metric_qdrant_repository=metric_qdrant_repository,
                meta_mysql_repository=meta_mysql_repository,
                dw_mysql_repository=dw_mysql_repository
            )
            # 创建状态对象
            state = DataAgentState(query="统计2025年各地区销售总额")
            # 调用图流式输出
            async for chunk in graph.astream(input=state,context=context,stream_mode="custom"):
                print(chunk)

        # 关闭客户端
        await qdrant_client_manager.close()
        await es_client_manager.close()
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()
    # 调用测试函数
    asyncio.run(test())
