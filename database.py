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


def _to_render_internal_host(host: str) -> tuple[str, str | None]:
    """
    External: dpg-xxx-a.singapore-postgres.render.com
    Internal: dpg-xxx-a  (같은 리전 Render 웹 서비스에서만 DNS 해석됨)
    """
    host = host or ""
    m = re.match(r"^(dpg-[a-z0-9-]+-a)\.[a-z0-9-]+-postgres\.render\.com$", host, re.I)
    if m:
        region = host.split(".")[1].replace("-postgres", "")  # singapore
        return m.group(1), region
    return host, None


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
    internal_host, db_region = _to_render_internal_host(host)

    if internal_host != host:
        print(
            f"[db] External→Internal: {host} → {internal_host} "
            f"(DB region={db_region}, 웹 서비스도 {db_region} 리전이어야 함)",
            flush=True,
        )
        url = _replace_hostname(url, internal_host)
        parsed = urlparse(url)
        host = internal_host

    qs = parse_qs(parsed.query, keep_blank_values=True)
    qs.pop("sslmode", None)

    if host.startswith("dpg-") and "." not in host:
        # Render private network (internal hostname)
        qs["sslmode"] = ["prefer"]
    elif re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        print("[db] ERROR: DATABASE_URL 에 IP가 들어있습니다. Connect 탭 URL 전체를 사용하세요.", flush=True)
        qs["sslmode"] = ["require"]
    else:
        qs["sslmode"] = ["require"]

    clean_qs = urlencode({k: v[0] for k, v in qs.items() if v and v[0]})
    final = urlunparse(parsed._replace(query=clean_qs))
    print(f"[db] connect host={parsed.hostname} sslmode={qs.get('sslmode', [''])[0]}", flush=True)
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
