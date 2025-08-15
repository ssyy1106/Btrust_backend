from pydantic import BaseModel
from typing import List, Optional, Dict
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
    update_time: Optional[datetime] = None
    modifier_id: Optional[int] = None
    modifier_name: Optional[str] = None
    last_order_date: Optional[datetime] = None

class StockItem(BaseModel):
    itemCode: str
    stock: List[StockEntry]
    name: Optional[Dict[str,str]] = None

class StockResponse(BaseModel):
    stockEntries: List[StockItem]
    