# data-agent（NL2SQL 问数服务）

基于 **LangGraph + 元知识库（RAG）** 的自然语言问数系统：把业务库表结构、字段取值、指标口径向量化/全文索引，用户用自然语言提问，系统自动召回相关字段与指标、过滤无关表、生成并校验 SQL，最终在数仓执行返回结果。

## 一、整体架构

```
自然语言问题
   │
   ▼
LangGraph 工作流（12 节点，SSE 流式推进）
   extract_keywords
   ├─ recall_column / recall_metric / recall_value   （三路并行召回）
   ├─ merge_retrieved_info
   ├─ filter_metric / filter_table
   ├─ add_extra_context
   ├─ generate_sql
   ├─ validate_sql ──(失败)──▶ correct_sql ──▶ execute_sql
   └─ execute_sql
   │
   ▼
FastAPI SSE 流式接口 /api/query
```

下游依赖（用 Docker 一键起）：
- **MySQL 8.0**：`dw`（数仓，存业务数据）+ `meta`（元知识库，存表/字段/指标元数据）
- **Qdrant 1.16**：字段向量库 `data-agent-column`、指标向量库 `data-agent-metric`
- **Elasticsearch 8.19（含 IK 中文分词）**：字段取值全文索引 `data-agent-values`
- **HuggingFace TEI（bge-large-zh-v1.5 CPU）**：向量化模型服务

LLM：默认接入 **阿里云百炼（DashScope）OpenAI 兼容接口**（`qwen-plus`），用于关键词扩展、表/指标过滤、SQL 生成与校正。后端可插拔：改用 DeepSeek / 本地 vLLM 等任何 OpenAI 兼容服务，只需改 `conf/app_config.yaml` 的 `llm` 段；`provider=mock` 时完全离线（无需 Key 与外部依赖）。

## 二、目录结构

```
data-agent/
├── docker/                  # 依赖服务编排（mysql / elasticsearch / qdrant / embedding）
│   ├── docker-compose.yaml  # 一键启动 4 个依赖服务
│   ├── mysql/               # 初始化 SQL（dw.sql / meta.sql）
│   ├── elasticsearch/       # 带 IK 插件的 ES 镜像构建
│   └── embedding/           # bge-large-zh-v1.5 模型文件
├── conf/
│   ├── app_config.yaml      # 全局配置（DB / Qdrant / ES / Embedding / LLM / 服务端口）
│   └── meta_config.yaml     # 元知识库配置（要导入哪些表、字段、指标）
├── prompts/                 # 各节点的 LLM 提示词模板
├── app/
│   ├── agent/               # LangGraph 图 + 节点 + 上下文/状态定义
│   ├── clients/             # MySQL / Qdrant / ES / Embedding 客户端管理器
│   ├── repositories/        # 数据持久层（MySQL / Qdrant / ES）
│   ├── models/              # SQLAlchemy ORM 模型 + Qdrant/ES 数据结构
│   ├── services/            # 业务服务（meta_knowledge_service / query_service）
│   ├── api/                 # FastAPI 路由 + 依赖注入
│   ├── conf/                # 配置 dataclass 定义
│   ├── core/                # 日志、lifespan 生命周期
│   └── prompt/              # 提示词加载器（带缓存）
├── server.py                # ★ FastAPI 服务入口（启动问数 API + 托管前端）
├── main.py                  # 元知识库构建入口（命令行）
├── frontend/                # 可视化问数前端（原生 HTML/CSS/JS，零构建，由 FastAPI 托管）
└── pyproject.toml
```

> 历史教学残留（可安全删除，不影响运行）：`app/clients/mysql_client_manager_v1.py`、`app/conf/text_config.py`、`conf/text_config.yaml`、`prompts/plan_sql.prompt`、`test/` 目录下除 `test.py` 外的 demo 文件。

## 三、环境要求

- Python 3.11（使用项目内置 `uv` 虚拟环境 `.venv`，驱动 `asyncmy`）
- Docker Desktop（用于启动依赖服务）
- 可用内存建议 ≥ 8GB（Elasticsearch 默认较吃内存，已在 compose 中限制 JVM 堆为 512MB）

## 四、快速开始

### 1. 启动依赖服务

```bash
cd docker
docker compose up -d
```

会启动 mysql(3306) / elasticsearch(9200) / qdrant(6333) / embedding(8081)。
MySQL 首次启动会按 `mysql/*.sql` 自动建 `dw`、`meta` 库并灌入演示维度数据。

> 若本机 3306 端口已被其他项目占用，请先停掉冲突容器，或修改 `docker-compose.yaml` 中 mysql 的端口映射（同时改 `conf/app_config.yaml` 的 `db_meta/db_dw.port`）。

