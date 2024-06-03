from pydantic import BaseModel

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

class MonitorData(BaseModel):
    Sales: SalesOrder
    Delivery: SalesOrder
    Purchase: SalesOrder
    POStore: SalesOrder | None
    POWarehouse: SalesOrder | None

class Response(BaseModel):
    Message: str = "ok"
    Data: MonitorData | None = None
