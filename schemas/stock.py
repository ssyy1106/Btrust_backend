from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime
from uuid import UUID


class StocktakeItemBase(BaseModel):
    id: int
    location: str
    barcode: str
    qty: int
    time: datetime


class StocktakeUpload(BaseModel):
    id: UUID
    timestamp: datetime
    deviceId: str
    stocktake: List[StocktakeItemBase]


class StocktakeItemOut(BaseModel):
    id: int
    location: str
    barcode: str
    qty: int
    time: datetime
    session_id: UUID
    create_time: datetime
    update_time: datetime

    class Config:
        orm_mode = True

class StocktakeSessionWithItems(BaseModel):
    id: UUID
    device_id: str
    timestamp: datetime
    create_time: datetime
    update_time: datetime
    items: List[StocktakeItemOut]

    class Config:
        orm_mode = True

class StocktakeSessionOut(BaseModel):
    id: UUID
    device_id: str
    timestamp: datetime
    create_time: datetime
    update_time: datetime

    class Config:
        orm_mode = True


class OperateLogOut(BaseModel):
    id: int
    api_name: str
    request_payload: Dict[str, Any]
    response_payload: Optional[dict]
    create_time: datetime

    class Config:
        orm_mode = True
