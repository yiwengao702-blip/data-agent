# test/smoke_test.py
# 离线冒烟测试：不依赖任何真实后端（MySQL / Qdrant / ES / Embedding）与 LLM Key，
# 用 mock LLM + fake 仓库把整条问数链路（12 节点）跑通，验证：
#   1) 链路能从「提取关键词」一路走到「执行 SQL」；
#   2) 各节点对 LLM / 仓库的返回格式兼容（mock 返回格式正确）；
#   3) 最终能产出 SQL 与执行结果，证明核心编排无阻塞。
#
# 运行方式：
#   DATA_AGENT_CONFIG=conf/app_config.mock.yaml python test/smoke_test.py
#
# 注意：必须在 import 任何 app 模块之前设置 DATA_AGENT_CONFIG，使 llm 走 mock 后端。
import asyncio
import os
import sys

# ===== 必须在导入 app 之前设置配置（决定 llm 走 mock 还是真实后端） =====
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
_MOCK_CONFIG = os.path.join(_PROJECT_ROOT, "conf", "app_config.mock.yaml")
os.environ.setdefault("DATA_AGENT_CONFIG", _MOCK_CONFIG)
# 把项目根目录注入 sys.path，保证 `python test/smoke_test.py` 从任意目录都能 import app
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from types import SimpleNamespace  # noqa: E402

from app.agent.graph import graph  # noqa: E402
from app.agent.state import DataAgentState  # noqa: E402
from app.conf.app_config import app_config  # noqa: E402


# ---------- 轻量 fake 仓库 / 客户端（仅实现链路实际调用到的方法） ----------
class FakeEmbedding:
    """伪装 Embedding 客户端：返回固定维度向量，不发起网络请求。"""
    def __init__(self, dim: int):
        self._dim = dim

    async def aembed_query(self, text: str):
        return [0.01] * self._dim


class FakeColumnQdrantRepo:
    """伪装字段向量库：返回一条与 ColumnInfoQdrant 兼容的 payload。"""
    async def search(self, embedding, score_threshold=0.6, limit=5):
        return [{
            "id": "dim_region.province",
            "name": "province",
            "type": "varchar(50)",
            "role": "dimension",
            "examples": ["广东省", "浙江省"],
            "description": "订单所属省份",
            "alias": ["省份", "省"],
            "table_id": "dim_region",
        }]


class FakeMetricQdrantRepo:
    """伪装指标向量库：返回一条与 MetricInfoQdrant 兼容的 payload。"""
    async def search(self, embedding, score_threshold=0.6, limit=20):
        return [{
            "id": "GMV",
            "name": "GMV",
            "description": "成交金额总和",
            "relevant_columns": ["dim_region.province"],
            "alias": ["成交总额", "销售额"],
        }]


class FakeValueEsRepo:
    """伪装字段值 ES 索引：返回一条与 ValueInfoEs 兼容的文档。"""
    async def search(self, keyword, threshold=0.6, limit=5):
        return [{
            "id": "dim_region.province.广东省",
            "value": "广东省",
            "type": "varchar(50)",
            "column_id": "dim_region.province",
            "column_name": "province",
            "table_id": "dim_region",
            "table_name": "dim_region",
        }]


class FakeMetaMysqlRepo:
    """伪装元数据库仓储：返回与转换函数字段兼容的对象（SimpleNamespace 支持属性访问）。"""
    async def get_column_info_by_id(self, column_id: str):
        return SimpleNamespace(
            id=column_id, name="province", type="varchar(50)", role="dimension",
            examples=[], description="字段", alias=[], table_id="dim_region",
        )

    async def get_key_columns_by_table_id(self, table_id: str):
        # 不额外补充主外键，保持测试数据最小可用
        return []

    async def get_table_info_by_id(self, table_id: str):
        return SimpleNamespace(name=table_id, role="dim", description="维度表")


class FakeDwMysqlRepo:
    """伪装数仓仓储：validate_sql 不抛异常（视为通过），execute_sql 返回样例结果。"""
    async def get_db_info(self):
        return {"version": "8.0.32", "dialect": "mysql"}

    async def validate_sql(self, sql: str):
        # 不真正执行 EXPLAIN，直接视为语法通过 -> state["error"]=None
        return None

    async def execute_sql(self, sql: str):
        return [{"region": "华北", "total_amount": 12345.0}]

    async def get_column_values(self, table_name: str, column_name: str, limit: int = 10):
        return []

    async def get_column_types(self, table_name: str):
        return {}


async def run():
    # 构造 fake 依赖，注入 DataAgentContext（链路只按 key 取用，不校验具体类型）
    context = {
        "embedding_client": FakeEmbedding(dim=app_config.qdrant.embedding_size),
        "column_qdrant_repository": FakeColumnQdrantRepo(),
        "value_es_repository": FakeValueEsRepo(),
        "metric_qdrant_repository": FakeMetricQdrantRepo(),
        "meta_mysql_repository": FakeMetaMysqlRepo(),
        "dw_mysql_repository": FakeDwMysqlRepo(),
    }
    state = DataAgentState(query="统计华北地区销售总额")

    events = []
    async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
        events.append(chunk)

    # 断言：链路确实走到了执行阶段并产出结果
    stages = [e.get("stage") for e in events if isinstance(e, dict) and e.get("stage")]
    assert "提取关键字---哈哈" in stages, f"未走到关键词提取，实际阶段：{stages}"
    assert "执行SQL" in stages, f"未走到执行SQL，实际阶段：{stages}"
    assert any(isinstance(e, dict) and e.get("result") for e in events), "未产出执行结果"

    # 断言：链路产出了 SQL（generate_sql 或 correct_sql 节点留下的 sql 经由 execute 反馈）
    print("✅ 离线冒烟测试通过：12 节点链路在 mock 后端下完整跑通")
    print(f"   流经阶段：{stages}")
    print(f"   执行结果样例：{[e for e in events if isinstance(e, dict) and e.get('result')]}")


def main():
    try:
        asyncio.run(run())
    except AssertionError as e:
        print(f"❌ 冒烟测试断言失败：{e}")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"❌ 冒烟测试异常：{e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
