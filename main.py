from hdbcli import dbapi
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.encoders import jsonable_encoder
import logging
import configparser
import datetime
import asyncio
from classes import SaleItem, Summary, SalesOrder, MonitorData, Response
from html import html
from hana import getSalesOrder, getDeliveryOrder

app = FastAPI()

configFile = 'config.ini'
config = configparser.ConfigParser()
config.read(configFile, encoding="utf-8")

directory = '.\\'
file = datetime.datetime.now(datetime.timezone.utc).isoformat()[:10]
logging.basicConfig(filename=directory + file + '.log', encoding='utf-8', level=logging.DEBUG)
logging.info('Start......')

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
        salesOrders = getSalesOrder(cursor, schema, config)
        logging.info(f"sales order: {salesOrders}")
        # get delivery sales orders
        deliveryOrders = getDeliveryOrder(cursor, schema, config)
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
            res = await getResponse()
            #data = await websocket.receive_text()
            await websocket.send_json(jsonable_encoder(res))
            await asyncio.sleep(float(config['duration']['second']))
    except:
        print(f"Client disconnect")

@app.get("/monitor")
async def monitor() -> Response | None:
    logging.info(f"visit enpoint monitor")
    return await getResponse()
    
