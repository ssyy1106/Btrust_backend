from pydantic import BaseModel, ConfigDict, field_validator
from typing import List, Optional, Any, Dict
from datetime import datetime
from uuid import UUID
import math


class ProductInfoOut(BaseModel):
    barcode: str
    name_ch: Optional[str] = None
    name_en: Optional[str] = None
    price: Optional[float] = None

    @field_validator("price", mode="before")
    def validate_price(cls, v):
        if v is None:
            return None
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except Exception:
            return None

    model_config = ConfigDict(from_attributes=True)

class StockByLocationItem(BaseModel):
    session_id: str
    barcode: str
    barcode_original: Optional[str] = None
    name_ch: Optional[str] = None
    name_en: Optional[str] = None
    price: Optional[float] = None
    tax: Optional[int] = None
    specification: Optional[str] = None
    unit_type: Optional[str] = None
    qty: int
    time: datetime
    create_time: datetime
    creator_id: Optional[str] = None
    modifier_id: Optional[str] = None

    @field_validator("price", "qty", mode="before")
    def clean_nan(cls, v):
        import math
        if v is None:
            return None
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except Exception:
            return None

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
    price: Optional[float] = None

    @field_validator("price", "qty", mode="before")
    def clean_nan(cls, v):
        import math
        if v is None:
            return None
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except Exception:
            return None

    model_config = ConfigDict(from_attributes=True) 
    # class Config:
    #     orm_mode = True

class StocktakeItemOutV2(BaseModel):
    id: int
    location: str
    barcode: str
    barcode_original: Optional[str] = None
    name_ch: Optional[str] = None
    name_en: Optional[str] = None
    qty: int
    time: datetime
    session_id: UUID
    creator_id: Optional[str]
    modifier_id: Optional[str]
    create_time: datetime
    update_time: datetime
    regular_price: Optional[float] = None
    active_price: Optional[float] = None
    package_price: Optional[float] = None
    package_count: Optional[float] = None
    tax: Optional[int] = None
    specification: Optional[str] = None
    unit_type: Optional[str] = None

    @field_validator("regular_price", "active_price", "package_price", "package_count", mode="before")
    def clean_nan(cls, v):
        import math
        if v is None:
            return None
        try:
            f = float(v)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except Exception:
            return None

    model_config = ConfigDict(from_attributes=True) 

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

class StocktakeItemSummaryResponse(BaseModel):
    pickupItems: List[StocktakeItemOut]
    pagination: Pagination
    model_config = ConfigDict(from_attributes=True) 

class StocktakeItemSummaryResponseV2(BaseModel):
    pickupItems: List[StocktakeItemOutV2]
    pagination: Pagination
    model_config = ConfigDict(from_attributes=True)

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

class ProductInfoResponse(BaseModel):
    products: list[ProductInfoOut]
    pagination: Pagination

class JobOut(BaseModel):
    id: str
    status: str
    payload_key: str
    create_time: datetime
    update_time: datetime

    model_config = ConfigDict(from_attributes=True)
