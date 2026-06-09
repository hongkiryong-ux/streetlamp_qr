# database.py
import os
from urllib.parse import urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# 기본은 로컬(SQLite). 서버에서는 Render가 DATABASE_URL을 환경변수로 줍니다.
# 주의: 호스팅에서 SQLite 파일을 쓰면 인스턴스가 둘 이상일 때 DB가 서로 달래
# 목록과 업데이트가 다른 DB를 볼 수 있습니다. 운영은 PostgreSQL 권장.
_RAW_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./streetlamp.db")


def _postgres_asyncpg_dsn(raw_url: str) -> str:
    """Render Postgres DSN — asyncpg가 sslmode를 직접 처리하도록 postgresql:// 형식."""
    url = raw_url
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    parsed = urlparse(url)
    if "sslmode=" not in (parsed.query or ""):
        query = parsed.query
        query = f"{query}&sslmode=require" if query else "sslmode=require"
        url = urlunparse(parsed._replace(query=query))
    return url


def _create_engine():
    raw = _RAW_DATABASE_URL
    lower = raw.lower()

    if lower.startswith("sqlite"):
        return create_async_engine(raw, echo=False)

    if "postgres" in lower:
        dsn = _postgres_asyncpg_dsn(raw)

        async def _asyncpg_connect():
            import asyncpg

            return await asyncpg.connect(dsn)

        # SQLAlchemy→asyncpg 경유 시 ssl/connect_args 가 무시되는 경우가 있어
        # asyncpg DSN(sslmode=require)으로 직접 연결합니다.
        return create_async_engine(
            "postgresql+asyncpg://",
            echo=False,
            async_creator=_asyncpg_connect,
            pool_pre_ping=True,
        )

    return create_async_engine(raw, echo=False)


DATABASE_URL = _RAW_DATABASE_URL
engine = _create_engine()

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

    url = (_RAW_DATABASE_URL or "").lower()
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
