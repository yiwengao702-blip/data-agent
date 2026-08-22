# app/db/auth_db.py
# 自包含的用户存储：使用 SQLAlchemy + 本地 SQLite（data/auth.db）。
#
# 设计取舍：鉴权用户与主业务 MySQL 解耦，采用独立 SQLite 文件，
# 保证在 MySQL 未启动（降级环境）时登录 / 注册仍可正常工作。

from pathlib import Path

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker
from sqlalchemy import create_engine

# 数据库文件落在项目根的 data/ 目录，自动创建
_BASE_DIR = Path(__file__).resolve().parents[2] / "data"
_BASE_DIR.mkdir(parents=True, exist_ok=True)
_DB_PATH = _BASE_DIR / "auth.db"

# check_same_thread=False：FastAPI 多线程下复用同一引擎（鉴权为低并发场景，足够）
engine = create_engine(f"sqlite:///{_DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    """平台账户表（与业务库隔离，仅承载登录/注册所需的最小字段）。"""

    __tablename__ = "auth_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


def init_auth_db() -> None:
    """惰性建表：首次调用时创建缺失的表，幂等可重复调用。"""
    Base.metadata.create_all(engine)
