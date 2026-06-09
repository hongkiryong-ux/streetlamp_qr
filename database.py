# database.py
import os
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# 기본은 로컬(SQLite). 서버에서는 Render가 DATABASE_URL을 환경변수로 줍니다.
# Render 웹 서비스 → Postgres 는 **Internal Database URL** 사용 (공인 IP X).
_RAW_DATABASE_URL = (
    os.environ.get("DATABASE_INTERNAL_URL", "").strip()
    or os.environ.get("DATABASE_URL", "").strip()
    or "sqlite+aiosqlite:///./streetlamp.db"
)


def _is_render_external_postgres_host(host: str) -> bool:
    host = (host or "").lower()
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        return True
    return ".postgres.render.com" in host or host.endswith(".render.com")


def _prepare_database_url(raw: str) -> str:
    url = raw
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)

    if not url.startswith("postgresql+psycopg://"):
        return url

    parsed = urlparse(url)
    host = parsed.hostname or ""
    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("sslmode", None)

    if _is_render_external_postgres_host(host):
        # 외부 URL(공인 IP / *.postgres.render.com) — SSL 협상 실패가 잦음
        qs["sslmode"] = ["require"]
        print(
            f"[db] WARNING: Postgres host={host!r} looks EXTERNAL. "
            "Render 대시보드에서 Postgres → Connect → Internal URL 로 DATABASE_URL 을 바꾸세요.",
            flush=True,
        )
    elif host.startswith("dpg-"):
        # Render internal: dpg-xxxxx-a
        qs["sslmode"] = ["prefer"]
    else:
        qs["sslmode"] = ["require"]

    clean_qs = urlencode({k: v[0] for k, v in qs.items() if v and v[0]})
    return urlunparse(parsed._replace(query=clean_qs))


DATABASE_URL = _prepare_database_url(_RAW_DATABASE_URL)

if DATABASE_URL.startswith("postgresql+psycopg://"):
    _host = urlparse(DATABASE_URL).hostname or "?"
    print(f"[db] postgres host={_host}", flush=True)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 10},
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
