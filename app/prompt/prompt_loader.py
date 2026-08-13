import functools
from pathlib import Path


@functools.lru_cache(maxsize=32)
def loader_prompt(name: str) -> str:
    # 根据指定的名称拼接提示词所在的路径
    prompt_path = Path(__file__).parents[2] / "prompts" / f"{name}.prompt"
    # 可以直接用 Path 读取即可（lru_cache 避免每次节点调用都读盘）
    return prompt_path.read_text(encoding="utf-8")
