import fastapi.middleware
import fastapi.middleware.cors
import fastapi.middleware.httpsredirect
import fastapi.middleware.wsgi
from hdbcli import dbapi
from fastapi import FastAPI, WebSocket, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
import fastapi
import pyodbc
import logging
import configparser
import datetime
import asyncio
from classes import SaleItem, Summary, SalesOrder, MonitorData, Response, WeekOrderSummary
from html import html
from hana import getSalesOrder, getDeliveryOrder, getPurchaseOrder, getWeekOrderOverview, getPickListStatus, getPickListByDepartment, getExpiredItems
from PO import getPOStoreOrder, getPOWareOrder
from mygraphql import graphql_app
from pydantic import BaseModel
from secure import create_jwt_token
from helper import LoginShift
 
app = FastAPI()
origins = [
    "http://localhost:3000",
    "http://172.16.10.106:3000",
    "http://localhost",
    "http://localhost:8000",
    "http://172.16.30.8:8000",
    "http://172.16.30.8",
    "http://172.16.30.8:81"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graphql_app, prefix="/graphql")
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
    # sql server
    USERNAME = config['POsqlserver']['name']
    PASSWORD = config['POsqlserver']['password']
    SERVER = config['POsqlserver']['host']
    DATABASE = config['POsqlserver']['database']
    connectionString = f'DRIVER={{SQL Server}};SERVER={SERVER};DATABASE={DATABASE};UID={USERNAME};PWD={PASSWORD}'
    connSQLServer = pyodbc.connect(connectionString)
    cursorSQLServer= connSQLServer.cursor()

    try:
        # get sales orders
        salesOrders = getSalesOrder(cursor, schema, config)
        logging.info(f"sales order: {salesOrders}")
       
        # get delivery sales orders
        deliveryOrders = getDeliveryOrder(cursor, schema, config)
        logging.info(f"delivery order: {deliveryOrders}")
        
        #get Purchase orders(SAP Data)
        purchaseOrders = getPurchaseOrder(cursor, schema, config)
        logging.info(f"Purchase order: {purchaseOrders}")

        #get Picking up orders status data
        PickListStatus = getPickListStatus(cursor, schema, config)
        logging.info(f"Pick order: {PickListStatus}")
        
        #get PickItem by department
        PickListByDepartment = getPickListByDepartment(cursor, schema, config)

        #get weekOrder overview data
        weekOrderSummary = getWeekOrderOverview(cursor, schema, config)
        logging.info(f"WeekOrderOverview: {weekOrderSummary}")

        # get po orders 
        poStoreOrders = getPOStoreOrder(cursorSQLServer)
        poWarehouseOrders = getPOWareOrder(cursorSQLServer)

        expirationItem = getExpiredItems(cursor, schema, config)
        
        #return data to frontend
        data = MonitorData(Sales=salesOrders, Delivery=deliveryOrders, Purchase=purchaseOrders, POStore=poStoreOrders, 
                           POWarehouse=poWarehouseOrders, WeekOrderSummary=weekOrderSummary, PickListStatus= PickListStatus, 
                           FrozenPickItem=PickListByDepartment["Frozen"], GroceryPickItem=PickListByDepartment["Grocery"],
                           ExpirationItem = expirationItem)
        
        res = Response(Data=data, Message="ok")
        return res
    except Exception as err:
        print(f"Something wrong, error is {err}")
        logging.error(f"visit enpoint monitor error, {err}")
    finally:
        cursor.close()
        cursorSQLServer.close()
        conn.close()
        connSQLServer.close()
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
    
# Login Model
class Login(BaseModel):
    username: str
    password: str

@app.post("/login")
async def login(user: Login):
    ok, userId = LoginShift(user.username, user.password)
    if not ok:
    #if user.username != 'admin' or user.password != '123456':
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    token_data = {"sub": str(userId)}
    token = create_jwt_token(data=token_data)
    return {"access_token": token, "token_type": "bearer"}