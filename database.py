# database.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# 기본은 로컬(SQLite). 서버에서는 Render가 DATABASE_URL을 환경변수로 줍니다.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./streetlamp.db")

# Render Postgres는 보통 'postgresql://' 형태로 주는데,
# SQLAlchemy async는 'postgresql+asyncpg://' 가 필요합니다.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
