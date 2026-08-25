# app/core/audit.py
# 接口级审计日志：记录「谁 / 何时 / 调用了哪个接口 / 结果如何」，用于企业合规与问题追溯。
#
# 设计：
# - 复用 app.core.log 已配置好的 loguru logger（自带 request_id 注入），仅通过 extra.audit=True
#   将审计条目路由到独立的 logs/audit.log（见 log.py 的过滤 sink），不影响业务日志文件。
# - 审计条目形如：METHOD path -> status | duration_ms | ip | user

# 复用已配置好的 logger（app.core.log 已打 patch 注入 request_id，且装配了 audit.log 过滤 sink）。
# 注意：必须从 app.core.log 导入，而非裸 from loguru import logger —— 否则绑定到未被
# inject_request_id patch 的 root logger，日志格式里的 {extra[request_id]} 会 KeyError 导致整条审计落盘失败。
from app.core.log import logger

# 绑定 audit 标签，使该 logger 输出的记录被 audit.log 过滤 sink 捕获
_audit_logger = logger.bind(audit=True)


def log_api_access(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    client_ip: str,
    user: str | None,
) -> None:
    """记录一次 API 访问的审计信息。"""
    _audit_logger.info(
        "{method} {path} -> {status} | {dur}ms | ip={ip} | user={user}".format(
            method=method,
            path=path,
            status=status_code,
            dur=duration_ms,
            ip=client_ip,
            user=user or "anonymous",
        )
    )
