import asyncio

import yaml
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.prompt.prompt_loader import loader_prompt


async def generate_sql(state:DataAgentState,runtime:Runtime[DataAgentContext]):
    # 获取流式输出器
    writer = runtime.stream_writer
    # 输出进度状态信息
    # writer("生成SQL")
    writer({"stage": "生成SQL"})
    try:
        # 获取用户查询
        query = state["query"]
        # 获取表数据列表
        table_infos = state["table_infos"]
        # 获取指标数据列表
        metric_infos = state["metric_infos"]
        # 获取时间信息
        date_info = state["date_info"]
        # 获取数据库信息
        db_info = state["db_info"]

        # 创建提示词对象
        prompt = PromptTemplate(template=loader_prompt("generate_sql"),
                                input_variables=["query", "table_infos", "metric_infos", "date_info", "db_info"])
        # 构建json转换对象--> 此处解析必须使用文本解析方式
        output_parser = StrOutputParser()
        # 构建查询链
        chain = prompt | llm | output_parser
        # 执行查询
        result = await chain.ainvoke({
            "query": query,
            "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False),
            "metric_infos": yaml.dump(metric_infos, allow_unicode=True, sort_keys=False),
            "date_info": yaml.dump(date_info, allow_unicode=True, sort_keys=False),
            "db_info": yaml.dump(db_info, allow_unicode=True, sort_keys=False)
        })
        logger.info(f"生成的sql语句\n：{result}")

        return {"sql": result}
    except Exception as e:
        logger.error(f"生成的sql语句失败:{str(e)}")
        raise
