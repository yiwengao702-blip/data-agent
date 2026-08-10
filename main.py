# main.py
# 项目入口文件：提供命令行方式构建元知识库

import asyncio
from pathlib import Path

from app.core.log import logger
from app.scripts.build_meta_knowledge import build


def main():
    """
    主入口函数：使用默认配置路径构建元知识库
    也可通过 app.scripts.build_meta_knowledge -c <config_path> 指定自定义配置
    """
    # 默认配置文件路径
    config_path = Path(__file__).parent / "conf" / "meta_config.yaml"
    logger.info(f"开始构建元知识库，配置文件: {config_path}")
    asyncio.run(build(config_path))


if __name__ == '__main__':
    main()
