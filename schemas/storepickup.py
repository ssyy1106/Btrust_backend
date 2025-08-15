from pydantic import BaseModel
from typing import Optional, List

class StockPickupEntry(BaseModel):
    itemCode: str
    quantity: int
    store: Optional[str] = None
    pickupdate: Optional[str] = None  # 新增，可传 'YYYY-MM-DD' 格式

    class Config:
        orm_mode = True

class StorePickupEntry(BaseModel):
    store: str
    quantity: int
    modifierName: Optional[str] = None
    updateTime: Optional[str] = None

class PickupItem(BaseModel):
    itemCode: str
    storePickup: List[StorePickupEntry] = []

class PickupStockResponse(BaseModel):
    pickupItems: List[PickupItem]