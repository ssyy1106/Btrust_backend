from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, JSON, Time, BigInteger, Boolean, Numeric, Text
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

class CostHRImport(Base_cost):
    __tablename__ = "cost_hr_imports"

    id = Column(Integer, primary_key=True, index=True)
    store = Column(Text, nullable=False)
    department = Column(Text, nullable=False)
    month = Column(String(7), nullable=False)
    cost = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.now())
    updated_at = Column(
        DateTime,
        default=datetime.datetime.now(),
        onupdate=datetime.datetime.now()
    )
    department_full_name = Column(Text)
    department_id = Column(Text)
    other_cost = Column(Numeric(12, 2))
    total_cost = Column(Numeric(12, 2))
    creator_id = Column(Text)