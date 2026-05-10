# models.py
from sqlalchemy import Column, Integer, String, Text, Enum, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from database import Base
class RequestStatus(str, enum.Enum):
    received = "received"      # 접수
    in_progress = "in_progress"  # 처리중
    done = "done"              # 완료
class RequestType(str, enum.Enum):
    outage = "outage"          # 불점등
    globe_broken = "globe_broken"  # 글로브 파손
    fall_risk = "fall_risk"    # 전도 위험
    low_brightness = "low_brightness"  # 조도 불량
    other = "other"            # 기타
class Lamp(Base):
    __tablename__ = "lamps"
    id = Column(Integer, primary_key=True, index=True)
    location = Column(String(255), nullable=False)   # 위치 이름
    description = Column(Text, nullable=True)        # 상세 설명 (선택)
    requests = relationship("MaintenanceRequest", back_populates="lamp")
class AppSetting(Base):
    """관리자 웹에서 수정 가능한 키-값 설정."""
    __tablename__ = "app_settings"
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)


class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"
    id = Column(Integer, primary_key=True, index=True)
    lamp_id = Column(Integer, ForeignKey("lamps.id"))
    name = Column(String(100), nullable=False)
    phone = Column(String(50), nullable=False)
    request_type = Column(Enum(RequestType), nullable=False)
    content = Column(Text, nullable=True)
    status = Column(Enum(RequestStatus), default=RequestStatus.received)
    # 완료 처리 시 관리자가 적는 작업/비고
    work_memo = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # 상태가 완료로 바뀐 시각(첫 완료 시 기록, 완료→비완료 시 NULL)
    completed_at = Column(DateTime, nullable=True)
    lamp = relationship("Lamp", back_populates="requests")
