from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from helper import getInvoiceConfig, getCostConfig, getStockConfig, getOdooConfig, getStoreStockConfig

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getInvoiceConfig()
DATABASE_URL_INVOICE = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine = create_async_engine(DATABASE_URL_INVOICE, echo=True)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

Base_invoice = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getCostConfig()
DATABASE_URL_COST = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine_cost = create_async_engine(DATABASE_URL_COST, echo=True)
AsyncSessionLocal_cost = sessionmaker(bind=engine_cost, class_=AsyncSession, expire_on_commit=False)

Base_cost = declarative_base()

async def get_db_cost():
    async with AsyncSessionLocal_cost() as session:
        yield session

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getStockConfig()
DATABASE_URL_STOCK = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine_stock = create_async_engine(DATABASE_URL_STOCK, echo=True)
AsyncSessionLocal_stock = sessionmaker(bind=engine_stock, class_=AsyncSession, expire_on_commit=False)

Base_stock = declarative_base()

async def get_db_stock():
    async with AsyncSessionLocal_stock() as session:
        yield session

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getOdooConfig()
DATABASE_URL_ODOO = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine_odoo = create_async_engine(DATABASE_URL_ODOO, echo=True)
AsyncSessionLocal_odoo = sessionmaker(bind=engine_odoo, class_=AsyncSession, expire_on_commit=False)

Base_odoo = declarative_base()

async def get_db_odoo():
    async with AsyncSessionLocal_odoo() as session:
        yield session

(USERNAME, PASSWORD, HOST, DATABASE, PORT) = getStoreStockConfig()
DATABASE_URL_STORESTOCK = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
engine_storestock = create_async_engine(DATABASE_URL_STORESTOCK, echo=True)
AsyncSessionLocal_storestock = sessionmaker(bind=engine_storestock, class_=AsyncSession, expire_on_commit=False)

Base_storestock = declarative_base()

async def get_db_storestock():
    async with AsyncSessionLocal_storestock() as session:
        yield session