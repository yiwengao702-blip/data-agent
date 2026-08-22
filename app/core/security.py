# app/core/security.py
# 鉴权安全工具：密码哈希（PBKDF2-HMAC-SHA256）与轻量 JWT（HS256，纯标准库实现）。
#
# 设计取舍：项目当前未引入 passlib / PyJWT（离线环境），这里用标准库实现等价能力，
# 避免新增依赖带来的安装与网络风险。生产环境请将签名密钥通过环境变量
# DATA_AGENT_AUTH_SECRET 覆盖为强随机值（见 app_config.auth.secret_key）。

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from app.conf.app_config import app_config

# ---- 密码哈希：PBKDF2-HMAC-SHA256 ----
_PBKDF2_ALGO = "sha256"
_PBKDF2_ITERS = 200_000


def hash_password(password: str) -> str:
    """对明文密码做加盐哈希，返回可安全存储的格式：pbkdf2_<algo>$<iters>$<salt_hex>$<hash_hex>"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2_{_PBKDF2_ALGO}${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """恒定时间校验明文密码与存储哈希是否匹配；格式异常一律返回 False。"""
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$")
        iters = int(iters_s)
        algo_name = algo.replace("pbkdf2_", "")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac(algo_name, password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---- 轻量 JWT（HS256，纯标准库） ----
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_str(s: str) -> str:
    return _b64url(s.encode("utf-8"))


def _get_secret() -> str:
    # 环境变量优先，其次配置默认值（生产必须用环境变量覆盖）
    return os.getenv("DATA_AGENT_AUTH_SECRET", app_config.auth.secret_key)


def create_access_token(username: str, expire_hours: Optional[int] = None) -> str:
    """为指定用户名签发 HS256 JWT，载荷含 sub / iat / exp。"""
    exp_h = expire_hours if expire_hours is not None else app_config.auth.token_expire_hours
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": username, "iat": now, "exp": now + exp_h * 3600}
    seg1 = _b64url_str(json.dumps(header, separators=(",", ":")))
    seg2 = _b64url_str(json.dumps(payload, separators=(",", ":")))
    signing_input = f"{seg1}.{seg2}".encode("ascii")
    sig = hmac.new(_get_secret().encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{seg1}.{seg2}.{_b64url(sig)}"


def decode_access_token(token: str) -> Optional[str]:
    """校验并解析 HS256 JWT，返回用户名；签名错误 / 过期 / 格式非法返回 None。"""
    try:
        seg1, seg2, seg3 = token.split(".")
    except ValueError:
        return None
    signing_input = f"{seg1}.{seg2}".encode("ascii")
    expected = hmac.new(_get_secret().encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url(expected), seg3):
        return None
    try:
        # 补齐 base64 padding 后解码
        payload = json.loads(base64.urlsafe_b64decode(seg2 + "==="))
    except Exception:
        return None
    if "exp" in payload and int(payload["exp"]) < int(time.time()):
        return None
    return payload.get("sub")
