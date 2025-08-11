import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from models.stock import Base_stock
from models.invoice import Base_invoice
from models.cost import Base_cost
from database import DATABASE_URL_STOCK, DATABASE_URL_INVOICE, DATABASE_URL_COST

async def init_db():
    engine = create_async_engine(DATABASE_URL_STOCK, echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base_stock.metadata.create_all)
    # engine2 = create_async_engine(DATABASE_URL_INVOICE, echo=True)
    # async with engine2.begin() as conn:
    #     await conn.run_sync(Base_invoice.metadata.create_all)
    # engine3 = create_async_engine(DATABASE_URL_COST, echo=True)
    # async with engine3.begin() as conn:
    #     await conn.run_sync(Base_cost.metadata.create_all)

