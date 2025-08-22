from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Any, Dict
from datetime import datetime
from uuid import UUID


class ProductInfoOut(BaseModel):
    barcode: str
    name_ch: Optional[str] = None
    name_en: Optional[str] = None

    class Config:
        orm_mode = True

class StockByLocationItem(BaseModel):
    session_id: str
    barcode: str
    name_ch: Optional[str] = None
    name_en: Optional[str] = None
    qty: int
    time: datetime
    create_time: datetime
    creator_id: Optional[str] = None
    modifier_id: Optional[str] = None

StockByLocationResponse = Dict[str, List[StockByLocationItem]]

class StocktakeItemBase(BaseModel):
    id: int
    location: str
    barcode: str
    qty: int
    time: datetime
    user_id: str   # 每条 item 自己的用户 ID


class StocktakeUpload(BaseModel):
    id: UUID
    timestamp: datetime
    deviceId: str
    #user_id: str   # 新增，必填
    stocktake: List[StocktakeItemBase]


class StocktakeItemOut(BaseModel):
    id: int
    location: str
    barcode: str
    name_ch: Optional[str] = None
    name_en: Optional[str] = None
    qty: int
    time: datetime
    session_id: UUID
    creator_id: Optional[str]
    modifier_id: Optional[str]
    create_time: datetime
    update_time: datetime

    model_config = ConfigDict(from_attributes=True) 
    # class Config:
    #     orm_mode = True

class Pagination(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int

class StocktakeSessionWithItems(BaseModel):
    id: UUID
    device_id: str
    timestamp: datetime
    creator_id: Optional[str]
    modifier_id: Optional[str]
    create_time: datetime
    update_time: datetime
    items: List[StocktakeItemOut]

    model_config = ConfigDict(from_attributes=True) 
    # class Config:
    #     orm_mode = True

class StocktakeSummaryResponse(BaseModel):
    pickupItems: List[StocktakeSessionWithItems]
    pagination: Pagination

class StocktakeSessionOut(BaseModel):
    id: UUID
    device_id: str
    timestamp: datetime
    creator_id: Optional[str]
    modifier_id: Optional[str]
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
