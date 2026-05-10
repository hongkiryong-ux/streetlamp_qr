# reporting.py — 최근 48시간 접수 엑셀 + SMTP 메일
from __future__ import annotations

import asyncio
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from zoneinfo import ZoneInfo

import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import MaintenanceRequest, RequestType, RequestStatus

RequestTypeLabel = {
    RequestType.outage.value: "불점등",
    RequestType.globe_broken.value: "글로브 파손",
    RequestType.fall_risk.value: "전도 위험",
    RequestType.low_brightness.value: "조도 불량",
    RequestType.other.value: "기타",
}
RequestStatusLabel = {
    RequestStatus.received.value: "접수",
    RequestStatus.in_progress.value: "처리중",
    RequestStatus.done.value: "완료",
}


def _kst_dt_str(dt: datetime | None) -> str:
    if not isinstance(dt, datetime):
        return ""
    d = dt
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")


async def fetch_requests_last_48h(session: AsyncSession) -> list[MaintenanceRequest]:
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=48)
    cutoff_naive = cutoff.replace(tzinfo=None)
    result = await session.execute(
        select(MaintenanceRequest)
        .where(MaintenanceRequest.created_at >= cutoff_naive)
        .order_by(MaintenanceRequest.created_at.desc())
    )
    return list(result.scalars().all())


def build_xlsx_bytes(rows: list[MaintenanceRequest]) -> tuple[bytes, str]:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "48h"
    ws.append(
        [
            "접수번호",
            "가로등 No",
            "접수일시(KST)",
            "완료일시(KST)",
            "이름",
            "전화번호",
            "정비유형",
            "내용",
            "작업비고",
            "상태",
        ]
    )
    for r in rows:
        created_str = _kst_dt_str(r.created_at)
        completed_str = _kst_dt_str(r.completed_at) if r.completed_at else ""
        ws.append(
            [
                r.id,
                r.lamp_id,
                created_str,
                completed_str,
                r.name,
                r.phone,
                RequestTypeLabel.get(r.request_type.value, r.request_type.value),
                r.content or "",
                r.work_memo or "",
                RequestStatusLabel.get(r.status.value, r.status.value),
            ]
        )
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    ts = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M")
    filename = f"streetlamp_48h_{ts}.xlsx"
    return bio.read(), filename


def _send_email_sync(
    to_addr: str,
    subject: str,
    body: str,
    attachment: bytes,
    attach_name: str,
) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        raise RuntimeError("SMTP_HOST 환경변수가 없습니다. Render에 SMTP 설정을 추가하세요.")

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    mail_from = os.environ.get("SMTP_FROM", user).strip()
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))
    part = MIMEApplication(attachment, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    part.add_header("Content-Disposition", "attachment", filename=attach_name)
    msg.attach(part)

    with smtplib.SMTP(host, port, timeout=60) as smtp:
        if use_tls:
            smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.sendmail(mail_from, [to_addr], msg.as_string())


async def send_daily_report_email(session: AsyncSession, to_email: str) -> str:
    rows = await fetch_requests_last_48h(session)
    data, fname = build_xlsx_bytes(rows)
    now_kst = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")
    subject = f"[가로등 정비] 최근 48시간 접수 요약 ({now_kst} KST)"
    body = (
        f"최근 48시간 접수 건수: {len(rows)}건\n"
        f"발송 시각(KST): {now_kst}\n\n"
        "첨부 엑셀을 확인하세요.\n"
    )
    await asyncio.to_thread(
        _send_email_sync, to_email, subject, body, data, fname
    )
    return f"메일 발송 완료: {to_email}, 건수 {len(rows)}"


async def run_daily_report_pipeline(session: AsyncSession, to_email: str) -> str:
    """메일 설정이 없으면 엑셀만 생성 후 안내 메시지 반환."""
    try:
        return await send_daily_report_email(session, to_email)
    except RuntimeError as e:
        rows = await fetch_requests_last_48h(session)
        _, fname = build_xlsx_bytes(rows)
        return (
            f"SMTP 미설정으로 메일은 보내지 못했습니다: {e}. "
            f"(대상 건수 {len(rows)}, 파일명 예: {fname})"
        )
