from models.stock import Base_stock
from models.storestock import Base_storestock
from database import get_engine_storestock, get_engine_stock


async def init_db():
    engine_stock = get_engine_stock()
    if engine_stock is None:
        raise RuntimeError("engine_stock is not initialized. Call init_database() before init_db().")
    engine_storestock = get_engine_storestock()
    if engine_storestock is None:
        raise RuntimeError("engine_storestock is not initialized. Call init_database() before init_db().")

    async with engine_stock.begin() as conn:
        await conn.run_sync(Base_stock.metadata.create_all)
    async with engine_storestock.begin() as conn:
        await conn.run_sync(Base_storestock.metadata.create_all)
    # engine2 = create_async_engine(DATABASE_URL_INVOICE, echo=True)
    # async with engine2.begin() as conn:
    #     await conn.run_sync(Base_invoice.metadata.create_all)
    # engine3 = create_async_engine(DATABASE_URL_COST, echo=True)
    # async with engine3.begin() as conn:
    #     await conn.run_sync(Base_cost.metadata.create_all)

