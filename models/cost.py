from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, JSON, Time, BigInteger, Boolean
from database import Base_cost
import datetime

class CostImport(Base_cost):
    __tablename__ = "cost_imports"

    id = Column(Integer, primary_key=True, index=True)
    store = Column(String(2), nullable=False)                # 店铺
    department = Column(String, nullable=False)         # 部门
    month = Column(String(7), nullable=False)           # 年月，比如 2025-06
    cost = Column(Float, nullable=False)                     # 成本
    created_at = Column(DateTime, default=datetime.datetime.now())
    updated_at = Column(
        DateTime,
        default=datetime.datetime.now(),
        onupdate=datetime.datetime.now()
    )

    def __repr__(self):
        return f"<CostImport(id={self.id}, store={self.store}, year_month={self.year_month}, cost={self.cost})>"
