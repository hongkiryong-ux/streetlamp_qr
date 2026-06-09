# database.py
import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

_RAW_DATABASE_URL = (
    os.environ.get("DATABASE_INTERNAL_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
    or "sqlite+aiosqlite:///./streetlamp.db"
)


def _postgres_conninfo(raw: str) -> str:
    """psycopg libpq 연결 문자열 (External URL + sslmode=require)."""
    url = raw
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    parsed = urlparse(url)
    host = parsed.hostname or ""
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("sslmode", None)

    if host.startswith("dpg-") and "." not in host:
        qs["sslmode"] = ["prefer"]
        print(f"[db] Internal host={host}", flush=True)
    else:
        qs["sslmode"] = ["require"]
        print(f"[db] External host={host} sslmode=require", flush=True)

    clean_qs = urlencode({k: v[0] for k, v in qs.items() if v and v[0]})
    return urlunparse(parsed._replace(query=clean_qs))


def _create_engine():
    raw = _RAW_DATABASE_URL
    lower = raw.lower()

    if lower.startswith("sqlite"):
        return create_async_engine(raw, echo=False)

    if "postgres" in lower:
        conninfo = _postgres_conninfo(raw)

        async def _connect():
            import psycopg

            # conninfo 의 sslmode=require 만 사용 (ssl= 키워드는 psycopg 에서 오류 남)
            return await psycopg.AsyncConnection.connect(
                conninfo,
                connect_timeout=15,
            )

        return create_async_engine(
            "postgresql+psycopg://",
            async_creator=_connect,
            pool_pre_ping=True,
            pool_recycle=3600,
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
