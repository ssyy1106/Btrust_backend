from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from datetime import datetime
from uuid import UUID


class ProductInfoOut(BaseModel):
    barcode: str
    name_ch: Optional[str]
    name_en: Optional[str]

    class Config:
        orm_mode = True

class StockByLocationItem(BaseModel):
    session_id: str
    barcode: str
    name_ch: Optional[str]
    name_en: Optional[str]
    qty: int
    time: datetime
    create_time: datetime

StockByLocationResponse = Dict[str, List[StockByLocationItem]]

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
    user_id: str   # 新增，必填
    stocktake: List[StocktakeItemBase]


class StocktakeItemOut(BaseModel):
    id: int
    location: str
    barcode: str
    name_ch: Optional[str]
    name_en: Optional[str]
    qty: int
    time: datetime
    session_id: UUID
    creator_id: Optional[str]
    modifier_id: Optional[str]
    create_time: datetime
    update_time: datetime

    class Config:
        orm_mode = True

class StocktakeSessionWithItems(BaseModel):
    id: UUID
    device_id: str
    timestamp: datetime
    creator_id: Optional[str]
    modifier_id: Optional[str]
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
