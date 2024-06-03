from pydantic import BaseModel
from typing import List

class SaleItem(BaseModel):
    DocNum: str
    DocDate: str
    CardCode: str
    CardName: str
    Address: str

class Summary(BaseModel):
    Total: int
    Current: int
    Warning: int
    Danger: int

class SalesOrder(BaseModel):
    Details: list[SaleItem] | None
    Summary: Summary

class WeekOrderSummary(BaseModel):
    WeekPurchase: List[int]
    WeekSales: List[int]
    WeekDelivery: List[int]

class MonitorData(BaseModel):
    Sales: SalesOrder
    Delivery: SalesOrder
    POStore: SalesOrder | None
    POWarehouse: SalesOrder | None
    WeekOrderSummary: WeekOrderSummary | None

class Response(BaseModel):
    Message: str = "ok"
    Data: MonitorData | None = None
