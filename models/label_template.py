from sqlalchemy import Column, BigInteger, String, Text, Integer, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from database import Base_stock

class LabelTemplate(Base_stock):
    __tablename__ = "label_template"

    id = Column(BigInteger, primary_key=True, index=True)
    code = Column(String(100), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    category = Column(String(50))
    version = Column(Integer, nullable=False, default=1)
    is_system = Column(Boolean, nullable=False, default=False)
    created_by = Column(BigInteger)
    template_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())