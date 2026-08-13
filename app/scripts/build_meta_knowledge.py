# app/scripts/build_meta_knowledge.py
# 元知识库构建脚本：把配置文件中的表/字段/指标元信息写入 MySQL meta 库、Qdrant 向量库、ES 全文索引
# 从 pathlib 库导入 Path 类，用于处理文件路径
import asyncio
from pathlib import Path
# 从 app.core.log 模块导入 logger 对象，用于日志记录
from app.core.log import logger
# 注意：必须使用标准库 argparse（早期写成 from Lib.argparse import ...，
# 仅因 uv 虚拟环境恰好把基础 Python 的 Lib 目录放进 sys.path 才能导入，换机器必崩）
from argparse import ArgumentParser

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


async def _reset_storages():
    """
    清空全部目标存储，实现"清空重新导入"语义：
    1. Qdrant 两个集合（字段向量集合、指标向量集合）直接删除，构建时会重新 ensure_collection 创建
    2. ES 取值索引删除，构建时会重新 ensure_index 创建
    3. MySQL meta 四张表清空（表信息、字段信息、指标信息、字段指标中间表）
    """
    # 1.1 删除 Qdrant 字段向量集合（不存在时静默跳过，避免 reset 重复执行报错）
    try:
        await qdrant_client_manager.client.delete_collection(
            collection_name=ColumnQdrantRepository.collection_name)
        logger.info(f"已删除 Qdrant 集合：{ColumnQdrantRepository.collection_name}")
    except Exception as e:
        logger.warning(f"删除 Qdrant 集合 {ColumnQdrantRepository.collection_name} 失败（可忽略）：{e}")

    # 1.2 删除 Qdrant 指标向量集合
    try:
        await qdrant_client_manager.client.delete_collection(
            collection_name=MetricQdrantRepository.collection_name)
        logger.info(f"已删除 Qdrant 集合：{MetricQdrantRepository.collection_name}")
    except Exception as e:
        logger.warning(f"删除 Qdrant 集合 {MetricQdrantRepository.collection_name} 失败（可忽略）：{e}")

    # 2. 删除 ES 取值索引（ignore_unavailable 保证索引不存在时不抛异常）
    try:
        await es_client_manager.client.indices.delete(
            index=ValueEsRepository.es_index_name, ignore_unavailable=True)
        logger.info(f"已删除 ES 索引：{ValueEsRepository.es_index_name}")
    except Exception as e:
        logger.warning(f"删除 ES 索引 {ValueEsRepository.es_index_name} 失败（可忽略）：{e}")

    # 3. 清空 MySQL meta 四张表（无外键约束，直接 delete；放在一个事务里保证原子性）
    async with meta_mysql_client_manager.session_factory() as session:
        # 直接执行原生 SQL 清表，avoid 逐条 ORM 删除
        from sqlalchemy import text
        # 开启事务，四张表要么全清要么全不清
        async with session.begin():
            # 中间表先清（逻辑上的从表）
            await session.execute(text("delete from column_metric"))
            # 指标信息表
            await session.execute(text("delete from metric_info"))
            # 字段信息表
            await session.execute(text("delete from column_info"))
            # 表信息表
            await session.execute(text("delete from table_info"))
    logger.info("已清空 MySQL meta 四张表：column_metric / metric_info / column_info / table_info")


# 定义 build 函数，接收一个 Path 类型的参数 config_path，表示配置文件路径
# reset：为 True 时先清空 Qdrant / ES / meta 库再重新导入（清空重新导入）
async def build(config_path: Path, reset: bool = False):
    # 创建service对象
    # 初始化客户端连接
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
    qdrant_client_manager.init() # 向量数据库客户端
    embedding_client_manager.init() # 向量化模型
    es_client_manager.init()  # es 客户端的初始化

    # 使用 try/finally 保证无论构建成功还是抛异常，客户端资源都会被释放
    # （早期版本没有 try/finally，构建中途报错时连接池不会关闭）
    try:
        # 按需执行清空重置逻辑
        if reset:
            logger.info("reset=True，先清空 Qdrant / ES / meta 库再重新构建")
            await _reset_storages()

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
        logger.info("元知识库构建完成")
    finally:
        # 释放资源（finally 保证异常路径也能释放）
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()
        await qdrant_client_manager.close()
        await es_client_manager.close()

# 当脚本被直接运行时执行以下代码
if __name__ == '__main__':
    # 创建一个命令行参数解析器对象
    parser = ArgumentParser(description="元知识库构建脚本")
    # 添加一个可选参数，支持短选项 -c 和长选项 --conf
    # 该选项用于接收配置文件的路径，不传时使用默认配置 conf/meta_config.yaml
    parser.add_argument('-c', '--conf', default=None, help="元知识库配置文件路径，默认 conf/meta_config.yaml")
    # 添加 reset 选项：先清空 Qdrant / ES / meta 库，再重新导入
    parser.add_argument('-r', '--reset', action='store_true',
                        help="先清空 Qdrant 两个集合与 ES 索引及 meta 四张表，再重新构建（清空重新导入）")
    # 解析命令行传入的所有参数，并将结果存入 args 对象
    args = parser.parse_args()
    # 配置文件路径：命令行优先，未指定时回退默认路径 conf/meta_config.yaml
    default_config = Path(__file__).parents[2] / "conf" / "meta_config.yaml"
    # 将命令行参数中获取的配置文件路径字符串，转换为 Path 对象
    config_path = Path(args.conf) if args.conf else default_config
    print(config_path)# 路径
    # 调用 build 函数，传入解析出的配置文件路径与 reset 开关
    asyncio.run(build(config_path, reset=args.reset))
