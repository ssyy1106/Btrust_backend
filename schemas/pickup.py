from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class StoreQuantity(BaseModel):
    store: str
    quantity: int

class PickupItem(BaseModel):
    itemCode: str
    orders: List[StoreQuantity]

class PickupSummaryResponse(BaseModel):
    pickupItems: List[PickupItem]

