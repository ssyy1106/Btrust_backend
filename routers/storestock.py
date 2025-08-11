from fastapi import APIRouter, Query, Depends
from sqlalchemy import func, select, update, insert
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from models.storestock import StoreStock
from database import get_db_storestock
from schemas.storestock import (
    StockUpdateEntry,
    StockEntry,
    StockItem,
    StockResponse
)

router = APIRouter(prefix="/storestock", tags=["StoreStock"])

# 假设你有一个依赖获取当前用户
async def get_current_user():
    # 从 token/session 获取
    return {"id": 1, "store": ["MS"]}

# 更新库存 API
@router.post("/update-stock")
async def update_stock(
    stock_updates: List[StockUpdateEntry],
    db: AsyncSession = Depends(get_db_storestock),
    current_user: dict = Depends(get_current_user)
):
    now = datetime.now()
    for entry in stock_updates:
        store = entry.store or current_user["store"][0]
        # 先尝试更新
        result = await db.execute(
            update(StoreStock)
            .where(StoreStock.item_code == entry.itemCode, StoreStock.store == store)
            .values(
                quantity=entry.quantity,
                update_time=now,
                modifier_id=current_user["id"]
            )
            .returning(StoreStock.id)
        )
        if not result.scalar():
            # 如果没有就插入
            await db.execute(
                insert(StoreStock).values(
                    item_code=entry.itemCode,
                    store=store,
                    quantity=entry.quantity,
                    update_time=now,
                    modifier_id=current_user["id"]
                )
            )
    await db.commit()
    return {"message": "Stock updated successfully"}


# 查询库存 API
@router.get("/get-stock", response_model=StockResponse)
async def get_stock(
    store: Optional[List[str]] = Query(None, description="Store list"),
    itemCode: Optional[List[str]] = Query(None, description="ItemCode list"),
    db: AsyncSession = Depends(get_db_storestock)
):
    stmt = select(StoreStock)
    if store:
        stmt = stmt.where(StoreStock.store.in_(store))
    if itemCode:
        stmt = stmt.where(StoreStock.item_code.in_(itemCode))
    
    result = await db.execute(stmt)
    rows = result.scalars().all()

    stock_dict = defaultdict(list)
    for row in rows:
        stock_dict[row.item_code].append(
            StockEntry(
                store=row.store,
                quantity=row.quantity,
                update_time=row.update_time,
                modifier_id=row.modifier_id
            )
        )
    
    stock_entries = [
        StockItem(itemCode=code, stock=entries) for code, entries in stock_dict.items()
    ]
    return StockResponse(stockEntries=stock_entries)
