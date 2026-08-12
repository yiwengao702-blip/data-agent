import asyncio
from typing import Union
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy import text
from app.conf.app_config import app_config, DBConfig

import asyncio
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncSession, async_sessionmaker

from app.conf.app_config import app_config, DBConfig


class MysqlClientManager:
    """MySQL 异步客户端管理器：负责创建引擎、会话工厂，以及资源释放"""

    def __init__(self, config: DBConfig):
        # 异步引擎，init() 之前为 None
        self.engine: Optional[AsyncEngine] = None
        # 数据库连接配置（user/password/host/port/database）
        self.config = config
        # 异步会话工厂，init() 之前为 None
        self.session_factory = None

    def _get_url(self):
        """拼接 SQLAlchemy 异步连接串，驱动使用 asyncmy，字符集 utf8mb4"""
        # 获取数据库连接地址
        return f"mysql+asyncmy://{self.config.user}:{self.config.password}@{self.config.host}:{self.config.port}/{self.config.database}?charset=utf8mb4"

    def init(self):
        """初始化异步引擎和会话工厂（使用前必须调用）"""
        self.engine = create_async_engine(
            url=self._get_url(),
            # 连接池常驻连接数
            pool_size=5,
            # 取连接前先做 ping 检测，自动剔除死连接
            pool_pre_ping=True
        )
        self.session_factory = async_sessionmaker(
            # 绑定异步引擎
            bind=self.engine,
            # 执行查询前自动 flush 内存中的变更到数据库
            autoflush=True, # 设置自动刷新
            # 会话开始时自动开启事务
            autobegin=True,# 自动开启事务
            # commit 后 ORM 对象属性过期，再次访问时会重新查库
            expire_on_commit=True # ORM对象如果过期 会自动重新查询库
        )

    async def close(self):
        """释放引擎及其连接池中的所有连接"""
        await self.engine.dispose()


# 数仓库客户端
dw_mysql_client_manager = MysqlClientManager(app_config.db_dw)
# 元数据库客户端
meta_mysql_client_manager = MysqlClientManager(app_config.db_meta)

if __name__ == '__main__':
    # 初始化客户端（创建引擎和会话工厂）
    dw_mysql_client_manager.init()


    # 定义异步测试函数
    async def test():
        # 通过会话工厂获取 session，退出 with 块自动关闭
        # 也可以不用工厂，直接创建：
        # async with AsyncSession(bind=dw_mysql_client_manager.engine, autoflush=True, autobegin=True, expire_on_commit=True) as session:
        async with dw_mysql_client_manager.session_factory() as session:
            # 待执行的 SQL
            sql = "select *from fact_order limit 10"
            # 执行 SQL，返回 Result 对象
            result = await session.execute(text(sql))

            # 提取结果（三种方式，按需选一种）：
            # rows = result.mappings().fetchall()  # 字典结构：[{}, {}, {}]
            rows = result.scalars().fetchall()      # 只取每行第一列的值：[v1, v2, v3]
            # rows = result.fetchall()             # 元组结构（Row 对象）：[(), (), ()]
            print(type(rows))
            print(rows)
        # 释放连接池资源
        await dw_mysql_client_manager.close()
    # 运行异步函数
    asyncio.run(test())
