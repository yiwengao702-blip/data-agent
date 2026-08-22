from dataclasses import dataclass, field
from pathlib import Path
import os

from omegaconf import OmegaConf


# ---- 配置引导：启动时自动加载项目根目录的 .env（含 LLM Key 等密钥） ----
# 设计约束：企业级服务不应因「忘记 export 环境变量」而在 import 阶段整体崩溃。
# 这里在加载配置之前把 .env 注入 os.environ；若 .env 不存在或 dotenv 未安装也不影响启动。
def _load_env_file() -> None:
    """
    加载项目根目录的 .env 文件到环境变量（仅补充未设置的变量，不覆盖已有环境值）。
    优先使用 python-dotenv；若未安装则回退到极简 KEY=VALUE 解析器，
    保证离线 / 精简环境也能正常启动。
    """
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
    except Exception:
        # 极简回退解析：仅补充缺失项，不覆盖
        with env_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)


# 日志配置
@dataclass
class File:
    enable: bool
    level: str
    path: str
    rotation: str
    retention: str


@dataclass
class Console:
    enable: bool
    level: str


@dataclass
class LoggingConfig:
    file: File
    console: Console


# 数据库配置
@dataclass
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass
class QdrantConfig:
    host: str
    port: int
    embedding_size: int


@dataclass
class EmbeddingConfig:
    host: str
    port: int
    model: str


@dataclass
class ESConfig:
    host: str
    port: int
    index_name: str


@dataclass
class LLMConfig:
    # provider: 可插拔的 LLM 后端类型
    #   - "openai"：兼容 OpenAI 协议的远端服务（百炼/DashScope、DeepSeek、本地 vLLM 等），默认
    #   - "mock"  ：离线占位后端，返回格式正确的假数据，用于 CI / 无 Key 环境下的 self-check
    provider: str = "openai"
    model_name: str = "qwen-plus"
    api_key: str = ""
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class ServerConfig:
    host: str
    port: int


@dataclass
class AuthConfig:
    # 鉴权签名密钥：生产环境务必通过环境变量 DATA_AGENT_AUTH_SECRET 覆盖为强随机值，
    # 否则默认的占位值存在 Token 被伪造的风险。
    secret_key: str = "change-me-in-prod"
    # 登录 Token 有效期（小时）
    token_expire_hours: int = 24


@dataclass
class AppConfig:
    logging: LoggingConfig
    db_meta: DBConfig
    db_dw: DBConfig
    qdrant: QdrantConfig
    embedding: EmbeddingConfig
    es: ESConfig
    llm: LLMConfig
    server: ServerConfig
    auth: AuthConfig = field(default_factory=AuthConfig)

# Path(__file__).parents[1] / 'conf' / 'app_config.yaml'
# 配置文件路径：默认取项目根目录 conf/app_config.yaml
# 支持通过环境变量 DATA_AGENT_CONFIG 指定其他路径（便于测试/多环境部署，不改代码切换配置）
import os
# 在加载配置前先把 .env 注入环境（若存在），避免 ${oc.env:...} 因变量缺失而抛 KeyError 使服务整体崩溃
_load_env_file()
config_file = Path(os.environ.get("DATA_AGENT_CONFIG", Path(__file__).parents[2] / 'conf' / 'app_config.yaml'))
context = OmegaConf.load(config_file)
schema = OmegaConf.structured(AppConfig)
app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))



if __name__ == "__main__":
    print(app_config.llm.model_name)




