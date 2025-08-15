from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy import update, insert
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from typing import List, Optional

from models.storepickup import StorePickup  # 新表模型
from dependencies.permission import PermissionChecker
from schemas.storepickup import StockPickupEntry
from database import get_db_storestock, get_db_odoo

router = APIRouter(prefix="/storepickup", tags=["StoreStockPickup"])

def check_store(store, user):
    if store not in (user.store or []):
        raise HTTPException(status_code=403, detail="No permission for this store: " + store)

# 更新或插入带 pickupdate 的库存
@router.post("/pickup")
async def update_stock_pickup(
    stock_updates: List[StockPickupEntry],
    db: AsyncSession = Depends(get_db_storestock),
    user = Depends(PermissionChecker(required_roles=["storepickup:insert", "storepickup:view"]))
):
    now = datetime.now()
    for entry in stock_updates:
        # 校验 store 权限
        if entry.store:
            check_store(entry.store, user)
        store = entry.store or (user.store[0] if user.store else "")

        # 处理 pickupdate 字段
        pickupdate = entry.pickupdate or datetime.today().date()
        if isinstance(pickupdate, str):
            pickupdate = datetime.strptime(pickupdate, "%Y-%m-%d").date()

        # 尝试更新
        result = await db.execute(
            update(StorePickup)
            .where(
                StorePickup.item_code == entry.itemCode,
                StorePickup.store == store,
                StorePickup.pickupdate == pickupdate
            )
            .values(
                quantity=entry.quantity,
                update_time=now,
                modifier_id=int(user.id),
                modifier_name=user.realname
            )
            .returning(StorePickup.id)
        )
        if not result.scalar():
            # 如果没有就插入
            await db.execute(
                insert(StorePickup).values(
                    item_code=entry.itemCode,
                    store=store,
                    quantity=entry.quantity,
                    update_time=now,
                    modifier_id=int(user.id),
                    modifier_name=user.realname,
                    pickupdate=pickupdate
                )
            )

    await db.commit()
    return {"message": "Stock with pickup date updated successfully"}
