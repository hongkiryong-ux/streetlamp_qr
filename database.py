# database.py
import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# 기본은 로컬(SQLite). 서버에서는 Render가 DATABASE_URL을 환경변수로 줍니다.
# 주의: 호스팅에서 SQLite 파일을 쓰면 인스턴스가 둘 이상일 때 DB가 서로 달라
# 목록과 업데이트가 다른 DB를 볼 수 있습니다. 운영은 PostgreSQL 권장.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./streetlamp.db")

# Render Postgres: sslmode=require 가 URL에 포함됨. psycopg3는 이를 네이티브 지원.
# asyncpg+SQLAlchemy 조합은 Render에서 SSL 설정이 누락되는 경우가 있어 psycopg 사용.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


async def ensure_schema_updates() -> None:
    """기존 DB에 새 컬럼 추가(마이그레이션 없이 운영할 때)."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    url = (os.environ.get("DATABASE_URL") or "").lower()
    async with engine.begin() as conn:
        if "postgresql" in url or "postgres" in url:
            await conn.execute(
                text(
                    "ALTER TABLE maintenance_requests ADD COLUMN IF NOT EXISTS work_memo TEXT"
                )
            )
            await conn.execute(
                text(
                    "ALTER TABLE maintenance_requests ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP"
                )
            )
        else:
            try:
                await conn.execute(
                    text("ALTER TABLE maintenance_requests ADD COLUMN work_memo TEXT")
                )
            except OperationalError:
                pass
            try:
                await conn.execute(
                    text(
                        "ALTER TABLE maintenance_requests ADD COLUMN completed_at DATETIME"
                    )
                )
            except OperationalError:
                pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
