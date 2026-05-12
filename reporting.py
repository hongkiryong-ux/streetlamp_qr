# reporting.py — 최근 48시간 접수 엑셀 + SMTP 메일
from __future__ import annotations

import asyncio
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.header import Header
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


def _smtp_log(line: str) -> None:
    """Render 로그에는 보통 print 가 확실히 잡힘(logging.INFO 는 레벨 때문에 안 보일 수 있음)."""
    print(line, flush=True)


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
    # Gmail 앱 비밀번호는 화면에 "abcd efgh ..." 로 보이므로 붙여넣 시 공백 제거
    password = "".join((os.environ.get("SMTP_PASSWORD", "") or "").split())
    mail_from = os.environ.get("SMTP_FROM", user).strip()
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")

    _smtp_log(
        f"[smtp] start host={host!r} port={port} tls={use_tls} "
        f"user_set={bool(user)} pass_len={len(password)} from={mail_from!r} to={to_addr!r}"
    )

    msg = MIMEMultipart()
    msg["Subject"] = str(Header(subject, "utf-8"))
    msg["From"] = mail_from
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))
    part = MIMEApplication(attachment, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    part.add_header("Content-Disposition", "attachment", filename=attach_name)
    msg.attach(part)

    try:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            refused = smtp.sendmail(mail_from, [to_addr], msg.as_string())
            if refused:
                raise RuntimeError(f"SMTP가 수신 거부: {refused}")
        _smtp_log(f"[smtp] sendmail ok from={mail_from!r} to={to_addr!r}")
    except Exception as e:
        _smtp_log(f"[smtp] FAILED {type(e).__name__}: {e}")
        raise


async def send_daily_report_email(session: AsyncSession, to_email: str) -> str:
    if not (to_email or "").strip():
        raise ValueError("받는 메일 주소가 비어 있습니다.")

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
    return (
        f"메일 발송 완료 — 수신 주소: {to_email} (설정의 「받는 메일 주소」로 발송됨), 건수 {len(rows)}건. "
        "수신함·스팸함·프로모션함을 확인하세요. 다른 주소로 받으려면 설정에서 받는 메일을 바꾼 뒤 저장하세요."
    )


async def run_daily_report_pipeline(session: AsyncSession, to_email: str) -> str:
    """SMTP 미설정·발송 실패·DB 오류 시에도 문자열로 안내 (관리자 화면 500 방지)."""
    addr = (to_email or "").strip()
    if not addr:
        _smtp_log("[smtp] pipeline skip: empty report_email")
        return "받는 메일 주소가 비어 있습니다. 설정에서 받는 메일 주소를 입력·저장한 뒤 다시 시도하세요."

    try:
        out = await send_daily_report_email(session, addr)
        _smtp_log("[smtp] pipeline ok (see settings notice for recipient)")
        return out
    except RuntimeError as e:
        try:
            rows = await fetch_requests_last_48h(session)
            _, fname = build_xlsx_bytes(rows)
        except Exception as inner:
            msg = (
                f"SMTP 미설정 또는 접수 조회 실패. SMTP: {e} | 조회 오류: {type(inner).__name__}: {inner}"
            )
            _smtp_log(f"[smtp] pipeline fail: {msg}")
            return msg
        msg = (
            f"SMTP 미설정으로 메일은 보내지 못했습니다: {e}. "
            f"(대상 건수 {len(rows)}, 파일명 예: {fname})"
        )
        _smtp_log(f"[smtp] pipeline fail: {msg}")
        return msg
    except ValueError as e:
        _smtp_log(f"[smtp] pipeline skip: {e}")
        return str(e)
    except Exception as e:
        msg = (
            f"메일 발송에 실패했습니다 ({type(e).__name__}): {e}\n\n"
            "점검: Render 환경변수 SMTP_HOST(예: smtp.gmail.com), SMTP_PORT(587), "
            "SMTP_USER, SMTP_PASSWORD(앱 비밀번호), SMTP_FROM, SMTP_USE_TLS=true · "
            "Gmail은 일반 비밀번호가 아닌 앱 비밀번호가 필요합니다. "
            "DB 스키마 오류면 서버 재배포 후에도 동일하면 Render Logs의 SQL 오류를 확인하세요."
        )
        _smtp_log(f"[smtp] pipeline fail: {type(e).__name__}: {e}")
        return msg
