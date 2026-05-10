# main.py
from __future__ import annotations

import asyncio
import hashlib
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import select, delete, or_, func, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import engine, Base, get_db, AsyncSessionLocal, ensure_schema_updates
from models import Lamp, MaintenanceRequest, RequestType, RequestStatus

from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import StreamingResponse

import os
from io import BytesIO
from datetime import datetime, timezone, date, time
from zoneinfo import ZoneInfo
from urllib.parse import urlencode, urlparse

import openpyxl

from settings_service import ensure_default_settings, get_all_settings_map, set_setting
from jobs import reschedule_daily_report_job, public_base_url_for_ping
from reporting import run_daily_report_pipeline


async def keep_alive_worker() -> None:
    """PUBLIC_BASE_URL 또는 RENDER_EXTERNAL_URL 의 /health 로 최소 요청(설정 분 단위)."""
    import httpx

    from settings_service import get_setting

    while True:
        async with AsyncSessionLocal() as session:
            try:
                mins = int((await get_setting(session, "keep_alive_minutes") or "0").strip() or "0")
            except ValueError:
                mins = 0
        if mins <= 0:
            await asyncio.sleep(600)
            continue
        await asyncio.sleep(max(60, mins * 60))
        base = public_base_url_for_ping()
        if not base:
            await asyncio.sleep(120)
            continue
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                await client.get(f"{base}/health")
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema_updates()
    async with AsyncSessionLocal() as session:
        await ensure_default_settings(session)
        await session.commit()

    scheduler = AsyncIOScheduler(timezone=ZoneInfo("Asia/Seoul"))
    app.state.scheduler = scheduler
    await reschedule_daily_report_job(scheduler)
    scheduler.start()

    keep_task = asyncio.create_task(keep_alive_worker())
    app.state.keep_alive_task = keep_task
    yield
    keep_task.cancel()
    try:
        await keep_task
    except asyncio.CancelledError:
        pass
    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)


def _fmt_kst(dt: datetime | None) -> str:
    """DB에 저장된 naive datetime은 UTC로 간주하고 한국시간(날짜·시간·초)으로 표시."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_kst_date(dt: datetime | None) -> str:
    """관리자 목록 등: 연·월·일만 (KST)."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")

# 세션용 (관리자 로그인, 간단하게)
SECRET_KEY = os.environ.get("APP_SECRET_KEY", "change_this_secret_in_prod")
_session_kw: dict = {"secret_key": SECRET_KEY, "same_site": "lax"}
# Render 등 HTTPS 뒤에서는 Secure 쿠키(https_only)를 켜야 세션이 유지되고 로그인↔목록 리다이렉트 루프를 막을 수 있음
if os.environ.get("RENDER", "").lower() in ("true", "1", "yes") or os.environ.get(
    "COOKIE_HTTPS_ONLY", ""
).lower() in ("1", "true", "yes"):
    _session_kw["https_only"] = True
app.add_middleware(SessionMiddleware, **_session_kw)

try:
    from starlette.middleware.proxy_headers import ProxyHeadersMiddleware

    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
except ImportError:
    pass

# static, templates 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.filters["fmt_kst"] = _fmt_kst
templates.env.filters["fmt_kst_date"] = _fmt_kst_date


