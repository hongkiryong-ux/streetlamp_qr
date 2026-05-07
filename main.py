# main.py
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import engine, Base, get_db
from models import Lamp, MaintenanceRequest, RequestType, RequestStatus

from starlette.middleware.sessions import SessionMiddleware

import os

app = FastAPI()

# 세션용 (관리자 로그인, 간단하게)
SECRET_KEY = os.environ.get("APP_SECRET_KEY", "change_this_secret_in_prod")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# static, templates 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def on_startup():
    # DB 테이블 생성
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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


def is_admin_logged_in(request: Request) -> bool:
    return request.session.get("admin_logged_in", False)


@app.get("/admin/login")
async def admin_login_form(request: Request):
    if is_admin_logged_in(request):
        return RedirectResponse(url="/admin/requests", status_code=302)
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {},
    )


@app.post("/admin/login")
async def admin_login(
    request: Request,
    admin_id: str = Form(...),
    admin_pw: str = Form(...),
):
    if admin_id == ADMIN_ID and admin_pw == ADMIN_PW:
        request.session["admin_logged_in"] = True
        return RedirectResponse(url="/admin/requests", status_code=302)
    else:
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            {"error": "아이디 또는 비밀번호가 잘못되었습니다."},
        )


@app.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=302)


@app.get("/admin/requests")
async def admin_requests(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    if not is_admin_logged_in(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    result = await db.execute(
        select(MaintenanceRequest).order_by(MaintenanceRequest.created_at.desc())
    )
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

    return templates.TemplateResponse(
        request,
        "admin_requests.html",
        {
            "requests_list": requests_list,
            "RequestStatus": RequestStatus,
            "RequestTypeLabel": RequestTypeLabel,
            "RequestStatusLabel": RequestStatusLabel,
        },
    )


@app.post("/admin/requests/{req_id}/status")
async def update_request_status(
    request: Request,
    req_id: int,
    status: RequestStatus = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not is_admin_logged_in(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    result = await db.execute(
        select(MaintenanceRequest).where(MaintenanceRequest.id == req_id)
    )
    req_obj = result.scalar_one_or_none()
    if not req_obj:
        raise HTTPException(status_code=404, detail="요청을 찾을 수 없습니다.")

    req_obj.status = status
    await db.commit()

    return RedirectResponse(url="/admin/requests", status_code=302)
