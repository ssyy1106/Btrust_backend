from pydantic import BaseModel
from hdbcli import dbapi
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.encoders import jsonable_encoder
import logging
import configparser
import datetime
import time
import asyncio
import json

app = FastAPI()

html = """
<!DOCTYPE html>
<html>
    <head>
        <title>Chat</title>
    </head>
    <body>
        <h1>WebSocket Chat</h1>
        <form action="" onsubmit="sendMessage(event)">
            <input type="text" id="messageText" autocomplete="off"/>
            <button>Send</button>
        </form>
        <ul id='messages'>
        </ul>
        <script>
            var ws = new WebSocket("ws://localhost:8000/ws");
            ws.onmessage = function(event) {
                var messages = document.getElementById('messages')
                var message = document.createElement('li')
                var content = document.createTextNode(event.data)
                message.appendChild(content)
                messages.appendChild(message)
            };
            function sendMessage(event) {
                var input = document.getElementById("messageText")
                ws.send(input.value)
                input.value = ''
                event.preventDefault()
            }
        </script>
    </body>
</html>
"""

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

def getRangeCount(begin: str, end: str, table: str, cursor) -> int:
    cursor.execute(f"SELECT Count(1) FROM {table} where \"DocStatus\"='O' and \"DocDate\" >= '{begin}' and \"DocDate\" <= '{end}'")
    res = cursor.fetchone()
    if res:
        return res[0]
    return 0

def getConfigDays() -> tuple:
    today = datetime.datetime.now()
    currentBegin, currentEnd = config['Current']['begin'], config['Current']['end']
    warningBegin, warningEnd = config['Warning']['begin'], config['Warning']['end']
    DangerBegin, DangerEnd = config['Danger']['begin'], config['Danger']['end']
    currentBeginStr, currentEndStr = (today + datetime.timedelta(days=int(currentBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(currentEnd))).strftime('%Y-%m-%d')
    warningBeginStr, warningEndStr = (today + datetime.timedelta(days=int(warningBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(warningEnd))).strftime('%Y-%m-%d')
    DangerBeginStr, DangerEndStr = (today + datetime.timedelta(days=int(DangerBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(DangerEnd))).strftime('%Y-%m-%d')
    return (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr)

def getSalesOrder(cursor, schema):
    (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr) = getConfigDays()
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.ORDR where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
    current = getRangeCount(currentBeginStr, currentEndStr, schema + '.ORDR', cursor)
    warning = getRangeCount(warningBeginStr, warningEndStr, schema + '.ORDR', cursor)
    danger = getRangeCount(DangerBeginStr, DangerEndStr, schema + '.ORDR', cursor)
    output = SalesOrder(Details=details, Summary=Summary(Total=count, Current=current, Warning=warning, Danger=danger))
    return output 

def getDeliveryOrder(cursor, schema):
    (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr) = getConfigDays()
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.ODLN where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
    
    current = getRangeCount(currentBeginStr, currentEndStr, schema + '.ODLN', cursor)
    warning = getRangeCount(warningBeginStr, warningEndStr, schema + '.ODLN', cursor)
    danger = getRangeCount(DangerBeginStr, DangerEndStr, schema + '.ODLN', cursor)
    output = SalesOrder(Details=details, Summary=Summary(Total=count, Current=current, Warning=warning, Danger=danger))
    return output 

async def getResponse() -> Response | None:
    conn = dbapi.connect(
        address=config['Hana']['address'],
        port=config['Hana']['port'],
        user=config['Hana']['user'],
        password=config['Hana']['password']
    )
    cursor = conn.cursor()
    schema = config['Hana']['schema']
    try:
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

@app.get("/")
async def root():
    # return {"message": "Hello World"}
    return HTMLResponse(html)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await asyncio.sleep(float(config['duration']['second']))
            res = await getResponse()
            #data = await websocket.receive_text()
            await websocket.send_json(jsonable_encoder(res))
    except:
        print(f"Client disconnect")

@app.get("/monitor")
async def monitor() -> Response | None:
    logging.info(f"visit enpoint monitor")
    return await getResponse()
    
