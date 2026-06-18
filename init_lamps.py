# init_lamps.py
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import engine, AsyncSessionLocal
from models import Base, Lamp

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # 1~100번 가로등 등록(일단 테스트용 기본값)
        # 실제 위치/설명은 나중에 원하실 때 CSV/수동으로 바꿔도 됩니다.
        for lamp_id in range(1, 101):
            location = f"가로등 {lamp_id}번"
            description = None

            result = await session.execute(select(Lamp).where(Lamp.id == lamp_id))
            existing = result.scalar_one_or_none()
            if not existing:
                session.add(
                    Lamp(
                        id=lamp_id,
                        location=location,
                        description=description,
                    )
                )

        await session.commit()

    async with AsyncSessionLocal() as session:
        from import_lamps_from_csv import _sync_lamps_id_sequence

        await _sync_lamps_id_sequence(session)
        await session.commit()

if __name__ == "__main__":
    asyncio.run(init())