def _parse_date_yyyy_mm_dd(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _admin_requests_select(
    status_filter: str,
    q: str,
    *,
    date_from: str = "",
    date_to: str = "",
    lamp_id: str = "",
    name: str = "",
    phone: str = "",
    content: str = "",
    request_type_filter: str = "",
):
    """관리자 목록/엑셀에서 동일하게 사용하는 쿼리."""
    stmt = select(MaintenanceRequest).order_by(MaintenanceRequest.created_at.desc())
    q_strip = (q or "").strip()
    name_s = (name or "").strip()
    phone_s = (phone or "").strip()
    content_s = (content or "").strip()
    lamp_s = (lamp_id or "").strip()

    # 처리 상태: 값이 있으면 해당 상태만, 비어 있으면 전체(접수·처리중·완료 모두 표시)
    if status_filter:
        try:
            stmt = stmt.where(
                MaintenanceRequest.status == RequestStatus(status_filter)
            )
        except ValueError:
            pass

    # 접수 기간 (입력일은 KST 달력 기준, DB는 naive UTC로 저장된 값과 비교)
    kst = ZoneInfo("Asia/Seoul")
    d_from = _parse_date_yyyy_mm_dd(date_from)
    if d_from is not None:
        utc_start = datetime.combine(d_from, time.min, tzinfo=kst).astimezone(
            timezone.utc
        ).replace(tzinfo=None)
        stmt = stmt.where(MaintenanceRequest.created_at >= utc_start)

    d_to = _parse_date_yyyy_mm_dd(date_to)
    if d_to is not None:
        utc_end = datetime.combine(d_to, time.max.replace(microsecond=999999), tzinfo=kst).astimezone(
            timezone.utc
        ).replace(tzinfo=None)
        stmt = stmt.where(MaintenanceRequest.created_at <= utc_end)

    # 가로등 번호 (정확히 일치)
    if lamp_s.isdigit():
        stmt = stmt.where(MaintenanceRequest.lamp_id == int(lamp_s))

    # 정비 유형
    if (request_type_filter or "").strip():
        try:
            stmt = stmt.where(
                MaintenanceRequest.request_type == RequestType(request_type_filter)
            )
        except ValueError:
            pass

    # 이름 / 전화 / 내용 (부분 일치, AND)
    if name_s:
        stmt = stmt.where(
            func.lower(MaintenanceRequest.name).like(f"%{name_s.lower()}%")
        )
    if phone_s:
        stmt = stmt.where(
            func.lower(MaintenanceRequest.phone).like(f"%{phone_s.lower()}%")
        )
    if content_s:
        stmt = stmt.where(
            func.lower(func.coalesce(MaintenanceRequest.content, "")).like(
                f"%{content_s.lower()}%"
            )
        )

    # 통합 검색(q): 이름·전화·내용·가로등ID 문자열에 OR
    if q_strip:
        pattern = f"%{q_strip.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(MaintenanceRequest.name).like(pattern),
                func.lower(MaintenanceRequest.phone).like(pattern),
                func.lower(func.coalesce(MaintenanceRequest.content, "")).like(pattern),
                cast(MaintenanceRequest.lamp_id, String).like(f"%{q_strip}%"),
            )
        )

    return stmt


def _admin_export_query_string(
    *,
    q: str,
    status_filter: str,
    date_from: str,
    date_to: str,
    lamp_id: str,
    name: str,
    phone: str,
    content: str,
    request_type_filter: str,
) -> str:
    params: dict[str, str] = {}
    if (q or "").strip():
        params["q"] = q.strip()
    if (status_filter or "").strip():
        params["filter_status"] = status_filter.strip()
    if (date_from or "").strip():
        params["date_from"] = date_from.strip()
    if (date_to or "").strip():
        params["date_to"] = date_to.strip()
    if (lamp_id or "").strip():
        params["lamp_id"] = lamp_id.strip()
    if (name or "").strip():
        params["name"] = name.strip()
    if (phone or "").strip():
        params["phone"] = phone.strip()
    if (content or "").strip():
        params["content"] = content.strip()
    if (request_type_filter or "").strip():
        params["request_type"] = request_type_filter.strip()
    return urlencode(params)


@app.get("/health")
async def health():
    """Render/LB 헬스체크 및 깨우기(self-ping)용."""
    return {"status": "ok"}


# 홈: 간단 안내
@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse(
        request,
        "base.html",
        {"content": "QR을 찍어 가로등 별 페이지에 접속하세요."},
    )


# 특정 가로등 페이지
@app.get("/lamp/{lamp_id}")
async def lamp_detail(
    request: Request,
    lamp_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Lamp).where(Lamp.id == lamp_id))
    lamp = result.scalar_one_or_none()
    if not lamp:
        raise HTTPException(status_code=404, detail="해당 가로등을 찾을 수 없습니다.")

    return templates.TemplateResponse(
        request,
        "lamp_detail.html",
        {
            "lamp": lamp,
            "request_types": RequestType,
        },
    )


