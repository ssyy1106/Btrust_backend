from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime


class StocktakeItemBase(BaseModel):
    id: int
    location: str
    barcode: str
    qty: int
    time: datetime


class StocktakeUpload(BaseModel):
    id: str
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
    id: str
    device_id: str
    timestamp: datetime
    create_time: datetime
    update_time: datetime
    items: List[StocktakeItemOut]

    class Config:
        orm_mode = True

class StocktakeSessionOut(BaseModel):
    id: str
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
