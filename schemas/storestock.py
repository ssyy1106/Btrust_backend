from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# 更新库存的请求
class StockUpdateEntry(BaseModel):
    itemCode: str
    quantity: int
    store: Optional[str] = None  # 如果不填，自动用用户的 store

# 查询库存的响应
class StockEntry(BaseModel):
    store: str
    quantity: int
    update_time: datetime
    modifier_id: int

class StockItem(BaseModel):
    itemCode: str
    stock: List[StockEntry]

class StockResponse(BaseModel):
    stockEntries: List[StockItem]
    