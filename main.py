# main.py
# 项目入口文件：提供命令行方式构建元知识库

import asyncio
import argparse
from pathlib import Path

from app.core.log import logger
from app.scripts.build_meta_knowledge import build


def main():
    """
    主入口函数：使用默认配置路径构建元知识库
    也可通过 app.scripts.build_meta_knowledge -c <config_path> 指定自定义配置
    使用 --reset 选项可在构建前先清空 Qdrant / ES 中的目标存储，再重新导入
    """
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="元知识库构建入口")
    parser.add_argument("-c", "--conf", help="自定义配置文件路径", default=None)
    parser.add_argument("-r", "--reset", action="store_true",
                        help="先清空 Qdrant 两个集合与 ES 索引，再重新构建（清空重新导入）")
    args = parser.parse_args()

    # 默认配置文件路径
    config_path = Path(args.conf) if args.conf else Path(__file__).parent / "conf" / "meta_config.yaml"
    logger.info(f"开始构建元知识库，配置文件: {config_path}, reset={args.reset}")
    asyncio.run(build(config_path, reset=args.reset))


if __name__ == '__main__':
    main()
