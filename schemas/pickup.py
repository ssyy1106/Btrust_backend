# -*- coding: utf-8 -*-
from typing import List, Optional, Dict
from pydantic import BaseModel

class StoreStockEntry(BaseModel):
    store: str
    quantity: int
    modifierName: Optional[str] = None
    updateTime: Optional[str] = None

class StoreQuantity(BaseModel):
    store: str
    quantity: int

class PickupItem(BaseModel):
    itemCode: str
    orders: List[StoreQuantity]
    stockAtHQ: Optional[int] = None
    categoryName: Optional[str] = None
    name: Dict[str, str]  # { "en_US": "...", "zh_CN": "...", "zh_TW": "..." }
    storeStock: List[StoreStockEntry] = []

class PickupSummaryResponse(BaseModel):
    pickupItems: List[PickupItem]

# class StoreQuantity(BaseModel):
#     store: str
#     quantity: int

# class BatchInfo(BaseModel):
#     batchNumber: str                     # 批号（DistNumber / BatchNumber）
#     location: Optional[str] = None       # 库位（BinCode），若无库位启用则为空
#     unitsPerCase: int                    # 每箱件数（INNER_PACK）
#     quantityUnits: int                   # 该批该库位的件数（OnHandQty）
#     quantityCases: int                   # 该批该库位的箱数（= floor(件数/每箱件数)）
#     costPerCase: float                   # 每箱成本（按你原逻辑推导）
#     vendorCode: Optional[str] = None
#     vendorName: Optional[str] = None

# class PickupItem(BaseModel):
#     itemCode: str                        # 注意：这里用的是 Odoo 的 default_code，对应 SAP 的 ItemCode
#     orders: List[StoreQuantity]          # Odoo 订货明细（门店与件数）
#     totalStockUnits: int                 # SAP 库存总件数（所有批次+库位汇总）
#     totalStockCases: int                 # SAP 库存总箱数
#     batches: List[BatchInfo]             # SAP 批次+库位的明细

# class PickupSummaryResponse(BaseModel):
#     pickupItems: List[PickupItem]