### 2. 构建元知识库

把 `conf/meta_config.yaml` 里配置的表结构、字段取值、指标口径写入 MySQL meta / Qdrant / ES：

```bash
# 默认配置
python main.py

# 指定配置 + 清空重建（先删 Qdrant 两集合、ES 索引、meta 四张表再导入）
python main.py -c conf/meta_config.yaml -r
```

构建完成后可重复执行，写入采用「先按主键删除、再批量插入」的 upsert 语义，不会因主键冲突报错。

### 3. 启动问数 API

```bash
python server.py
# 默认监听 http://127.0.0.1:8001，端口可在 conf/app_config.yaml 的 server 段修改
```

### 4. 调用示例

健康检查：

```bash
curl http://127.0.0.1:8001/api/health
# {"status":"ok","service":"data-agent"}
```

问数（SSE 流式）：

```bash
curl -N -X POST http://127.0.0.1:8001/api/query \
  -H "Content-Type: application/json" \
  -d '{"query":"统计2025年各地区销售总额"}'
```

返回为 SSE：`data: {"stage":"提取关键字"}` → `{"stage":"召回列数据"}` → … → `{"sql":"..."}` → `{"result":[...]}`。
（Python 客户端见 `test/test.py`。）

### 5. 可视化前端（Web UI）

服务内置一个**纯静态、零构建**的问数前端（商务风），由 FastAPI 直接托管，开箱即用：

- 启动服务后，浏览器打开 **http://127.0.0.1:8001/**（自动跳转到 `/ui/`）；
- 在输入框提出问题，界面会**实时流式**展示 12 个阶段进度、生成的 SQL、以及查询结果表格；
- 顶栏「健康状态」实时反映各下游依赖（LLM/MySQL/Qdrant/ES/Embedding）连通情况，点击可手动刷新；
- 提供「演示（模拟流式）」按钮：**无需启动任何后端依赖**，即可本地预览完整界面与流式效果（便于演示与界面验收）。

前端文件位于 `frontend/`（`index.html` / `styles.css` / `app.js`），样式与交互均为原生实现，不引入任何前端构建工具链。对接的接口：

- 问数：`POST /api/query`（`{"query":"..."}`，SSE 流式返回）
- 探活：`GET /api/health`

## 五、配置说明（conf/app_config.yaml）

| 段 | 说明 |
|---|---|
| `db_meta` / `db_dw` | 两库连接；`db_meta` 存元知识库，`db_dw` 是业务数仓 |
| `qdrant` | 向量库地址，`embedding_size=1024` 须与模型维度一致 |
| `embedding` | TEI 向量化服务地址（默认 `:8081`） |
| `es` | Elasticsearch 地址与索引名 |
| `llm` | 大模型后端：provider（openai / mock）、model_name、api_key（**经环境变量注入，禁止硬编码**）、base_url |
| `server` | API 监听 `host` / `port` |
| `logging` | 日志输出到控制台 + 文件（`logs/app.log`） |

## 六、密钥注入与运行配置（安全）

本项目对密钥采用「环境变量 + `.env` 文件」的隔离模式，杜绝把明文 Key 提交进版本库：

- **`.env`**（已被 `.gitignore` 忽略，**绝不入库**）：存放真实 `DATA_AGENT_LLM_API_KEY` 等密钥，从仓库根目录的 `.env.example` 复制而来：
  ```bash
  cp .env.example .env
  # 然后编辑 .env，填入阿里云百炼控制台获取的 Key
  ```
- **`.env.example`**（可提交模板）：仅含占位符与说明，不含任何真实密钥。
- **自动加载**：服务启动加载配置时（`app/conf/app_config.py`）会自动读取项目根目录的 `.env` 注入环境变量，**无需手动 `export`**。即便 `.env` 缺失或 Key 为空，配置解析也会优雅降级为空字符串（不再因 `KeyError` 在 import 阶段整体崩溃），真实鉴权错误会在实际调用时由上层转成中文提示。
- **LLM 后端可插拔**：默认接入阿里云百炼（`qwen-plus`）。切换为 DeepSeek / 本地 vLLM 等任意 OpenAI 兼容服务，只需改 `conf/app_config.yaml` 的 `llm` 段（`provider` / `model_name` / `base_url` / `api_key` 来源）；设 `provider: mock` 则完全离线（见下）。
- **多环境**：通过环境变量 `DATA_AGENT_CONFIG` 指定配置文件路径（如 `conf/app_config.docker.yaml`），实现不改代码切换配置。

> ⚠️ **历史密钥已泄露，必须轮换**：早期版本曾在 `conf/app_config.yaml` 中硬编码过一条 DeepSeek 明文 Key，该密钥已视为泄露，请**立即在对应控制台停用 / 重新生成**，切勿继续使用。当前版本已从配置中彻底移除硬编码密钥。

