from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from helper import getInvoiceConfig, getCostConfig, getStockConfig, getOdooConfig, getStoreStockConfig, getStoreDBConfig, getLocalStore

store, DRIVER = getLocalStore()
(USERNAME, PASSWORD, HOST, DATABASE) = getStoreDBConfig(store)

# 构造连接字符串
DATABASE_URL_SQLSERVER = (
    f"mssql+aioodbc://{USERNAME}:{PASSWORD}@{HOST}/{DATABASE}"
    f"?driver={DRIVER.replace(' ', '+')}"  # 注意 driver 名字里的空格要替换成 +
)
print(f"DRIVER: {DRIVER} DATABASE_URL_SQLSERVER: {DATABASE_URL_SQLSERVER}")
engine_sqlserver = create_async_engine(
    DATABASE_URL_SQLSERVER,
    echo=True,
    pool_size=10,           # 连接池大小
    max_overflow=20,        # 超过 pool_size 时允许的额外连接
    pool_recycle=1800,      # 每 30 分钟回收一次连接
    pool_timeout=30,        # 等待连接的超时时间
    future=True
)

AsyncSessionLocal_sqlserver = async_sessionmaker(
    bind=engine_sqlserver, class_=AsyncSession, expire_on_commit=False
)

Base_store_sqlserver = declarative_base()

async def get_db_store_sqlserver():
    async with AsyncSessionLocal_sqlserver() as session:
        try:
            yield session
        finally:
            await session.close()
    
(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getInvoiceConfig()
DATABASE_URL_INVOICE = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine = create_async_engine(
    DATABASE_URL_INVOICE, 
    echo=True,
    pool_size=10,           # 连接池大小
    max_overflow=20,        # 超过 pool_size 时允许的额外连接
    pool_recycle=1800,      # 每 30 分钟回收一次连接，防止 timeout
    pool_timeout=30,        # 等待连接的超时时间
    future=True)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

Base_invoice = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getCostConfig()
DATABASE_URL_COST = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine_cost = create_async_engine(
    DATABASE_URL_COST, 
    echo=True,
    pool_size=10,           # 连接池大小
    max_overflow=20,        # 超过 pool_size 时允许的额外连接
    pool_recycle=1800,      # 每 30 分钟回收一次连接，防止 timeout
    pool_timeout=30,        # 等待连接的超时时间
    future=True)
#engine_cost = create_async_engine(DATABASE_URL_COST, echo=True)
AsyncSessionLocal_cost = async_sessionmaker(bind=engine_cost, class_=AsyncSession, expire_on_commit=False)

Base_cost = declarative_base()

async def get_db_cost():
    async with AsyncSessionLocal_cost() as session:
        try:
            yield session
        finally:
            await session.close()

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getStockConfig()
DATABASE_URL_STOCK = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine_stock = create_async_engine(
    DATABASE_URL_STOCK, 
    echo=True,
    pool_size=10,           # 连接池大小
    max_overflow=20,        # 超过 pool_size 时允许的额外连接
    pool_recycle=1800,      # 每 30 分钟回收一次连接，防止 timeout
    pool_timeout=30,        # 等待连接的超时时间
    future=True)
AsyncSessionLocal_stock = async_sessionmaker(bind=engine_stock, class_=AsyncSession, expire_on_commit=False)

Base_stock = declarative_base()

async def get_db_stock():
    async with AsyncSessionLocal_stock() as session:
        try:
            yield session
        finally:
            await session.close()

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getOdooConfig()
DATABASE_URL_ODOO = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine_odoo = create_async_engine(
    DATABASE_URL_ODOO, 
    echo=True,
    pool_size=10,           # 连接池大小
    max_overflow=20,        # 超过 pool_size 时允许的额外连接
    pool_recycle=1800,      # 每 30 分钟回收一次连接，防止 timeout
    pool_timeout=30,        # 等待连接的超时时间
    future=True)
AsyncSessionLocal_odoo = async_sessionmaker(bind=engine_odoo, class_=AsyncSession, expire_on_commit=False)

Base_odoo = declarative_base()

async def get_db_odoo():
    async with AsyncSessionLocal_odoo() as session:
        try:
            yield session
        finally:
            await session.close()

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getStoreStockConfig()
DATABASE_URL_STORESTOCK = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine_storestock = create_async_engine(
    DATABASE_URL_STORESTOCK, 
    echo=True,
    pool_size=10,           # 连接池大小
    max_overflow=20,        # 超过 pool_size 时允许的额外连接
    pool_recycle=1800,      # 每 30 分钟回收一次连接，防止 timeout
    pool_timeout=30,        # 等待连接的超时时间
    future=True)
AsyncSessionLocal_storestock = async_sessionmaker(bind=engine_storestock, class_=AsyncSession, expire_on_commit=False)

Base_storestock = declarative_base()

async def get_db_storestock():
    async with AsyncSessionLocal_storestock() as session:
        try:
            yield session
        finally:
            await session.close()