# 정비 의뢰 접수 처리
@app.post("/lamp/{lamp_id}/request")
async def create_request(
    request: Request,
    lamp_id: int,
    name: str = Form(...),
    phone: str = Form(...),
    request_type: RequestType = Form(...),
    content: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    # 가로등 존재 확인
    result = await db.execute(select(Lamp).where(Lamp.id == lamp_id))
    lamp = result.scalar_one_or_none()
    if not lamp:
        raise HTTPException(status_code=404, detail="해당 가로등을 찾을 수 없습니다.")

    # 템플릿에는 ORM 객체를 넘기지 않음: 응답 렌더 시점에 DB 세션이 닫히면
    # Jinja가 lamp 필드 접근 시 lazy-load → MissingGreenlet(500) 발생할 수 있음
    lamp_id_val = lamp.id
    lamp_location_val = lamp.location

    new_req = MaintenanceRequest(
        lamp_id=lamp_id,
        name=name,
        phone=phone,
        request_type=request_type,
        content=content,
    )
    db.add(new_req)
    await db.commit()

    return templates.TemplateResponse(
        request,
        "request_submitted.html",
        {"lamp_id": lamp_id_val, "lamp_location": lamp_location_val},
    )


# ---------- 관리자 영역 (매우 단순 버전) ----------

# 아주 간단한 하드코딩 계정 (실제 서비스 때는 DB로 관리 권장)
ADMIN_ID = os.environ.get("ADMIN_ID", "admin")
ADMIN_PW = os.environ.get("ADMIN_PW", "password123")


def _load_guest_accounts() -> dict[str, str]:
    """게스트 로그인 최대 10개: GUEST_1_ID / GUEST_1_PW … GUEST_10_ID / GUEST_10_PW"""
    out: dict[str, str] = {}
    for i in range(1, 11):
        gid = os.environ.get(f"GUEST_{i}_ID", "").strip()
        gpw = os.environ.get(f"GUEST_{i}_PW", "").strip()
        if gid and gpw:
            out[gid] = gpw
    return out


GUEST_ACCOUNTS = _load_guest_accounts()


def _plain_pw_matches(given: str, stored: str) -> bool:
    """secrets.compare_digest는 길이가 다르면 예외가 날 수 있어 길이 확인 후 비교."""
    ga = given.encode("utf-8")
    sb = stored.encode("utf-8")
    if len(ga) != len(sb):
        return False
    return secrets.compare_digest(ga, sb)


def is_admin_logged_in(request: Request) -> bool:
    return request.session.get("admin_logged_in", False)


def is_guest_logged_in(request: Request) -> bool:
    return bool(request.session.get("guest_logged_in"))


def is_staff_logged_in(request: Request) -> bool:
    """관리자 또는 게스트(목록·검색·수정 허용)."""
    return is_admin_logged_in(request) or is_guest_logged_in(request)


def admin_app_path(request: Request, path: str) -> str:
    """폼 action·링크용 상대 경로(root_path 반영). 전체 URL 대신 쓰면 같은 오리진·세션 쿠키 유지에 유리."""
    rp = (request.scope.get("root_path") or "").rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return f"{rp}{path}"


def admin_paths(request: Request) -> dict[str, str]:
    """관리자 템플릿 공통 링크·폼 action (하드코딩 /admin/... 금지)."""
    return {
        "path_login": admin_app_path(request, "/admin/login"),
        "path_logout": admin_app_path(request, "/admin/logout"),
        "path_requests_list": admin_app_path(request, "/admin/requests"),
        "path_requests_export": admin_app_path(request, "/admin/requests/export"),
        "path_requests_update": admin_app_path(request, "/admin/requests/update"),
        "path_requests_save_update": admin_app_path(request, "/admin/requests/save-update"),
        "path_requests_remove": admin_app_path(request, "/admin/requests/remove-row"),
        "path_settings": admin_app_path(request, "/admin/settings"),
        "path_settings_test_email": admin_app_path(request, "/admin/settings/test-email"),
    }


def _with_saved_flash(url: str) -> str:
    """저장 직후 목록으로 돌아갈 때 한 번만 표시할 flash=saved 쿼리."""
    if not url or "flash=saved" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}flash=saved"


