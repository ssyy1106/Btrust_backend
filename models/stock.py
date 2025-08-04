from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from database import Base_stock
import datetime
from sqlalchemy.dialects.postgresql import UUID
import uuid

def utcnow():
    return datetime.datetime.now()

class StocktakeSession(Base_stock):
    __tablename__ = 'stocktake_session'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    device_id = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)  # 前端上传时间

    creator_id = Column(Integer, nullable=True)
    modifier_id = Column(Integer, nullable=True)
    create_time = Column(DateTime(timezone=True), default=utcnow)
    update_time = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    items = relationship("StocktakeItem", back_populates="session", cascade="all, delete-orphan")


class StocktakeItem(Base_stock):
    __tablename__ = 'stocktake_item'

    session_id = Column(UUID(as_uuid=True), ForeignKey('stocktake_session.id', ondelete="CASCADE"), primary_key=True)
    id = Column(Integer, primary_key=True)  # 来自前端
    
    location = Column(String, nullable=False)
    barcode = Column(String, nullable=False)
    qty = Column(Integer, nullable=False)
    time = Column(DateTime(timezone=True), nullable=False)  # 前端上传时间

    creator_id = Column(Integer, nullable=True)
    modifier_id = Column(Integer, nullable=True)
    create_time = Column(DateTime(timezone=True), default=utcnow)
    update_time = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    session = relationship("StocktakeSession", back_populates="items")


class OperateLog(Base_stock):
    __tablename__ = 'operate_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_name = Column(String, nullable=False)
    request_payload = Column(JSON, nullable=False)
    response_payload = Column(JSON, nullable=True)
    create_time = Column(DateTime(timezone=True), default=utcnow)
