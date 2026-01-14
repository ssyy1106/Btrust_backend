from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, BigInteger, Float, Numeric
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

    creator_id = Column(String, nullable=True)
    modifier_id = Column(String, nullable=True)
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

    creator_id = Column(String, nullable=True)
    modifier_id = Column(String, nullable=True)
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

class ProductInfo(Base_stock):
    __tablename__ = "product_info"

    barcode = Column(String, primary_key=True)
    name_ch = Column(String, nullable=True)
    name_en = Column(String, nullable=True)
    price = Column(Float, nullable=True)

class ProductSnapshot(Base_stock):
    __tablename__ = "product_snapshot"

    barcode = Column(String, primary_key=True)
    name_en = Column(String, nullable=True)
    name_cn = Column(String, nullable=True)
    name_fr = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    specification = Column(String, nullable=True)
    category_code = Column(Numeric, nullable=True)
    category_name = Column(String, nullable=True)
    price_type = Column(String, nullable=True)
    unit_price = Column(Float, nullable=True)
    pack_qty = Column(Integer, nullable=True)
    pack_price = Column(Float, nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    original_price = Column(Float, nullable=True)
    unit_type = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    store = Column(String, nullable=True)
    update_time = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    