def _safe_admin_requests_referer(request: Request, referer: str) -> str | None:
    """Referer 기반 리다이렉트: 같은 호스트·목록 경로만 허용 (오픈 리다이렉트·과다 리다이렉트 방지)."""
    referer = (referer or "").strip()
    if not referer:
        return None
    try:
        pr = urlparse(referer)
        req_host = (request.url.hostname or "").lower()
        ref_host = (pr.hostname or "").lower()
        if req_host and ref_host and ref_host != req_host:
            return None
        list_path = admin_app_path(request, "/admin/requests").rstrip("/") or "/"
        path = (pr.path or "").rstrip("/") or "/"
        if path != list_path:
            return None
        return referer
    except Exception:
        return None


@app.get("/admin/login")
async def admin_login_form(request: Request):
    if is_staff_logged_in(request):
        return RedirectResponse(
            url=admin_app_path(request, "/admin/requests"), status_code=302
        )
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {**admin_paths(request)},
    )


@app.post("/admin/login")
async def admin_login(
    request: Request,
    admin_id: str = Form(...),
    admin_pw: str = Form(...),
):
    uid = (admin_id or "").strip()
    pw = admin_pw or ""
    if uid == ADMIN_ID and pw == ADMIN_PW:
        request.session["admin_logged_in"] = True
        request.session.pop("guest_logged_in", None)
        return RedirectResponse(
            url=admin_app_path(request, "/admin/requests"), status_code=302
        )
    expected = GUEST_ACCOUNTS.get(uid)
    if expected is not None and _plain_pw_matches(pw, expected):
        request.session["guest_logged_in"] = True
        request.session.pop("admin_logged_in", None)
        return RedirectResponse(
            url=admin_app_path(request, "/admin/requests"), status_code=302
        )
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {**admin_paths(request), "error": "아이디 또는 비밀번호가 잘못되었습니다."},
    )


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(
        url=admin_app_path(request, "/admin/login"), status_code=302
    )


@app.get("/cron/daily-report")
async def cron_daily_report(secret: str | None = None):
    """Render 수면 시 내부 스케줄러가 안 돌 수 있어, 외부 Cron(Uptime 등)이 하루 1회 호출하는 용도."""
    expected = (os.environ.get("CRON_SECRET") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="환경변수 CRON_SECRET 이 설정되지 않았습니다.",
        )
    if not secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    digest_s = hashlib.sha256(secret.encode("utf-8")).digest()
    digest_e = hashlib.sha256(expected.encode("utf-8")).digest()
    if not secrets.compare_digest(digest_s, digest_e):
        raise HTTPException(status_code=403, detail="Forbidden")
    async with AsyncSessionLocal() as session:
        from settings_service import get_setting

        to_email = await get_setting(session, "report_email")
        msg = await run_daily_report_pipeline(session, to_email)
    return {"ok": True, "detail": msg}


@app.get("/admin/settings")
async def admin_settings_get(request: Request):
    if not is_admin_logged_in(request):
        if is_guest_logged_in(request):
            base = admin_app_path(request, "/admin/requests")
            return RedirectResponse(url=f"{base}?flash=guest_restricted", status_code=303)
        return RedirectResponse(
            url=admin_app_path(request, "/admin/login"), status_code=302
        )
    async with AsyncSessionLocal() as session:
        settings_map = await get_all_settings_map(session)
    base = public_base_url_for_ping()
    cron_secret_set = bool((os.environ.get("CRON_SECRET") or "").strip())
    saved = request.query_params.get("saved") == "1"
    notice = request.session.pop("admin_notice", None)
    return templates.TemplateResponse(
        request,
        "admin_settings.html",
        {
            **admin_paths(request),
            "settings": settings_map,
            "public_base_url": base,
            "cron_secret_set": cron_secret_set,
            "saved": saved,
            "notice": notice,
        },
    )


