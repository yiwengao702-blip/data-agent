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

LLM：DeepSeek（经由腾讯云兼容 OpenAI 接口），用于关键词扩展、表/指标过滤、SQL 生成与校正。

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
├── server.py                # ★ FastAPI 服务入口（启动问数 API）
├── main.py                  # 元知识库构建入口（命令行）
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

## 五、配置说明（conf/app_config.yaml）

| 段 | 说明 |
|---|---|
| `db_meta` / `db_dw` | 两库连接；`db_meta` 存元知识库，`db_dw` 是业务数仓 |
| `qdrant` | 向量库地址，`embedding_size=1024` 须与模型维度一致 |
| `embedding` | TEI 向量化服务地址（默认 `:8081`） |
| `es` | Elasticsearch 地址与索引名 |
| `llm` | 大模型（DeepSeek）的 model / api_key / base_url |
| `server` | API 监听 `host` / `port` |
| `logging` | 日志输出到控制台 + 文件（`logs/app.log`） |

## 六、本次优化变更清单

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

## 七、常见问题

- **`MissingGreenlet: greenlet_spawn has not been called`**：历史版本的两个 async SQLAlchemy 配置坑（见上文 4、5），已修复；若自行升级 SQLAlchemy 需注意。
- **Elasticsearch 容器反复退出（exit 137）**：内存不足被 OOM Kill，已通过限制 JVM 堆解决。
- **问数接口报错 `403 套餐包被禁用`**：LLM 账号的调用套餐被禁用/过期（与代码无关），请到腾讯云控制台检查 `app_config.yaml` 中 `llm.api_key` 对应的套餐包状态。
- **`from Lib import xxx` 报错 `ModuleNotFoundError`**：旧代码写法，已修复；如还遇到请改用标准库导入。
- **`python main.py` 报 `TypeError: build() got an unexpected keyword argument 'reset'`**：旧版本入口与函数签名不一致，已修复。
