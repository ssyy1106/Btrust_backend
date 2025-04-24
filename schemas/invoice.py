from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime

class InvoiceDetailCreate(BaseModel):
    totalamount: float
    department: Optional[int]

class InvoiceCreate(BaseModel):
    number: str
    totalamount: float
    remark: Optional[str]
    invoicedate: date
    entrytime: date
    department: Optional[int]
    #creatorid: int
    details: List[InvoiceDetailCreate]

class InvoiceResponse(BaseModel):
    id: int
    createtime: datetime
    modifytime: datetime
    creatorid: int
    modifierid: Optional[int] = None
    number: str
    status: int
    totalamount: float
    remark: Optional[str] = None
    invoicedate: Optional[date] = None
    entrytime: Optional[date] = None
    department: int

    class Config:
        orm_mode = True  # 让 Pydantic 支持从 SQLAlchemy 模型中提取数据