@app.post("/admin/settings")
async def admin_settings_post(request: Request):
    if not is_admin_logged_in(request):
        if is_guest_logged_in(request):
            base = admin_app_path(request, "/admin/requests")
            return RedirectResponse(url=f"{base}?flash=guest_restricted", status_code=303)
        return RedirectResponse(
            url=admin_app_path(request, "/admin/login"), status_code=302
        )

    form = await request.form()
    report_email = (form.get("report_email") or "").strip()
    try:
        report_hour_kst = int(form.get("report_hour_kst") or 16)
        report_minute_kst = int(form.get("report_minute_kst") or 0)
        keep_alive_minutes = int(form.get("keep_alive_minutes") or 0)
    except ValueError:
        raise HTTPException(status_code=400, detail="숫자 형식이 올바르지 않습니다.")

    use_internal = form.get("use_internal_daily_scheduler") in ("1", "on", "true", "yes")

    async with AsyncSessionLocal() as session:
        await set_setting(session, "report_email", report_email)
        await set_setting(session, "report_hour_kst", str(max(0, min(23, report_hour_kst))))
        await set_setting(session, "report_minute_kst", str(max(0, min(59, report_minute_kst))))
        await set_setting(session, "keep_alive_minutes", str(max(0, min(1440, keep_alive_minutes))))
        await set_setting(session, "use_internal_daily_scheduler", "1" if use_internal else "0")
        await session.commit()

    scheduler = request.app.state.scheduler
    await reschedule_daily_report_job(scheduler)

    base = admin_app_path(request, "/admin/settings")
    return RedirectResponse(url=f"{base}?saved=1", status_code=302)


@app.get("/admin/settings/test-email")
async def admin_settings_test_email_get(request: Request):
    """GET으로 열면 JSON 405 대신 설정 화면으로."""
    return RedirectResponse(
        url=admin_app_path(request, "/admin/settings"), status_code=302
    )


@app.post("/admin/settings/test-email")
async def admin_settings_test_email(request: Request):
    if not is_admin_logged_in(request):
        if is_guest_logged_in(request):
            base = admin_app_path(request, "/admin/requests")
            return RedirectResponse(url=f"{base}?flash=guest_restricted", status_code=303)
        return RedirectResponse(
            url=admin_app_path(request, "/admin/login"), status_code=302
        )
    async with AsyncSessionLocal() as session:
        from settings_service import get_setting

        to_email = await get_setting(session, "report_email")
        msg = await run_daily_report_pipeline(session, to_email)
    request.session["admin_notice"] = msg
    return RedirectResponse(
        url=admin_app_path(request, "/admin/settings"), status_code=302
    )


