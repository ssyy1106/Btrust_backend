from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class StocktakeItemBase(BaseModel):
    id: int
    location: str
    barcode: str
    qty: int
    time: datetime


class StocktakeUpload(BaseModel):
    timestamp: datetime
    deviceId: str
    stocktake: List[StocktakeItemBase]


class StocktakeItemOut(BaseModel):
    id: int
    location: str
    barcode: str
    qty: int
    time: datetime
    session_id: int
    create_time: datetime
    update_time: datetime

    class Config:
        orm_mode = True

class StocktakeSessionWithItems(BaseModel):
    id: int
    device_id: str
    timestamp: datetime
    create_time: datetime
    update_time: datetime
    items: List[StocktakeItemOut]

    class Config:
        orm_mode = True

class StocktakeSessionOut(BaseModel):
    id: int
    device_id: str
    timestamp: datetime
    create_time: datetime
    update_time: datetime

    class Config:
        orm_mode = True


class OperateLogOut(BaseModel):
    id: int
    api_name: str
    request_payload: dict
    response_payload: Optional[dict]
    create_time: datetime

    class Config:
        orm_mode = True
