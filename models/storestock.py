from sqlalchemy import Column, Integer, String, DateTime, BigInteger
from database import Base_storestock
from sqlalchemy.sql import func

class StoreStock(Base_storestock):
    __tablename__ = "store_stock"

    id = Column(Integer, primary_key=True, index=True)
    item_code = Column(String, nullable=False, index=True)
    store = Column(String, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    update_time = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    modifier_id = Column(BigInteger, nullable=False)