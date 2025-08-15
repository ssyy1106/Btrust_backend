from pydantic import BaseModel
from typing import Optional

class StockPickupEntry(BaseModel):
    itemCode: str
    quantity: int
    store: Optional[str] = None
    pickupdate: Optional[str] = None  # 新增，可传 'YYYY-MM-DD' 格式

    class Config:
        orm_mode = True
