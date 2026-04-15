from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import declarative_base
from helper import getInvoiceConfig, getCostConfig, getStockConfig, getOdooConfig, getStoreStockConfig, getStoreDBConfig, getLocalStore
from typing import Optional
from contextlib import asynccontextmanager


Base_store_sqlserver = declarative_base()

# 缓存各 store 的 sessionmaker
store_sessions = {}

def get_db_store_sqlserver_factory(store: str):
    """
    根据 store 动态生成 AsyncSession 依赖
    """
    if store not in store_sessions:
        # 获取本地 driver
        _, DRIVER = getLocalStore()
        # 获取数据库配置
        USERNAME, PASSWORD, HOST, DATABASE = getStoreDBConfig(store)

        # 构造连接字符串
        DATABASE_URL_SQLSERVER = (
            f"mssql+aioodbc://{USERNAME}:{PASSWORD}@{HOST}/{DATABASE}"
            f"?driver={DRIVER.replace(' ', '+')}"
        )

        # 创建 engine + sessionmaker
        engine_sqlserver = create_async_engine(
            DATABASE_URL_SQLSERVER,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
            pool_timeout=30,
            future=True
        )
        AsyncSessionLocal_sqlserver = async_sessionmaker(
            bind=engine_sqlserver, class_=AsyncSession, expire_on_commit=False
        )

        store_sessions[store] = AsyncSessionLocal_sqlserver

    # 实际的依赖函数
    @asynccontextmanager
    async def _get_db():
        async with store_sessions[store]() as session:
            try:
                yield session
            finally:
                await session.close()

    return _get_db

engine_cost: Optional[AsyncEngine] = None
AsyncSessionLocal_cost: Optional[async_sessionmaker] = None
Base_cost = declarative_base()

engine: Optional[AsyncEngine] = None
AsyncSessionLocal: Optional[async_sessionmaker] = None
Base_invoice = declarative_base()

engine_stock: Optional[AsyncEngine] = None
AsyncSessionLocal_stock: Optional[async_sessionmaker] = None
Base_stock = declarative_base()

engine_odoo: Optional[AsyncEngine] = None
AsyncSessionLocal_odoo: Optional[async_sessionmaker] = None
Base_odoo = declarative_base()

engine_storestock: Optional[AsyncEngine] = None
AsyncSessionLocal_storestock: Optional[async_sessionmaker] = None
Base_storestock = declarative_base()

def get_engine_storestock() -> Optional[AsyncEngine]:
    return engine_storestock

def get_engine_stock() -> Optional[AsyncEngine]:
    return engine_stock

def _require_sessionmaker(session_maker: Optional[async_sessionmaker], name: str) -> async_sessionmaker:
    if session_maker is None:
        raise RuntimeError(f"{name} is not initialized. Call init_database() during app startup.")
    return session_maker

def init_database(echo: bool = False):
    global engine_cost, AsyncSessionLocal_cost, engine, AsyncSessionLocal, engine_stock, AsyncSessionLocal_stock
    global engine_odoo, AsyncSessionLocal_odoo, engine_storestock, AsyncSessionLocal_storestock

    (USERNAME, PASSWORD, HOST, DATABASE, PORT) = getCostConfig()
    DATABASE_URL_COST = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
    engine_cost = create_async_engine(
        DATABASE_URL_COST,
        echo=echo,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        pool_timeout=30,
        future=True
    )
    AsyncSessionLocal_cost = async_sessionmaker(
        bind=engine_cost,
        class_=AsyncSession,
        expire_on_commit=False
    )

    (USERNAME, PASSWORD, HOST, DATABASE, PORT) = getInvoiceConfig()
    DATABASE_URL_INVOICE = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
    engine = create_async_engine(
        DATABASE_URL_INVOICE,
        echo=echo,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        pool_timeout=30,
        future=True
    )
    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    (USERNAME, PASSWORD, HOST, DATABASE, PORT) = getStockConfig()
    DATABASE_URL_STOCK = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
    engine_stock = create_async_engine(
        DATABASE_URL_STOCK, 
        echo=echo,
        pool_size=10,           # 连接池大小
        max_overflow=20,        # 超过 pool_size 时允许的额外连接
        pool_recycle=1800,      # 每 30 分钟回收一次连接，防止 timeout
        pool_timeout=30,        # 等待连接的超时时间
        future=True)
    AsyncSessionLocal_stock = async_sessionmaker(bind=engine_stock, class_=AsyncSession, expire_on_commit=False)

    (USERNAME, PASSWORD, HOST, DATABASE, PORT) = getOdooConfig()
    DATABASE_URL_ODOO = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
    engine_odoo = create_async_engine(
        DATABASE_URL_ODOO, 
        echo=echo,
        pool_size=10,           # 连接池大小
        max_overflow=20,        # 超过 pool_size 时允许的额外连接
        pool_recycle=1800,      # 每 30 分钟回收一次连接，防止 timeout
        pool_timeout=30,        # 等待连接的超时时间
        future=True)
    AsyncSessionLocal_odoo = async_sessionmaker(bind=engine_odoo, class_=AsyncSession, expire_on_commit=False)

    (USERNAME, PASSWORD, HOST, DATABASE, PORT) = getStoreStockConfig()
    DATABASE_URL_STORESTOCK = f"postgresql+asyncpg://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
    engine_storestock = create_async_engine(
        DATABASE_URL_STORESTOCK, 
        echo=echo,
        pool_size=10,           # 连接池大小
        max_overflow=20,        # 超过 pool_size 时允许的额外连接
        pool_recycle=1800,      # 每 30 分钟回收一次连接，防止 timeout
        pool_timeout=30,        # 等待连接的超时时间
        future=True)
    AsyncSessionLocal_storestock = async_sessionmaker(bind=engine_storestock, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    session_maker = _require_sessionmaker(AsyncSessionLocal, "AsyncSessionLocal")
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_db_cost():
    session_maker = _require_sessionmaker(AsyncSessionLocal_cost, "AsyncSessionLocal_cost")
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

@asynccontextmanager
async def get_db_stock():
    session_maker = _require_sessionmaker(AsyncSessionLocal_stock, "AsyncSessionLocal_stock")
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_db_odoo():
    session_maker = _require_sessionmaker(AsyncSessionLocal_odoo, "AsyncSessionLocal_odoo")
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

async def get_db_storestock():
    session_maker = _require_sessionmaker(AsyncSessionLocal_storestock, "AsyncSessionLocal_storestock")
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
