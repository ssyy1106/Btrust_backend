from hdbcli import dbapi
from fastapi import FastAPI, WebSocket, HTTPException, status, Request, Header, Depends
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.config import Config
import os
import pyodbc
import logging
import configparser
import datetime
import asyncio
from contextlib import asynccontextmanager
from classes import SaleItem, Summary, SalesOrder, MonitorData, Response, WeekOrderSummary
from html import html
from hana import getSalesOrder, getDeliveryOrder, getPurchaseOrder, getWeekOrderOverview, getPickListStatus, getPickListByDepartment, getExpiredItems
from PO import getPOStoreOrder, getPOWareOrder
from mygraphql import graphql_app
from pydantic import BaseModel
from helper import LoginShift, verify_token, create_jwt_token, verify_jwt_token, get_user_information
from graphqlschema.schema import UserInformation
from routers import attachments, bos_api, cost, download, invoice, pickup, product, stock, storepickup, storestock, supplier
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from init_db import init_db
# from pyzbar.pyzbar import decode
# from PIL import Image
# import cv2
# import numpy as np
 
#app = FastAPI()
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 应用启动时执行
    await init_db()
    yield
    # async with engine.begin() as conn:
    #     await conn.run_sync(Base_invoice.metadata.create_all)
    # yield
    # # 应用启动时，两个数据库都创建表
    # async with engine.begin() as conn_invoice:
    #     await conn_invoice.run_sync(Base_invoice.metadata.create_all)
    # async with engine_cost.begin() as conn_cost:
    #     await conn_cost.run_sync(Base_cost.metadata.create_all)
    # 应用关闭时执行（如有需要可以添加清理逻辑）

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
        content={"detail": str(exc)},
    )

# origins = [
#     "http://localhost:3000",
#     "http://172.16.10.106:3000",
#     "http://localhost",
#     "http://localhost:8000",
#     "http://172.16.30.8:8000",
#     "http://172.16.30.8",
#     "http://172.16.30.8:81",
#     "http://172.16.30.8:82",
#     "http://172.16.30.8:8200",
#     "http://172.16.10.81:3000",
#     "https://172.16.30.8:8501",
#     "https://172.16.30.8:8502",
#     "http://172.16.30.8:8601",
#     "http://172.16.30.8:8600"
# ]
env_path = ".env"

# 手动以 utf-8 打开
with open(env_path, "r", encoding="utf-8") as f:
    lines = f.read().splitlines()

# 临时写入 os.environ
for line in lines:
    if line.strip() == "" or line.startswith("#"):
        continue
    key, value = line.split("=", 1)
    os.environ[key.strip()] = value.strip()

# 然后直接初始化 Config，不带 encoding
config_env = Config(".env")
origins = config_env("CORS_ORIGINS", cast=lambda v: [s.strip() for s in v.split(",")])

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
    except:
        print(f"Client disconnect")

@app.get("/monitor")
async def monitor() -> Response | None:
    logging.info(f"visit enpoint monitor")
    return await getResponse()

@app.get("/token")
@limiter.limit("500/minute")
async def token(request: Request, user=Depends(verify_token)):
    # # 读取图片
    # image = Image.open("download.png").convert("RGBA")
    # bg = Image.new("RGB", image.size, (255, 255, 255))
    # bg.paste(image, mask=image.split()[3])  # 使用 alpha 通道作为 mask
    # image = bg
    # image = image.resize((image.width*4, image.height*4))

    # cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    # gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
    # _, thresh = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    # barcodes = decode(thresh)
    # print(barcodes)
    # # 解码条码
    # # barcodes = decode(image)
    # # print(f"barcodes: {barcodes}")
    # for barcode in barcodes:
    #     barcode_data = barcode.data.decode("utf-8")
    #     barcode_type = barcode.type
    #     print(f"条码内容: {barcode_data}, 类型: {barcode_type}")
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

# app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
# app.mount("/thumbnails", StaticFiles(directory="thumbnails"), name="thumbnails")
