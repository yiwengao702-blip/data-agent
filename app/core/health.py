# app/core/health.py
# 运行时依赖探活：企业级服务不能只返回 {"status":"ok"}，还要回答「下游都活着吗」。
# /api/health 据此给出每个依赖（LLM / MySQL / Qdrant / ES / Embedding）的真实连通状态与耗时。
import time
from datetime import datetime, timezone

from sqlalchemy import text

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import dw_mysql_client_manager, meta_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.conf.app_config import app_config
from app.core.log import logger


async def _probe(label: str, awaitable):
    """
    统一探测某个依赖：记录耗时，异常时返回 error（绝不因单点故障而整体崩溃）。
    :param awaitable: 一个可 await 的对象（协程）
    """
    start = time.monotonic()
    try:
        await awaitable
        return {"status": "ok", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        logger.warning(f"依赖探活失败 [{label}]: {e}")
        # 截断异常文本，避免把敏感堆栈塞进健康接口响应
        return {
            "status": "error",
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
            "detail": str(e)[:200],
        }


async def _mysql_ok(manager):
    """MySQL 连通性：执行 SELECT 1；manager 未初始化（engine=None）时明确报错。"""
    if manager.engine is None:
        raise RuntimeError("MySQL 客户端未初始化（服务启动未完成或 lifespan 未执行）")
    async with manager.session_factory() as session:
        await session.execute(text("SELECT 1"))


async def _client_ok(manager, probe_fn, label: str):
    """
    通用客户端探活守卫：先判断 manager.client 是否为 None（lifespan 未执行 / 启动未完成），
    为 None 时显式抛出清晰错误（交由 _probe 捕获为 error 条目，绝不 500）；
    否则执行 probe_fn(client) 进行真实连通性探测。
    这样可避免「在参数求值阶段直接访问 None.xxx() 抛出 AttributeError 导致接口崩溃」的隐患。
    :param manager: 客户端管理器（含 .client 属性）
    :param probe_fn: 接收已初始化 client、返回可 await 对象的探测函数
    :param label: 依赖中文名（用于错误描述）
    """
    client = manager.client
    if client is None:
        raise RuntimeError(f"{label} 客户端未初始化（服务启动未完成或 lifespan 未执行）")
    await probe_fn(client)


async def check_health() -> dict:
    """汇总各依赖状态，返回结构化健康报告。"""
    deps: dict = {}

    # LLM：mock 模式视为离线可用；openai 模式校验 Key 是否配置（真实连通性由实际问数验证）
    if (app_config.llm.provider or "openai").lower() == "mock":
        deps["llm"] = {"status": "ok", "provider": "mock", "note": "离线占位后端"}
    else:
        key_ok = bool(app_config.llm.api_key) and app_config.llm.api_key != "missing-api-key"
        deps["llm"] = {
            "status": "ok" if key_ok else "error",
            "provider": "openai",
            "model": app_config.llm.model_name,
            "detail": None if key_ok else "未配置 DATA_AGENT_LLM_API_KEY",
        }

    # MySQL（meta / dw 两套）
    deps["mysql_meta"] = await _probe("mysql_meta", _mysql_ok(meta_mysql_client_manager))
    deps["mysql_dw"] = await _probe("mysql_dw", _mysql_ok(dw_mysql_client_manager))

    # Qdrant
    deps["qdrant"] = await _probe(
        "qdrant",
        _client_ok(qdrant_client_manager, lambda c: c.get_collections(), "Qdrant"),
    )

    # Elasticsearch
    deps["elasticsearch"] = await _probe(
        "elasticsearch",
        _client_ok(es_client_manager, lambda c: c.ping(), "Elasticsearch"),
    )

    # Embedding（轻量探测一次向量化，确认 TEI 服务可达）
    deps["embedding"] = await _probe(
        "embedding",
        _client_ok(embedding_client_manager, lambda c: c.aembed_query("健康检查探测"), "Embedding"),
    )

    # 整体状态：核心依赖（llm / mysql / qdrant / es）全部 ok 才算 ok，否则 degraded
    critical = ["llm", "mysql_meta", "mysql_dw", "qdrant", "elasticsearch"]
    overall = "ok" if all(deps[k]["status"] == "ok" for k in critical) else "degraded"

    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": deps,
    }
