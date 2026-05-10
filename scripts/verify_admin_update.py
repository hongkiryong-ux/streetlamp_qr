"""관리자 상태 변경(admin POST /admin/requests/update) 로컬 검증.

프로젝트 루트에서:
  python scripts/verify_admin_update.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    sys.path.insert(0, ROOT)

    fd, dbpath = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{dbpath}"
    os.environ.setdefault("ADMIN_ID", "admin")
    os.environ.setdefault("ADMIN_PW", "password123")

    mr_id = asyncio.run(_seed())

    from starlette.testclient import TestClient

    from main import app
    from models import RequestStatus

    client = TestClient(app)
    login = client.post(
        "/admin/login",
        data={"admin_id": "admin", "admin_pw": "password123"},
        follow_redirects=False,
    )
    assert login.status_code == 302, login.text

    up = client.post(
        "/admin/requests/update",
        data={
            "mr_id": str(mr_id),
            "mr_status": RequestStatus.done.value,
            "mr_work_memo": "작업완료 테스트",
        },
        follow_redirects=False,
    )
    assert up.status_code == 302, up.text
    loc = up.headers.get("location") or ""
    assert "flash=nosuchrequest" not in loc, loc

    asyncio.run(_assert_db(mr_id))

    try:
        os.unlink(dbpath)
    except OSError:
        pass

    print("OK: verify_admin_update passed (mr_id=%s)" % mr_id)
    return 0


async def _seed() -> int:
    from sqlalchemy import select

    from database import AsyncSessionLocal, Base, engine
    from models import Lamp, MaintenanceRequest, RequestStatus, RequestType

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        lamp = Lamp(location="테스트 위치", description=None)
        session.add(lamp)
        await session.flush()
        mr = MaintenanceRequest(
            lamp_id=lamp.id,
            name="홍길동",
            phone="010",
            request_type=RequestType.other,
            content="검증",
            status=RequestStatus.received,
        )
        session.add(mr)
        await session.commit()
        await session.refresh(mr)
        return mr.id


async def _assert_db(mr_id: int) -> None:
    from sqlalchemy import select

    from database import AsyncSessionLocal
    from models import MaintenanceRequest, RequestStatus

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(MaintenanceRequest).where(MaintenanceRequest.id == mr_id)
            )
        ).scalar_one()
        assert row.status == RequestStatus.done
        assert row.work_memo == "작업완료 테스트"


if __name__ == "__main__":
    raise SystemExit(main())
