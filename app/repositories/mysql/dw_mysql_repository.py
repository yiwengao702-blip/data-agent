# app/repositories/mysql/dw_mysql_repository.py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DwMysqlRepository:
    def __init__(self, session: AsyncSession):
        self.session = session  # 拿到数据库连接

    async def get_column_values(self, table_name: str, column_name: str, limit: int = 10):
        """
        查询指定字段的取值

        :param table_name:
        :param column_name:
        :return: ["C001","C002","C003","C004","C005"]
        """
        # 定义sql
        # 'select distinct province from dim_region limit 10000'
        sql = f"select distinct {column_name} from {table_name} limit {limit}"
        # 执行sql
        result = await self.session.execute(text(sql))
        # [row(C001),row(C002),row(C003)]
        return result.scalars().fetchall()

    async def get_column_types(self, table_name: str):
        """

        查询表中字段的类型
        :param table_name:
        :return: 字段 {"字段名":"字段类型"}
        """
        # 定义sql  desc 表名   字段  类型
        sql = f"show columns from {table_name}"
        # 执行sql
        result = await self.session.execute(text(sql))
        # [row(),row(),row()]

        # 获取结果，组装数据
        return {row.Field: row.Type for row in result.fetchall()}

    async def get_db_info(self):
        """
        查询数据库环境信息，版本、方言
        :return:
        """
        # 查询数据版本
        result = await self.session.execute(text("select version()"))
        # 解析结果
        version = result.scalar()

        # 查询数据方言
        dialect = self.session.get_bind().dialect.name
        return {"version": version, "dialect": dialect}

    async def validate_sql(self, sql: str):
        """
        验证执行sql
        :param sql:
        :return: 如果sql语法不合法，会抛出异常
        """
        await self.session.execute(text(f"explain {sql}"))

    async def execute_sql(self, sql):
        """
        执行最终的sql语句，获取结果
        :param sql:
        :return:
        """
        result = await self.session.execute(text(sql))
        return [dict(row) for row in result.mappings().fetchall()]
