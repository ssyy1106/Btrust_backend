from fastapi import FastAPI
from pydantic import BaseModel
from hdbcli import dbapi

app = FastAPI()

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
    PO: SalesOrder | None

class Response(BaseModel):
    Message: str = "ok"
    Data: MonitorData | None = None

def getSalesOrder(cursor, schema):
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.ORDR where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
        
    output = SalesOrder(Details=details, Summary=Summary(Total=count, Current=0, Warning=0, Danger=0))
    return output 

def getDeliveryOrder(cursor, schema):
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.ODLN where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
        
    output = SalesOrder(Details=details, Summary=Summary(Total=count, Current=0, Warning=0, Danger=0))
    return output 

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/monitor")
async def monitor() -> Response | None:
    # connect db
    conn = dbapi.connect(
        address="hanabtrust", 
        port=30015, 
        user="SBOADMIN", 
        password="Btwsx76!"
    )
    cursor = conn.cursor()
    schema = "UPDATEROW_TEST_BTRUST"
    try:
        # get sales orders
        salesOrders = getSalesOrder(cursor, schema)
        # get delivery sales orders
        deliveryOrders = getDeliveryOrder(cursor, schema)
        # get po orders
        # poOrders = getPOOrder()
        #poOrders = getPOOrder(cursor, schema)
        data = MonitorData(Sales=salesOrders, Delivery=deliveryOrders, PO= None)
        res = Response(Data=data, Message="ok")
        return res
    except Exception as err:
        print(f"Somethin wrong, error is {err}")
    finally:
        cursor.close()
        conn.close()
    return None
