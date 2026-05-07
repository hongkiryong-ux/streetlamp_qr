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
        # 예시로 1~5번 가로등 등록
        lamps_data = [
            (1, "OO동 1번 가로등", "OO아파트 앞 교차로"),
            (2, "OO동 2번 가로등", "OO초등학교 후문"),
            (3, "OO동 3번 가로등", "OO시장 입구"),
            (4, "OO동 4번 가로등", "공원 입구"),
            (5, "OO동 5번 가로등", "버스 정류장 앞"),
        ]

        for lamp_id, location, description in lamps_data:
            result = await session.execute(select(Lamp).where(Lamp.id == lamp_id))
            lamp = result.scalar_one_or_none()
            if not lamp:
                session.add(Lamp(id=lamp_id, location=location, description=description))

        await session.commit()

if __name__ == "__main__":
    asyncio.run(init())
