# -*- coding: utf-8 -*-
from typing import List, Optional, Dict
from pydantic import BaseModel

class StoreStockEntry(BaseModel):
    store: str
    quantity: int
    modifierName: Optional[str] = None
    updateTime: Optional[str] = None

# class StoreQuantity(BaseModel):
#     store: str
#     quantity: int
class OrderDetail(BaseModel):
    name: str
    date_order: str
    note: Optional[str]

class StoreOrder(BaseModel):
    store: str
    quantity: int
    detail: Optional[List[OrderDetail]] = None   # 只有 order=True 时才有

class PickupItem(BaseModel):
    itemCode: str
    orders: List[StoreOrder]
    # orders: List[StoreQuantity]
    stockAtHQ: Optional[int] = None
    categoryName: Optional[str] = None
    name: Dict[str, str]  # { "en_US": "...", "zh_CN": "...", "zh_TW": "..." }
    storeStock: List[StoreStockEntry] = []

class Pagination(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int

class PickupSummaryResponse(BaseModel):
    pickupItems: List[PickupItem]
    pagination: Pagination

