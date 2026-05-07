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
class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"
    id = Column(Integer, primary_key=True, index=True)
    lamp_id = Column(Integer, ForeignKey("lamps.id"))
    name = Column(String(100), nullable=False)
    phone = Column(String(50), nullable=False)
    request_type = Column(Enum(RequestType), nullable=False)
    content = Column(Text, nullable=True)
    status = Column(Enum(RequestStatus), default=RequestStatus.received)
    created_at = Column(DateTime, default=datetime.utcnow)
    lamp = relationship("Lamp", back_populates="requests")
