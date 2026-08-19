# app/agent/llm.py
# LLM 客户端：可插拔的模型后端，支撑「真实远端服务」与「离线 mock 后端」两种模式。
# - provider=openai  ：兼容 OpenAI 协议的远端服务（默认接入阿里云百炼 / DashScope，亦可换 DeepSeek、本地 vLLM 等）
# - provider=mock    ：离线占位后端，按提示词任务返回格式正确的假数据，用于 CI / 无 Key 环境的 self-check
# 设计约束：本模块在 import 阶段绝不因缺 Key 而崩溃（构造时即使无 Key 也仅用占位值，真实鉴权错误在实际调用时由上游返回）

import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.conf.app_config import app_config


class LLMError(Exception):
    """LLM 客户端相关的统一异常，便于上层（query_service）识别并给出可读提示。"""


def describe_llm_error(e: Exception) -> str:
    """
    把上游 LLM 异常转成中文可读、可操作的描述。
    真实项目的「可诊断性」：排查人员看到一句话就知道该查 Key、套餐还是网络。
    """
    msg = str(e)
    low = msg.lower()
    if "401" in msg or "authentication" in low or "unauthorized" in low:
        return "LLM 鉴权失败（401）：API Key 无效或未配置，请检查环境变量 DATA_AGENT_LLM_API_KEY"
    if "arrearage" in low or "overdue" in low or "good standing" in low:
        return "LLM 账户状态异常（欠费/未实名）：阿里云百炼账户存在欠费或未实名认证，已拒绝访问，请到阿里云控制台处理账户状态后再试"
    if "403" in msg or "permission" in low or "forbidden" in low or "access denied" in low:
        return "LLM 访问被拒绝（403）：API Key 对应套餐可能受限、被禁用或账户无权调用该模型，请更换 Key / 套餐或检查模型开通情况"
    if "429" in msg or "rate" in low or "quota" in low:
        return "LLM 触发限流（429）：请求过频或额度耗尽，请稍后重试或升级套餐"
    if "timeout" in low or "timed out" in low:
        return "LLM 请求超时：服务网络不通或响应过慢，请检查 base_url 与网络连通性"
    # 502 / Connection refused：远端模型服务（如本地 vLLM / TGI）未启动，或 base_url 配置错误
    if (
        "502" in msg
        or "503" in msg
        or "bad gateway" in low
        or "service unavailable" in low
        or "connection refused" in low
        or "actively refused" in low
        or "target machine" in low
        or "os error 10061" in low
        or "cannot connect" in low
        or "upstream connect failed" in low
    ):
        base_url = getattr(app_config.llm, "base_url", None) or "配置的服务地址"
        # 如果系统设置了代理（HTTP_PROXY/HTTPS_PROXY）且代理本身不可达，也会表现为连不上 localhost:8081 这类地址
        proxies = [f"{k}={os.environ[k]}" for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY") if k in os.environ]
        proxy_hint = f"当前检测到的代理环境变量：{', '.join(proxies)}" if proxies else "当前未检测到系统代理环境变量"
        return (
            f"LLM 推理服务连接失败（502/连接被拒绝）：无法连接到模型服务（base_url={base_url}）。\n"
            "可能原因：1) 本地模型服务（如 vLLM / TGI）未启动；2) llm.base_url 配置错误；3) 系统代理（HTTP_PROXY/HTTPS_PROXY）指向了未运行的代理（常见为 localhost:8081）。\n"
            f"排查建议：检查 conf/app_config.yaml 的 llm.base_url；检查并清理环境变量 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY。{proxy_hint}"
        )
    return f"LLM 调用异常：{msg}"


class MockChatModel(BaseChatModel):
    """
    离线占位模型：不发起任何网络请求，仅根据提示词中的任务关键词返回「格式正确」的响应，
    使整条问数链路（含需要扩展关键词 / 过滤 / 生成 SQL 的节点）在无真实 LLM 时也能跑通。

    返回格式严格匹配各节点的解析器要求：
      - 扩展关键词类（JsonOutputParser 期望 list）         -> JSON 数组
      - 过滤指标类（节点对「非 list」走保留全部防御）        -> "{}"（合法 JSON 对象）
      - 过滤表类（节点对「非 dict」走保留全部防御）          -> 合法 JSON 字符串
      - 生成 / 校正 SQL 类（StrOutputParser 期望字符串）     -> SQL 文本
    """

    @property
    def _llm_type(self) -> str:
        return "mock"

    # 仅用于离线测试，不接入真实模型，故不需要真正调用模型
    @property
    def _identifying_params(self) -> dict:
        return {"llm_type": "mock"}

    def _decide(self, messages) -> str:
        # 取最后一条人类消息的文本内容作为任务判定依据（提示词模板含稳定的输出格式标识）
        text = ""
        for m in reversed(messages):
            content = getattr(m, "content", "")
            if isinstance(content, str) and content.strip():
                text = content
                break

        # 1) 过滤表：模板要求「仅输出 JSON 对象」-> 返回非 dict 的合法 JSON 字符串，
        #    触发节点「保留全部表与字段」的防御分支（保证后续 generate_sql 仍有上下文）
        if "仅输出 JSON 对象" in text:
            return '"__keep_all__"'

        # 2) 过滤指标 / 扩展关键词：模板均要求「仅输出 JSON 数组」
        if "仅输出 JSON 数组" in text:
            # 过滤指标：返回非 list（合法 JSON 对象），触发节点「保留全部指标」防御分支
            if "指标" in text and "过滤" in text:
                return "{}"
            # 扩展关键词：返回 JSON 数组，节点会将其并入关键词集合参与召回
            return '["销售", "总额", "地区", "时间", "订单"]'

        # 3) 生成 / 校正 SQL：模板要求「输出一条完整 SQL 语句」-> 返回 SQL 文本
        if "SQL 语句" in text or "SQL查询语句" in text:
            return "SELECT region, SUM(order_amount) AS total_amount FROM fact_order GROUP BY region"

        # 4) 兜底：视为扩展关键词，返回 JSON 数组
        return '["销售", "总额", "地区", "时间", "订单"]'

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        content = self._decide(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        # 离线 mock 无需异步 IO，直接复用同步逻辑
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def get_llm():
    """
    构造 LLM 客户端（工厂函数）。
    - provider=mock：返回离线占位模型，无需任何 Key 与外部依赖。
    - provider=openai（默认）：构造 OpenAI 兼容客户端；为兼容性考虑，构造阶段即使缺 Key 也
      仅用占位值，真实鉴权错误会在实际调用时由上游返回（401/403），再由 describe_llm_error 转中文。
    """
    cfg = app_config.llm
    provider = (cfg.provider or "openai").lower()

    if provider == "mock":
        return MockChatModel()

    if provider == "openai":
        # 缺 Key 时用占位值，避免 import 阶段崩溃；真实鉴权报错在调用时由上游返回
        api_key = cfg.api_key or "missing-api-key"
        try:
            model = init_chat_model(
                model=cfg.model_name,
                model_provider="openai",
                api_key=api_key,
                base_url=cfg.base_url,
                temperature=0,  # 严谨：问数场景不需要创造性
            )
            # 对网络抖动 / 限流等瞬时错误做指数退避重试（至多 3 次），提升链路韧性
            return model.with_retry(
                stop_after_attempt=3,
                wait_exponential_jitter=True,
            )
        except LLMError:
            raise
        except Exception as e:  # 构造阶段的其它异常（如 base_url 非法）统一转成中文可读错误
            raise LLMError(f"LLM 客户端初始化失败：{describe_llm_error(e)}") from e

    raise LLMError(f"不支持的 LLM provider：{cfg.provider}（仅支持 openai / mock）")


# 模块级单例，保持与历史代码 `from app.agent.llm import llm` 的向后兼容
llm = get_llm()


if __name__ == '__main__':
    # 仅直接运行本文件时做一次连通性自测（需要真实可用的 LLM Key）
    import asyncio

    async def _self_test():
        resp = await llm.ainvoke("你是谁？")
        print("LLM 自测响应：", resp.content)

    asyncio.run(_self_test())
