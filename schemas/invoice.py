from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime
from enum import IntEnum

class InvoiceStatus(IntEnum):
    CONFIRMED = 0
    Voided = 1
    DRAFT = 2

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
    supplier: int
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
    #department: int
    supplier: int

    class Config:
        orm_mode = True  # 让 Pydantic 支持从 SQLAlchemy 模型中提取数据

class InvoiceAttachmentOut(BaseModel):
    id: int
    path: str
    thumbnail: str
    # model_config = {
    #     "from_attributes": True
    # }
    class Config:
        orm_mode = True

class InvoiceOut(BaseModel):
    id: int
    number: str
    totalamount: float
    invoicedate: date
    #department: int
    attachments: List[InvoiceAttachmentOut] = []
    supplier: int
    # model_config = {
    #     "from_attributes": True
    # }
    class Config:
        orm_mode = True

class InvoiceDetailOut(BaseModel):
    id: int
    totalamount: float
    department: int

    class Config:
        orm_mode = True

class InvoiceAttachmentOut(BaseModel):
    id: int
    path: str
    thumbnail: Optional[str]

    class Config:
        orm_mode = True

class SupplierBase(BaseModel):
    name: str
    telephone: Optional[str] = None
    remark: Optional[str] = None
    email: Optional[str] = None
    contact: Optional[str] = None
    status: Optional[int] = 0

class SupplierCreate(SupplierBase):
    pass

class SupplierOut(SupplierBase):
    id: int

    class Config:
        orm_mode = True

class InvoiceOutFull(BaseModel):
    id: int
    number: Optional[str] = None
    totalamount: Optional[float] = None
    invoicedate: Optional[date] = None
    entrytime: Optional[date] = None
    store: Optional[str] = None
    status: Optional[InvoiceStatus]
    #department: int
    supplier: Optional[SupplierOut] = None
    attachments: List[InvoiceAttachmentOut] = []
    details: List[InvoiceDetailOut] = []
    createtime: Optional[datetime] = None
    remark: Optional[str]
    department_total_amount: Optional[float] = None
    #isdraft: Optional[bool]

    #supplier_name: Optional[str] = None
    class Config:
        use_enum_values = True  # 输出 JSON 时显示 数字 0 1 2
        orm_mode = True