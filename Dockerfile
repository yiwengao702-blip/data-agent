# ============================================================
# data-agent 服务镜像（生产参考）
# 构建方式（在仓库根目录执行）：
#   docker build -t data-agent:0.1.0 .
# 运行方式（建议走 docker/docker-compose.yaml 一键编排）：
#   cd docker && docker compose up -d data-agent
#
# 设计要点：
#   1) 基于 uv 锁文件（uv.lock）可复现安装依赖，避免「本地能跑、线上依赖漂移」；
#   2) 构建阶段先装依赖再拷源码，充分利用 Docker 层缓存；
#   3) 以非 root 用户（appuser）运行，降低容器逃逸风险（企业安全基线）；
#   4) 容器内通过 uvicorn 绑定 0.0.0.0，使容器编排的网络端口映射生效；
#   5) 密钥（LLM Key）经环境变量 / env_file 注入，绝不写进镜像（见 .dockerignore）。
# ============================================================

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

# 编译依赖：asyncmy 等含 C 扩展的包需要在构建阶段用 gcc 编译
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

# 安装 uv（本项目依赖管理工具，保证与本地开发环境一致）
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# 1) 先拷贝依赖声明与锁文件，单独成层（仅 pyproject / uv.lock 变更时才重装依赖）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 2) 再拷贝源码
COPY . .

# 以非 root 用户运行（企业安全基线）
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

# 容器内绑定 0.0.0.0，使 `docker run -p 8001:8001` 的端口映射可达；
# 端口与 conf 中 server.port / compose 映射保持一致。
# 使用 uv run 复用镜像内已锁定的依赖环境，无需再激活 venv。
CMD ["uv", "run", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
