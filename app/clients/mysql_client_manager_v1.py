import asyncio
from typing import Union
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy import text
from app.conf.app_config import app_config, DBConfig


class MysqlClientManager:
    def __init__(self, db_config: DBConfig):  # 初始化方法  成员属性（成员变量 ）
        self.db_config = db_config
        # self.engine : AsyncEngine=None
        # self.engine: AsyncEngine|None = None
        # self.engine=Optional(AsyncEngine)
        self.engine: Union[AsyncEngine, None] = None

    def _get_url(self):
        # 连接数据库  数据库地址# 私有方法
        # print(f"mysql+asyncmy://{self.db_config.user}:{self.db_config.password}@{self.db_config.host}:{self.db_config.port}/{self.db_config.database}?charset=utf8mb4")
        return f"mysql+asyncmy://{self.db_config.user}:{self.db_config.password}@{self.db_config.host}:{self.db_config.port}/{self.db_config.database}?charset=utf8mb4"

    def init(self):  # 我们自己写的初始化方式
        # 创建异步引擎
        self.engine = create_async_engine(
            # 指定数据地址
            self._get_url(),
            # 设置连接池最大空闲连接数
            pool_size=10,
            # 提前检测死连接，自动替换为新连接，避免业务报错。
            pool_pre_ping=True
        )

    async def close(self):
        await self.engine.dispose()  # 断开


# 实例化
dw_mysql_client_manager = MysqlClientManager(app_config.db_dw)  # 创建对象 并把db_dw配置信息
meta_mysql_client_manager = MysqlClientManager(app_config.db_meta)  # 创建对象 并把 db_meta配置文件

if __name__ == '__main__':
    dw_mysql_client_manager.init()

    # 成功的连接 上 数据库 并取回值   连数据库
    async def test():  # 异步方式
        async with AsyncSession(dw_mysql_client_manager.engine) as session:
            # 执行sql查询
            result = await session.execute(text("select * from fact_order limit 10"))
            # 提取查询结果rows对象结构如：[(),(),()]
            # rows = result.fetchall()
            # 提取查询结果封装成字典结构如：[{},{},{}]
            rows = result.mappings().fetchall()
            # 输出返回结果类型  int  float
            print(type(rows[0]))
            # 输出首行数据
            print(rows)


    asyncio.run(test())  # 调用异步方式
