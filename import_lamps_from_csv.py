# import_lamps_from_csv.py — data/lamp_codes.csv → DB lamps 테이블
import asyncio
import csv
from pathlib import Path

from sqlalchemy import select, text

from database import engine, AsyncSessionLocal, ensure_schema_updates
from models import Base, Lamp

CSV_PATH = Path(__file__).resolve().parent / "data" / "lamp_codes.csv"


async def import_lamps() -> int:
    if not CSV_PATH.is_file():
        raise FileNotFoundError(
            f"{CSV_PATH} 없음. 먼저 scripts/build_lamp_codes_csv.py 를 실행하세요."
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema_updates()

    rows: list[dict[str, str]] = []
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("code") or "").strip()
            if code:
                rows.append(row)

    added = 0
    async with AsyncSessionLocal() as session:
        for row in rows:
            code = row["code"].strip()
            prefix = (row.get("group_prefix") or code.rsplit("-", 1)[0]).strip()
            location = f"가로등 {code}"

            result = await session.execute(select(Lamp).where(Lamp.code == code))
            existing = result.scalar_one_or_none()
            if existing:
                if existing.location != location:
                    existing.location = location
                continue

            session.add(
                Lamp(
                    code=code,
                    location=location,
                    description=f"구역 {prefix}" if prefix else None,
                )
            )
            added += 1

        # 기존 숫자 id 1~100 → code 문자열 백필 (하위 호환)
        for num in range(1, 101):
            code_s = str(num)
            result = await session.execute(select(Lamp).where(Lamp.id == num))
            lamp = result.scalar_one_or_none()
            if lamp and not lamp.code:
                lamp.code = code_s

        await session.commit()

    return added


if __name__ == "__main__":
    n = asyncio.run(import_lamps())
    print(f"완료. 새로 등록된 가로등: {n}개 (CSV: {CSV_PATH})")
