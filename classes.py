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

# This class represents a summary of data over a week.
# Each attribute represents the data for a specific day.
class WeeklyDataSummary(BaseModel):
    OpenData: list[int] #The first number corresponds to the longer days, and the rest 7 numbers correspond to the most recent week summary
    CloseData: list[int]

# this shows the sales, delivery, purchase order week view summary
class SalesOrderWeek(BaseModel):
    Details: list[SaleItem] | None
    Summary: WeeklyDataSummary

class SalesOrder(BaseModel):
    Details: list[SaleItem] | None
    Summary: Summary

class WeekOrderSummary(BaseModel):
    WeekPurchase: list[int]
    WeekSales: list[int]
    WeekDelivery: list[int]

class PickItemDetail(BaseModel):
    PickListNumber: str
    CreateDate: str
    DockNumber: str
    PickPackRemarks: str
    CardCode: str

class FrozenPickItem(BaseModel):
    Details: list[PickItemDetail]
    Summary: WeeklyDataSummary | None

class GroceryPickItem(BaseModel):
    Details: list[PickItemDetail]
    Summary: WeeklyDataSummary | None

class OtherPickItem(BaseModel):
    Details: list[PickItemDetail]
    Summary: WeeklyDataSummary | None

class PickListStatus(BaseModel):
    Details: list[PickItem] | None
    Summary: Summary

class ExpirationItemDetail(BaseModel):
    ItemCode: str
    ItemName: str
    FrgnName: str
    ItemGrpCode: str
    Quantity: int
    FreeQuantity: int
    BuyUnitMsr: str
    SSCC: str
    StoreLocCode: str
    PmxWhsCode: str
    BatchNumber: str
    BestBeforeDate: str
    DaysUntilExpired: int
    MonthsUntilExpired: float

class ExpirationItemSummary(BaseModel):
    Interval: int
    Kind: str
    Items: int
    Quantity: int

class ExpirationItem(BaseModel):
    Details: list[ExpirationItemDetail] | None
    Summary: ExpirationItemSummary

class MonitorData(BaseModel):
    Sales: SalesOrderWeek | None
    Delivery: SalesOrderWeek | None
    Purchase: SalesOrderWeek | None
    POStore: SalesOrder | None
    POWarehouse: SalesOrder | None
    WeekOrderSummary: WeekOrderSummary | None
    PickListStatus: PickListStatus| None
    FrozenPickItem: FrozenPickItem | None
    GroceryPickItem: GroceryPickItem | None
    ExpirationItem: list[ExpirationItem] | None

class Response(BaseModel):
    Message: str = "ok"
    Data: MonitorData | None = None