@app.get("/admin/requests", name="admin_requests_list")
async def admin_requests(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not is_staff_logged_in(request):
        return RedirectResponse(
            url=admin_app_path(request, "/admin/login"), status_code=302
        )

    q = (request.query_params.get("q") or "").strip()
    status_filter = (
        request.query_params.get("filter_status")
        or request.query_params.get("status")
        or ""
    ).strip()
    date_from = (request.query_params.get("date_from") or "").strip()
    date_to = (request.query_params.get("date_to") or "").strip()
    lamp_id = (request.query_params.get("lamp_id") or "").strip()
    name = (request.query_params.get("name") or "").strip()
    phone = (request.query_params.get("phone") or "").strip()
    content = (request.query_params.get("content") or "").strip()
    request_type_filter = (request.query_params.get("request_type") or "").strip()

    stmt = _admin_requests_select(
        status_filter,
        q,
        date_from=date_from,
        date_to=date_to,
        lamp_id=lamp_id,
        name=name,
        phone=phone,
        content=content,
        request_type_filter=request_type_filter,
    )

    result = await db.execute(stmt)
    requests_list = result.scalars().all()

    # 관리자 화면에서 Enum을 한글로 보여주기 위한 매핑
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

    export_qs = _admin_export_query_string(
        q=q,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        lamp_id=lamp_id,
        name=name,
        phone=phone,
        content=content,
        request_type_filter=request_type_filter,
    )

    return templates.TemplateResponse(
        request,
        "admin_requests.html",
        {
            **admin_paths(request),
            "is_guest": is_guest_logged_in(request),
            "requests_list": requests_list,
            "RequestStatus": RequestStatus,
            "RequestType": RequestType,
            "RequestTypeLabel": RequestTypeLabel,
            "RequestStatusLabel": RequestStatusLabel,
            "q": q,
            "status_filter": status_filter,
            "date_from": date_from,
            "date_to": date_to,
            "lamp_id": lamp_id,
            "name": name,
            "phone": phone,
            "content": content,
            "request_type_filter": request_type_filter,
            "export_qs": export_qs,
        },
    )


@app.post("/admin/requests", name="admin_requests_row_save")
async def admin_requests_row_save(
    request: Request,
    mr_id: int = Form(...),
    mr_status: RequestStatus = Form(...),
    mr_work_memo: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """목록 GET과 같은 URL로 POST → 폼 action이 목록과 항상 일치해 405 방지."""
    return await _admin_apply_request_status(
        request, mr_id, mr_status, mr_work_memo, db
    )


@app.get("/admin/requests/export", name="admin_requests_export")
async def admin_requests_export(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not is_staff_logged_in(request):
        return RedirectResponse(
            url=admin_app_path(request, "/admin/login"), status_code=302
        )

    # 목록과 동일한 필터 로직
    q = (request.query_params.get("q") or "").strip()
    status_filter = (
        request.query_params.get("filter_status")
        or request.query_params.get("status")
        or ""
    ).strip()
    date_from = (request.query_params.get("date_from") or "").strip()
    date_to = (request.query_params.get("date_to") or "").strip()
    lamp_id = (request.query_params.get("lamp_id") or "").strip()
    name = (request.query_params.get("name") or "").strip()
    phone = (request.query_params.get("phone") or "").strip()
    content = (request.query_params.get("content") or "").strip()
    request_type_filter = (request.query_params.get("request_type") or "").strip()

    stmt = _admin_requests_select(
        status_filter,
        q,
        date_from=date_from,
        date_to=date_to,
        lamp_id=lamp_id,
        name=name,
        phone=phone,
        content=content,
        request_type_filter=request_type_filter,
    )

    result = await db.execute(stmt)
    rows = result.scalars().all()

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

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "정비의뢰"

    ws.append(
        [
            "접수ID",
            "가로등ID",
            "접수일시(KST)",
            "이름",
            "전화번호",
            "정비유형",
            "내용",
            "작업비고",
            "상태",
        ]
    )

    for r in rows:
        created = r.created_at
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            created_str = created.astimezone(ZoneInfo("Asia/Seoul")).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            created_str = ""

        ws.append(
            [
                r.id,
                r.lamp_id,
                created_str,
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

    filename = "maintenance_requests.xlsx"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


async def _admin_apply_request_status(
    request: Request,
    req_id: int,
    status: RequestStatus,
    work_memo: str,
    db: AsyncSession,
) -> RedirectResponse:
    if not is_staff_logged_in(request):
        return RedirectResponse(
            url=admin_app_path(request, "/admin/login"), status_code=302
        )

    result = await db.execute(
        select(MaintenanceRequest).where(MaintenanceRequest.id == req_id)
    )
    req_obj = result.scalar_one_or_none()
    if not req_obj:
        base = admin_app_path(request, "/admin/requests")
        return RedirectResponse(url=f"{base}?flash=nosuchrequest", status_code=302)

    memo = (work_memo or "").strip()
    req_obj.status = status
    # 비고는 상태와 무관하게 입력하면 저장 (접수/처리중만 두고 글만 적어도 유지)
    if memo:
        req_obj.work_memo = memo
    elif status == RequestStatus.done:
        # 완료인데 비고를 비운 경우만 DB 비고 삭제
        req_obj.work_memo = None
    # 비고 비움 + 접수/처리중 → 기존 work_memo 유지 (덮어쓰지 않음)

    await db.commit()

    ref = (request.headers.get("referer") or "").strip()
    safe_ref = _safe_admin_requests_referer(request, ref)
    if safe_ref:
        return RedirectResponse(url=_with_saved_flash(safe_ref), status_code=303)
    return RedirectResponse(
        url=_with_saved_flash(admin_app_path(request, "/admin/requests")),
        status_code=303,
    )


@app.get("/admin/requests/update")
async def admin_update_request_status_get(request: Request):
    """GET으로 열면 JSON 405 대신 목록으로."""
    return RedirectResponse(
        url=admin_app_path(request, "/admin/requests"), status_code=302
    )


@app.post("/admin/requests/update", name="admin_update_request_status")
async def admin_update_request_status(
    request: Request,
    mr_id: int = Form(...),
    mr_status: RequestStatus = Form(...),
    mr_work_memo: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """상태 변경. 필드명 mr_* 는 검색 폼의 status 등과 겹치지 않도록 고유 접두사."""
    return await _admin_apply_request_status(
        request, mr_id, mr_status, mr_work_memo, db
    )


@app.get("/admin/requests/save-update")
async def admin_requests_save_update_get(request: Request):
    return RedirectResponse(
        url=admin_app_path(request, "/admin/requests"), status_code=302
    )


@app.post("/admin/requests/save-update")
async def admin_requests_save_update(
    request: Request,
    mr_id: int = Form(...),
    mr_status: RequestStatus = Form(...),
    mr_work_memo: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """`/admin/requests/update` 와 동일(프록시·캐시 이슈 시 대체 URL)."""
    return await _admin_apply_request_status(
        request, mr_id, mr_status, mr_work_memo, db
    )


@app.get("/admin/requests/{req_id}/status")
async def update_request_status_get(request: Request, req_id: int):
    """실수·북마크·리다이렉트로 GET이 들어오면 JSON 405 대신 목록으로 보냄."""
    return RedirectResponse(
        url=admin_app_path(request, "/admin/requests"), status_code=302
    )


@app.post("/admin/requests/{req_id}/status", name="update_request_status")
async def update_request_status(
    request: Request,
    req_id: int,
    status: RequestStatus = Form(...),
    work_memo: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    return await _admin_apply_request_status(
        request, req_id, status, work_memo, db
    )


@app.post("/admin/requests/remove-row", name="admin_remove_request_row")
async def admin_remove_request_row(
    request: Request,
    mr_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """삭제도 동적 경로 대신 고정 POST + mr_id (세션·프록시 안정)."""
    if not is_admin_logged_in(request):
        if is_guest_logged_in(request):
            base = admin_app_path(request, "/admin/requests")
            return RedirectResponse(
                url=f"{base}?flash=guest_restricted", status_code=303
            )
        return RedirectResponse(
            url=admin_app_path(request, "/admin/login"), status_code=302
        )

    row = (
        await db.execute(
            select(MaintenanceRequest).where(MaintenanceRequest.id == mr_id)
        )
    ).scalar_one_or_none()
    if not row:
        base = admin_app_path(request, "/admin/requests")
        return RedirectResponse(url=f"{base}?flash=nosuchrequest", status_code=302)

    await db.execute(delete(MaintenanceRequest).where(MaintenanceRequest.id == mr_id))
    await db.commit()

    ref = (request.headers.get("referer") or "").strip()
    try:
        pr = urlparse(ref)
        if "/admin/requests" in pr.path:
            return RedirectResponse(url=_with_saved_flash(ref))
    except Exception:
        pass
    return RedirectResponse(
        url=_with_saved_flash(admin_app_path(request, "/admin/requests"))
    )


@app.post("/admin/requests/{req_id}/delete", name="admin_delete_request")
async def admin_delete_request(
    request: Request,
    req_id: int,
    db: AsyncSession = Depends(get_db),
):
    if not is_admin_logged_in(request):
        if is_guest_logged_in(request):
            base = admin_app_path(request, "/admin/requests")
            return RedirectResponse(
                url=f"{base}?flash=guest_restricted", status_code=303
            )
        return RedirectResponse(
            url=admin_app_path(request, "/admin/login"), status_code=302
        )

    await db.execute(delete(MaintenanceRequest).where(MaintenanceRequest.id == req_id))
    await db.commit()

    ref = (request.headers.get("referer") or "").strip()
    try:
        pr = urlparse(ref)
        if "/admin/requests" in pr.path:
            return RedirectResponse(url=_with_saved_flash(ref))
    except Exception:
        pass
    return RedirectResponse(
        url=_with_saved_flash(admin_app_path(request, "/admin/requests"))
    )
