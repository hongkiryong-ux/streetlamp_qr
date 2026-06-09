# database.py
import os
import re
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

_RAW_DATABASE_URL = (
    os.environ.get("DATABASE_INTERNAL_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
    or "sqlite+aiosqlite:///./streetlamp.db"
)


def _replace_hostname(url: str, new_host: str) -> str:
    parsed = urlparse(url)
    user = quote(parsed.username or "", safe="")
    password = quote(parsed.password or "", safe="")
    auth = f"{user}:{password}@" if user else ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{auth}{new_host}{port}"
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _normalize_render_postgres_host(host: str) -> str:
    """External 호스트(dpg-xxx-a.region-postgres.render.com) → Internal(dpg-xxx-a)."""
    host = host or ""
    if host.startswith("dpg-") and ".render.com" in host:
        internal = host.split(".")[0]
        print(
            f"[db] Render Postgres external→internal: {host} → {internal}",
            flush=True,
        )
        return internal
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        print(
            f"[db] ERROR: DATABASE_URL host is public IP ({host}). "
            "Render → Postgres → Connect → Internal Connection String 으로 교체하세요.",
            flush=True,
        )
    return host


def _prepare_database_url(raw: str) -> str:
    url = raw
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)

    if not url.startswith("postgresql+psycopg://"):
        return url

    parsed = urlparse(url)
    host = _normalize_render_postgres_host(parsed.hostname or "")
    if host != (parsed.hostname or ""):
        url = _replace_hostname(url, host)
        parsed = urlparse(url)

    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("sslmode", None)

    if (parsed.hostname or "").startswith("dpg-"):
        qs["sslmode"] = ["prefer"]
    else:
        qs["sslmode"] = ["require"]

    clean_qs = urlencode({k: v[0] for k, v in qs.items() if v and v[0]})
    return urlunparse(parsed._replace(query=clean_qs))


DATABASE_URL = _prepare_database_url(_RAW_DATABASE_URL)

if DATABASE_URL.startswith("postgresql+psycopg://"):
    print(f"[db] postgres host={urlparse(DATABASE_URL).hostname}", flush=True)

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
