from hdbcli import dbapi
from fastapi import FastAPI, WebSocket, HTTPException, status, Request, Header, Depends
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.config import Config
from pathlib import Path
import os
import pyodbc
import logging
import configparser
import datetime
import asyncio
from contextlib import asynccontextmanager
from classes import SaleItem, Summary, SalesOrder, MonitorData, Response, WeekOrderSummary
from html_template import html
from hana import getSalesOrder, getDeliveryOrder, getPurchaseOrder, getWeekOrderOverview, getPickListStatus, getPickListByDepartment, getExpiredItems
from PO import getPOStoreOrder, getPOWareOrder
from mygraphql import graphql_app
from pydantic import BaseModel
from helper import LoginShift, verify_token, create_jwt_token, verify_jwt_token, get_user_information
from graphqlschema.schema import UserInformation
from routers import attachments, bos_api, cost, download, invoice, pickup, product, stock, storepickup, storestock, supplier
from routers.report import invoice as report_invoice
from routers.report import labor as report_labor
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.concurrency import run_in_threadpool
from init_db import init_db
from config_log_env import load_env, init_config, init_logging
from database import init_database

 
BASE_DIR = Path(__file__).resolve().parent  # main.py 所在目录
ENV_PATH = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "config.ini"

config_env = Config(str(ENV_PATH))
origins = config_env("CORS_ORIGINS", cast=lambda v: [s.strip() for s in v.split(",")])
config = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global config
    # 应用启动时执行
    load_env(ENV_PATH)
    config = init_config(CONFIG_PATH)
    init_logging()
    init_database()
    bos_api.init_odoo()
    await init_db()
    yield

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(lifespan=lifespan)

# 注册限流异常处理器
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ⭐ 注册全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        # 警告: 在生产环境中，为了安全不应将原始异常信息 `str(exc)` 返回给客户端。
        content={"detail": str(exc)},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cost.router)
app.include_router(invoice.router)
app.include_router(supplier.router)
app.include_router(attachments.router)
app.include_router(stock.router)
app.include_router(pickup.router)
app.include_router(storestock.router)
app.include_router(product.router)
app.include_router(download.router)
app.include_router(storepickup.router)
app.include_router(bos_api.router)
app.include_router(report_invoice.router)
app.include_router(report_labor.router)

app.include_router(graphql_app, prefix="/graphql")

directory = '.\\'
file = datetime.datetime.now(datetime.timezone.utc).isoformat()[:10]
#logging.basicConfig(filename=directory + file + '.log', encoding='utf-8', level=logging.DEBUG)
logging.info('Start......')


def sync_getResponse() -> Response | None:
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

async def getResponse() -> Response | None:
    # 将同步的、阻塞的 getResponse 函数放入线程池中运行，以避免阻塞asyncio事件循环
    return await run_in_threadpool(sync_getResponse)

@app.get("/")
async def root():
    # return {"message": "Hello World"}
    return HTMLResponse(html)

@app.get("/ping")
async def ping():
    return PlainTextResponse("ok")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            res = await getResponse()
            #data = await websocket.receive_text()
            await websocket.send_json(jsonable_encoder(res))
            await asyncio.sleep(float(config['duration']['second']))
    except Exception as e:
        # 捕获更具体的异常，避免隐藏其他bug
        # from starlette.websockets import WebSocketDisconnect
        print(f"Client disconnect or error: {e}")

@app.get("/monitor")
async def monitor() -> Response | None:
    logging.info(f"visit enpoint monitor")
    return await getResponse()

@app.get("/token")
@limiter.limit("500/minute")
async def token(request: Request, user=Depends(verify_token)):
    return {"user": user}

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