## 七、离线自检与冒烟测试

无需任何真实后端（MySQL / Qdrant / ES / Embedding）与 LLM Key，即可验证整条问数链路（12 节点）能跑通：

```bash
# mock 后端：llm.provider=mock，配合 fake 仓库跑通整图
DATA_AGENT_CONFIG=conf/app_config.mock.yaml python test/smoke_test.py
```

测试通过会打印流经的全部阶段（提取关键字 → 三路召回 → 合并 → 过滤 → 加上下文 → 生成 SQL → 校验 → 执行），并产出样例执行结果。该测试可作为 CI 的自检门槛。

## 八、容器化部署（Docker）

提供生产参考镜像与一键编排：

```bash
# 1) 构建并启动全部依赖 + data-agent 服务
cd docker
docker compose up -d            # 含 mysql / elasticsearch / qdrant / embedding / data-agent

# 2) 查看问数服务健康状态（容器内已配置 /api/health 探活 + compose healthcheck）
curl http://127.0.0.1:8001/api/health
```

- 镜像构建见仓库根目录 `Dockerfile`：基于 `python:3.11-slim`，用 `uv` 按 `uv.lock` 可复现安装依赖，以非 root 用户运行；密钥经 `env_file: ../.env` 注入，**绝不打进镜像**（`.dockerignore` 已排除 `.env`）。
- 容器内 `data-agent` 通过 `conf/app_config.docker.yaml` 把下游依赖 host 指向 compose 服务名（`mysql` / `qdrant` / `elasticsearch` / `embedding`），与默认 `localhost` 配置区分。
- 端口映射 `8001:8001`；如需改端口，同步修改 `conf/app_config.docker.yaml` 的 `server.port` 与 compose 映射。

## 九、本次优化变更清单

> 2026-10-13，针对「可直接运行 + 健壮性」做的修复与增强。

**P0 — 阻塞级 Bug（已修）**
1. `main.py` 调用 `build(config_path, reset=...)` 但 `build()` 无 `reset` 形参 → 原命令直接 `TypeError`。已统一签名，并实现 `--reset` 重置逻辑（清空 Qdrant/ES/meta 后重建）。
2. `from Lib.argparse import ...` 与 `from Lib import uuid` 依赖 uv 虚拟环境把基础 Python `Lib` 目录塞进 `sys.path` 的巧合，换机器必崩 → 改回标准 `argparse` / `uuid`。
3. **无 FastAPI 服务入口**：`app/api/`、`app/core/lifespan.py` 原是死代码，无任何 `FastAPI()` 实例 → 新建 `server.py` 补齐 `/api/query` + `/api/health`。

**P1 — 健壮性与正确性（已修）**
4. 异步 MySQL 会话 `pool_pre_ping=True` 与 `asyncmy` 不兼容（连接检出时同步 ping 抛 `MissingGreenlet`）→ 关闭。
5. 异步会话 `expire_on_commit=True` 导致跨 `await` 访问已提交 ORM 对象属性时触发同步懒加载、抛 `MissingGreenlet` → 改为 `False`（异步最佳实践）。
6. 元知识库写入：`meta_mysql_repository.save_*` 原为纯 `add_all`，重复构建主键冲突必炸 → 改为「先删后插」upsert 语义。
7. ES `upsert_values` 的 `bulk` 未检查响应错误（失败静默）→ 现在校验 `errors` 并抛出。
8. `app/agent/graph.py` 模块级 `print(graph...print_ascii())` 在 import 时执行、污染日志 → 移入 `__main__`。
9. `graph.py` 缺少 `app_config` 中 `server` 段及环境变量 `DATA_AGENT_CONFIG` 覆盖（便于多环境/测试切换配置）。
10. `docker-compose.yaml` 的 Elasticsearch 未限制 JVM 堆，单机内存不足时会被 OOM Kill（exit 137）→ 增加 `ES_JAVA_OPTS: -Xms512m -Xmx512m`。

**P2 — 性能与防御（已修）**
11. `recall_column/recall_metric/recall_value` 三节点对每个关键词串行 `await` → 改为 `asyncio.gather` + 信号量（并发上限 8），整体召回耗时显著下降。
12. `prompt_loader` 每次节点调用都读盘 → 加 `lru_cache`。
13. `filter_metric/filter_table` 对 LLM 返回结构无防御 → 增加类型校验，异常时保留全量不误删。

