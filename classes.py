from pydantic import BaseModel

class SaleItem(BaseModel):
    DocNum: str
    DocDate: str
    CardCode: str
    CardName: str
    Address: str

class PickDetails(BaseModel):
    ItemName: str
    ItemCode: str
    Open: int
    Picked: int
    Total: int

class PickItem(SaleItem):
    NumberOfItems: int
    DockLocation: str
    PickDetails: list[PickDetails]

class Summary(BaseModel):
    Total: int
    Current: int
    Warning: int
    Danger: int

class SalesOrder(BaseModel):
    Details: list[SaleItem] | None
    Summary: Summary

class WeekOrderSummary(BaseModel):
    WeekPurchase: list[int]
    WeekSales: list[int]
    WeekDelivery: list[int]

class PickListStatus(BaseModel):
    Details: list[PickItem] | None
    Summary: Summary

class MonitorData(BaseModel):
    Sales: SalesOrder
    Delivery: SalesOrder
    Purchase: SalesOrder
    POStore: SalesOrder | None
    POWarehouse: SalesOrder | None
    WeekOrderSummary: WeekOrderSummary | None
    PickListStatus: PickListStatus| None

class Response(BaseModel):
    Message: str = "ok"
    Data: MonitorData | None = None
