# database.py
import os
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

_RAW_DATABASE_URL = (
    os.environ.get("DATABASE_INTERNAL_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
    or "sqlite+aiosqlite:///./streetlamp.db"
)


def _prepare_database_url(raw: str) -> str:
    url = raw
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)

    if not url.startswith("postgresql+psycopg://"):
        return url

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("sslmode", None)

    # Render Postgres (Internal: dpg-xxx-a / External: dpg-xxx-a.region-postgres.render.com)
    if host.startswith("dpg-"):
        qs["sslmode"] = ["require"]
    elif re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        print(
            f"[db] ERROR: DATABASE_URL host is IP ({host}). "
            "Postgres → Connect → Internal 또는 External Connection String 전체를 붙여넣으세요.",
            flush=True,
        )
        qs["sslmode"] = ["require"]
    else:
        qs["sslmode"] = ["require"]

    clean_qs = urlencode({k: v[0] for k, v in qs.items() if v and v[0]})
    final = urlunparse(parsed._replace(query=clean_qs))

    print(f"[db] postgres host={parsed.hostname}", flush=True)
    if host.startswith("dpg-") and "." not in host:
        print(
            "[db] Internal hostname (dpg-xxx-a). "
            "Name or service not known 이면: 웹 서비스 Settings → Link Postgres DB.",
            flush=True,
        )
    return final


DATABASE_URL = _prepare_database_url(_RAW_DATABASE_URL)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"connect_timeout": 15},
)

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
