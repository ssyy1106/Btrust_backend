from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, BigInteger, Float, Numeric, Boolean, Date
from sqlalchemy.orm import relationship
from database import Base_stock
from sqlalchemy.dialects.postgresql import UUID, ARRAY
import datetime
import uuid

def utcnow():
    return datetime.datetime.now()

class StocktakeSession(Base_stock):
    __tablename__ = 'stocktake_session'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    device_id = Column(String, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)  # 前端上传时间
    store = Column(String, nullable=True)

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
    store = Column(String, nullable=True)

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
    tax = Column(Integer, nullable=True)
    unit_type = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    store = Column(String, primary_key=True)
    department = Column(String, nullable=True)
    subdepartment = Column(String, nullable=True)
    update_time = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class Job(Base_stock):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="pending")
    payload_key = Column(String, nullable=False)
    create_time = Column(DateTime(timezone=True), default=utcnow)
    update_time = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class InstorePriceSession(Base_stock):
    __tablename__ = 'instoreprice_session'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    creator_id = Column(String(50), nullable=False)
    modifier_id = Column(String(50), nullable=True)
    create_time = Column(DateTime(timezone=True), default=utcnow)
    update_time = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    items = relationship("InstorePriceItem", back_populates="session", cascade="all, delete-orphan")

class InstorePriceItem(Base_stock):
    __tablename__ = 'instoreprice_item'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey('instoreprice_session.id', ondelete="CASCADE"), nullable=False)
    upc = Column(String(50), nullable=False)
    store = Column(String, nullable=True)
    status = Column(String(20), nullable=False, default='pending')
    price_type = Column(String(30), nullable=False, default='instore')
    old_price = Column(Numeric(10,2), nullable=True)
    new_price = Column(Numeric(10,2), nullable=False)
    from_date = Column(Date, nullable=True)
    to_date = Column(Date, nullable=True)
    package_deal_enabled = Column(Boolean, nullable=False, default=False)
    package_qty = Column(Integer, nullable=True)
    package_price = Column(Numeric(10,2), nullable=True)
    label_types = Column(ARRAY(Integer), nullable=True)
    create_time = Column(DateTime(timezone=True), default=utcnow)
    update_time = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    session = relationship("InstorePriceSession", back_populates="items")

class InstorePriceApprovalLog(Base_stock):
    __tablename__ = 'instoreprice_approval_log'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    item_id = Column(BigInteger, ForeignKey('instoreprice_item.id', ondelete="SET NULL"), nullable=True)
    session_id = Column(UUID(as_uuid=True), nullable=False)
    upc = Column(String(50), nullable=False)
    action = Column(String(20), nullable=False) # approve, reject, auto_reject, cancel
    action_by = Column(String(50), nullable=False)
    action_time = Column(DateTime(timezone=True), default=utcnow)
    snapshot_price = Column(Numeric(10,2))
    snapshot_data = Column(JSON, nullable=False)

    item = relationship("InstorePriceItem")

class InstorePricePrintLog(Base_stock):
    __tablename__ = 'instoreprice_print_log'

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    approval_log_id = Column(BigInteger, ForeignKey('instoreprice_approval_log.id', ondelete="CASCADE"), nullable=False)
    label_id = Column(BigInteger, nullable=False)
    printed_by = Column(String(50), nullable=True)
    printed_time = Column(DateTime(timezone=False), default=utcnow, nullable=False)
    print_count = Column(Integer, nullable=False, default=1)

    approval_log = relationship("InstorePriceApprovalLog")
    