**P3 — 企业级可用性与安全（已修，2026-10-13 第二轮）**
14. **密钥安全化**：从 `conf/app_config.yaml` 彻底移除硬编码的 DeepSeek 明文 Key（视为已泄露）；LLM Key 改为经环境变量 `DATA_AGENT_LLM_API_KEY` 注入。新增 `.env`（gitignore 忽略，**绝不入库**）+ `.env.example`（可提交模板）双层隔离。
15. **配置崩溃修复**：`${oc.env:DATA_AGENT_LLM_API_KEY}` 在变量缺失时会抛 `KeyError` 导致整个服务在 import 阶段崩溃 → 改为带空默认值 `${oc.env:DATA_AGENT_LLM_API_KEY,""}`，并在加载配置前自动读取 `.env` 注入环境（无需手动 export），缺失变量也不致命。
16. **LLM 后端可插拔**：`app/agent/llm.py` 重构为工厂模式，`provider=openai`（默认，兼容百炼/DeepSeek/本地 vLLM 等 OpenAI 协议服务）/ `provider=mock`（离线占位，返回格式正确的假数据）。远端客户端加 `with_retry`（指数退避，至多 3 次）提升链路韧性；新增 `describe_llm_error` 把 401/403/429/超时/欠费(Arrearage) 转成中文可读、可操作的提示。
17. **SSE 错误韧性**：`query_service.py` 在异常时推送结构化错误事件（`{"type":"error",...}`）后再发 `data: [DONE]`，客户端永不挂起。
18. **真实健康检查**：新增 `app/core/health.py`，`/api/health` 汇总 LLM / MySQL(meta+dw) / Qdrant / ES / Embedding 的真实连通状态与耗时，整体状态为 `ok` / `degraded`，可作为容器探活与上线自检。
19. **离线冒烟测试**：新增 `test/smoke_test.py`，`DATA_AGENT_CONFIG=conf/app_config.mock.yaml` 驱动 mock LLM + fake 仓库跑通 12 节点全链路，作为 CI 自检门槛；新增 `conf/app_config.mock.yaml`。
20. **容器化部署**：新增仓库根目录 `Dockerfile`（python:3.11-slim + uv 锁文件可复现安装 + 非 root 运行）、`.dockerignore`（排除 `.env`/`.venv`/日志等，杜绝密钥入镜像）、`conf/app_config.docker.yaml`（下游 host 改 compose 服务名），并在 `docker/docker-compose.yaml` 增加 `data-agent` 服务（含 `/api/health` healthcheck 与 `env_file: ../.env` 注入密钥）。
21. **可视化前端（Web UI）**：新增 `frontend/`（原生 HTML/CSS/JS，零构建）作为问数控制台，由 `server.py` 通过 `StaticFiles` 托管在 `/ui`（根路径 `/` 自动重定向）；支持 SSE 实时阶段时间线、SQL 展示与复制、结果表格渲染、错误提示、`/api/health` 探活轮询，并内置「演示（模拟流式）」可在无后端依赖时预览。
22. **SQL 流式透出**：`generate_sql` / `correct_sql` 节点在生成/校正后额外 `writer({"sql": ...})`，使生成的 SQL 在 `stream_mode="custom"` 下也能经 SSE 触达前端（原先仅写入状态、客户端拿不到 SQL）。

## 十、常见问题

- **`MissingGreenlet: greenlet_spawn has not been called`**：历史版本的两个 async SQLAlchemy 配置坑（见上文 4、5），已修复；若自行升级 SQLAlchemy 需注意。
- **Elasticsearch 容器反复退出（exit 137）**：内存不足被 OOM Kill，已通过限制 JVM 堆解决。
- **问数接口报错 `403 套餐包被禁用` / `Arrearage` / `账户状态异常`**：LLM 账号的调用套餐被禁用/过期，或**阿里云账户存在欠费 / 未实名认证**（返回 `400 Arrearage: Access denied, please make sure your account is in good standing`）。这是账户侧问题，与代码无关：请到阿里云百炼控制台处理账户状态（充值 / 实名 / 开通模型）后重试。代码已把此类错误转成中文可读提示。
- **服务启动即崩溃，报 `KeyError: Environment variable 'DATA_AGENT_LLM_API_KEY' not found`**：旧版本 `${oc.env:...}` 在变量缺失时会抛 KeyError 导致整体崩溃。当前版本已在加载配置前自动读取 `.env`，并给默认值；若仍报此错，请确认项目根目录 `.env` 存在且含 `DATA_AGENT_LLM_API_KEY`（或已通过环境变量注入）。
- **`from Lib import xxx` 报错 `ModuleNotFoundError`**：旧代码写法，已修复；如还遇到请改用标准库导入。
- **`python main.py` 报 `TypeError: build() got an unexpected keyword argument 'reset'`**：旧版本入口与函数签名不一致，已修复。
