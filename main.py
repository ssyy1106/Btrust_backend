from fastapi import FastAPI
from pydantic import BaseModel
from hdbcli import dbapi
import logging
import configparser
import datetime

app = FastAPI()

configFile = 'config.ini'
config = configparser.ConfigParser()
config.read(configFile, encoding="utf-8")

directory = '.\\'
file = datetime.datetime.now(datetime.timezone.utc).isoformat()[:10]
logging.basicConfig(filename=directory + file + '.log', encoding='utf-8', level=logging.DEBUG)
logging.info('Start......')

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
        address=config['Hana']['address'],
        port=config['Hana']['port'],
        user=config['Hana']['user'],
        password=config['Hana']['password']
    )
    cursor = conn.cursor()
    schema = "UPDATEROW_TEST_BTRUST"
    try:
        logging.info(f"visit enpoint monitor")
        # get sales orders
        salesOrders = getSalesOrder(cursor, schema)
        logging.info(f"sales order: {salesOrders}")
        # get delivery sales orders
        deliveryOrders = getDeliveryOrder(cursor, schema)
        logging.info(f"delivery order: {deliveryOrders}")
        # get po orders
        # poOrders = getPOOrder()
        #poOrders = getPOOrder(cursor, schema)
        data = MonitorData(Sales=salesOrders, Delivery=deliveryOrders, PO= None)
        res = Response(Data=data, Message="ok")
        return res
    except Exception as err:
        print(f"Somethin wrong, error is {err}")
        logging.error(f"visit enpoint monitor error, {err}")
    finally:
        cursor.close()
        conn.close()
    return None
