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
    OpenData: list[int] #The first seven numbers represent data for each day of the week, while the eighth number corresponds to data spanning more than seven days
    CloseData: list[int]

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

class PickListStatus(BaseModel):
    Details: list[PickItem] | None
    Summary: Summary

class MonitorData(BaseModel):
    Sales: SalesOrderWeek
    Delivery: SalesOrder
    Purchase: SalesOrder
    POStore: SalesOrder | None
    POWarehouse: SalesOrder | None
    WeekOrderSummary: WeekOrderSummary | None
    PickListStatus: PickListStatus| None

class Response(BaseModel):
    Message: str = "ok"
    Data: MonitorData | None = None
