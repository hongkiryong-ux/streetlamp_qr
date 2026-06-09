# settings_service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AppSetting

DEFAULT_SETTINGS: dict[str, str] = {
    "report_email": "hkr008@poscowide.com",
    "report_hour_kst": "16",
    "report_minute_kst": "0",
    "keep_alive_minutes": "0",
    # "1"이면 서버가 살아 있는 동안 APScheduler로 매일 메일 시도 (Render 수면 시에는 실행 안 됨)
    "use_internal_daily_scheduler": "1",
    # 신규 접수 SMS (Solapi)
    "alert_sms_enabled": "1",
    "alert_sms_phones": "01071704563",
}


async def ensure_default_settings(session: AsyncSession) -> None:
    for key, val in DEFAULT_SETTINGS.items():
        result = await session.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        if not row:
            session.add(AppSetting(key=key, value=val))


async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    result = await session.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row and row.value is not None:
        return row.value
    return DEFAULT_SETTINGS.get(key, default)


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    result = await session.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))


async def get_all_settings_map(session: AsyncSession) -> dict[str, str]:
    out = dict(DEFAULT_SETTINGS)
    result = await session.execute(select(AppSetting))
    for row in result.scalars().all():
        if row.value is not None:
            out[row.key] = row.value
    return out
