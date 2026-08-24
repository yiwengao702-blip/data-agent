from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.conf.app_config import app_config
from app.core.log import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FastApi启动器执行的初始化逻辑
    # 初始化客户端对象
    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    # 企业级安全自检：若鉴权签名密钥仍为默认占位值，生产环境存在 Token 被伪造风险，给出强告警
    if app_config.auth.secret_key == "change-me-in-prod":
        logger.warning(
            "⚠️ 安全告警：auth.secret_key 仍为默认占位值，Token 可被任意伪造。"
            "生产部署请通过环境变量 DATA_AGENT_AUTH_SECRET 设置为强随机值。"
        )

    yield
    # FastApi结束后执行的释放资源逻辑
    # 关闭客户端
    await qdrant_client_manager.close()
    await es_client_manager.close()
    await meta_mysql_client_manager.close()
    await dw_mysql_client_manager.close()
