# app/scripts/build_meta_knowledge.py
# 从 pathlib 库导入 Path 类，用于处理文件路径
import asyncio
from pathlib import Path
# 从 app.core.log 模块导入 logger 对象，用于日志记录
from app.core.log import logger
from Lib.argparse import ArgumentParser


from app.services.meta_knowledge_service import MetaKnowledgeService
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.repositories.mysql.dw_mysql_repository import DwMysqlRepository
from app.repositories.mysql.meta_mysql_repository import MetaMysqlRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.es.value_es_repository import ValueEsRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
# 定义 build 函数，接收一个 Path 类型的参数 config_path，表示配置文件路径
async def build(config_path: Path):
    # 创建service对象
    # 初始化客户端连接
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    qdrant_client_manager.init() # 向量数据库客户端
    embedding_client_manager.init() # 向量化模型
    es_client_manager.init()  # es 客户端的初始化


    # 获取session
    async with meta_mysql_client_manager.session_factory() as meta_session, dw_mysql_client_manager.session_factory() as dw_session:
        # 创建repository对象
        meta_mysql_repository = MetaMysqlRepository(meta_session)
        dw_mysql_repository = DwMysqlRepository(dw_session)
        column_qdrant_repository = ColumnQdrantRepository(qdrant_client_manager.client)# 原始数据
        value_es_repository = ValueEsRepository(es_client_manager.client)
        # 操作层 关于 指标的元信息 的 向量化操作
        metric_qdrant_repository = MetricQdrantRepository(qdrant_client_manager.client) # 指标信息
        # 创建service对象
        meta_knowledge_service = MetaKnowledgeService(
            meta_mysql_repository=meta_mysql_repository,# 操作meta库连接
            dw_mysql_repository=dw_mysql_repository,# 操作dw 连接
            column_qdrant_repository = column_qdrant_repository, # 业务层
            embedding_client=embedding_client_manager.client, # 模型 BGEM large 1.5 ZH
            value_es_repository = value_es_repository,
            metric_qdrant_repository = metric_qdrant_repository
        )
        # 调用build函数
        await meta_knowledge_service.build(config_path)
    # 释放资源
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
    await qdrant_client_manager.close()
    await es_client_manager.close()

# 当脚本被直接运行时执行以下代码
if __name__ == '__main__':
    # 创建一个命令行参数解析器对象
    parser = ArgumentParser()
    # 添加一个可选参数，支持短选项 -c 和长选项 --conf
    # 该选项用于接收配置文件的路径
    parser.add_argument('-c', '--conf')
    # 解析命令行传入的所有参数，并将结果存入 args 对象
    args = parser.parse_args()
    # 将命令行参数中获取的配置文件路径字符串，转换为 Path 对象
    config_path = Path(args.conf)
    print(config_path)# 路径
    # 调用 build 函数，传入解析后的配置文件路径
    asyncio.run(build(config_path))
