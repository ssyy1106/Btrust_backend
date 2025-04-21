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
    creatorid: int
    details: List[InvoiceDetailCreate]
