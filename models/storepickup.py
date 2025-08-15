from sqlalchemy import Column, Integer, String, DateTime, BigInteger, Date
from database import Base_storestock
from sqlalchemy.sql import func

class StorePickup(Base_storestock):
    __tablename__ = "store_stock_with_pickup"

    id = Column(Integer, primary_key=True, index=True)
    item_code = Column(String, nullable=False, index=True)
    store = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    modifier_id = Column(BigInteger, nullable=True)
    modifier_name = Column(String, nullable=True)  # 新增保存用户名字段
    pickupdate = Column(Date, nullable=False)