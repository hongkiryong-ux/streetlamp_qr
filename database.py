# database.py
import os
import ssl
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# 기본은 로컬(SQLite). 서버에서는 Render가 DATABASE_URL을 환경변수로 줍니다.
# 주의: 호스팅에서 SQLite 파일을 쓰면 인스턴스가 둘 이상일 때 DB가 서로 달라
# 목록과 업데이트가 다른 DB를 볼 수 있습니다. 운영은 PostgreSQL 권장.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./streetlamp.db")


def _prepare_database_url(url: str) -> tuple[str, dict]:
    """Render Postgres URL을 asyncpg + SQLAlchemy에 맞게 정리합니다."""
    connect_args: dict = {}

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)

    if not url.startswith("postgresql+asyncpg://"):
        return url, connect_args

    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = (query.pop("sslmode", [None])[0] or "").lower()
    # asyncpg는 sslmode 쿼리를 SQLAlchemy 경유 시 받지 못함 → 제거 후 ssl 컨텍스트로 대체
    for key in ("sslcert", "sslkey", "sslrootcert", "sslcrl"):
        query.pop(key, None)
    # Render Postgres는 SSL 필수. sslmode 미포함 URL도 기본으로 SSL 사용
    if sslmode != "disable":
        connect_args["ssl"] = ssl.create_default_context()

    clean_query = urlencode({k: v[0] for k, v in query.items() if v and v[0]})
    clean_url = urlunparse(parsed._replace(query=clean_query))
    return clean_url, connect_args


DATABASE_URL, _connect_args = _prepare_database_url(DATABASE_URL)

engine = create_async_engine(DATABASE_URL, echo=False, connect_args=_connect_args)

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
