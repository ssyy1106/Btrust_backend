from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy import update, insert, select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from sqlalchemy.orm import aliased
from typing import List, Optional, Dict
from collections import defaultdict
import json
from dateutil import parser

from models.pickup import SaleOrder, SaleOrderLine
from models.storepickup import StorePickup  # 新表模型
from dependencies.permission import PermissionChecker
from schemas.storepickup import StockPickupEntry, StorePickupEntry, PickupItem, PickupStockResponse
from models.product import ProductProduct, ProductTemplate, ProductCategory
from models.partner import ResPartner
from database import get_db_storestock, get_db_odoo
from helper import getStoreNameOdoo, ensure_aware, to_utc_naive, LOCAL_TZ  # 假设有获取子孙分类函数

router = APIRouter(prefix="/storepickup", tags=["StoreStockPickup"])

def check_store(store, user):
    return
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

def default_start():
    return (datetime.now().astimezone() - timedelta(days=1)).isoformat()

def default_end():
    return datetime.now().astimezone().isoformat()

@router.get("/pickup", response_model=PickupStockResponse)
async def get_storepickup(
    start_date: Optional[str] = Query(default_factory=default_start, description="起始日期 ISO8601 带时区"),
    end_date: Optional[str] = Query(default_factory=default_end, description="结束日期 ISO8601 带时区"),
    shift_hour: int = Query(16, ge=0, le=23, description="班次开始小时"),
    categoryIds: Optional[List[int]] = Query(None, description="按分类 ID 过滤，多值用逗号分隔，自动包含子孙分类"),
    order: bool = Query(True, description="是否只筛选有订单的产品"),
    db_odoo: AsyncSession = Depends(get_db_odoo),
    db_storestock: AsyncSession = Depends(get_db_storestock),
    user = Depends(PermissionChecker(required_roles=["pickup:search", "pickup:view"]))
):
    # ---------- 1. 计算班次时间 ----------
    start_dt_local = ensure_aware(parser.isoparse(start_date), LOCAL_TZ) + timedelta(hours=shift_hour)
    end_dt_local = ensure_aware(parser.isoparse(end_date), LOCAL_TZ) + timedelta(days=1, hours=shift_hour - 24)
    start_dt_utc = to_utc_naive(start_dt_local)
    end_dt_utc = to_utc_naive(end_dt_local)

    ParentPartner = aliased(ResPartner)

    # ---------- 2. 总订单子查询 ----------
    order_subq = (
        select(
            SaleOrderLine.product_id,
            func.sum(SaleOrderLine.product_uom_qty).label("order_quantity")
        )
        .join(SaleOrder, SaleOrderLine.order_id == SaleOrder.id)
        .where(SaleOrder.state == 'sale')
        .where(SaleOrder.date_order >= start_dt_utc)
        .where(SaleOrder.date_order < end_dt_utc)
        .group_by(SaleOrderLine.product_id)
        .subquery()
    )

    # ---------- 3. 主商品查询 ----------
    stmt = (
        select(
            ProductProduct.id,
            ProductProduct.default_code,
            ProductTemplate.categ_id
        )
        .join(ProductTemplate, ProductProduct.product_tmpl_id == ProductTemplate.id)
        .where(ProductTemplate.type != 'service')
        .where(ProductProduct.default_code.isnot(None))
        .outerjoin(order_subq, order_subq.c.product_id == ProductProduct.id)
    )

    # --- 递归查询 categoryIds 的子孙分类 ---
    if categoryIds:
        Category = ProductCategory
        base_cte = select(Category.id, Category.parent_id).where(Category.id.in_(categoryIds)).cte(name="category_cte", recursive=True)
        category_alias = aliased(base_cte)
        category_child = aliased(Category)
        recursive_cte = base_cte.union_all(
            select(category_child.id, category_child.parent_id)
            .where(category_child.parent_id == category_alias.c.id)
        )
        all_cat_result = await db_odoo.execute(select(recursive_cte.c.id))
        all_category_ids = [row[0] for row in all_cat_result.all()]
        stmt = stmt.where(ProductTemplate.categ_id.in_(all_category_ids))

    # ---------- 订单过滤 ----------
    if order:
        stmt = stmt.where(order_subq.c.order_quantity.isnot(None))
    else:
        stmt = stmt.where(order_subq.c.order_quantity.is_(None))

    result = await db_odoo.execute(stmt)
    rows = result.all()

    # ---------- 4. 获取 item_codes ----------
    item_codes = [r.default_code for r in rows if r.default_code]

    # ---------- 5. 查询 store pickup 表 ----------
    storepickup_rows = await db_storestock.execute(
        select(StorePickup).where(
            StorePickup.item_code.in_(item_codes),
            StorePickup.pickupdate == parser.isoparse(end_date).date()
        )
    )
    storepickup_list = storepickup_rows.scalars().all()

    # ---------- 6. 构建返回 ----------
    pickup_dict = defaultdict(list)
    for s in storepickup_list:
        pickup_dict[s.item_code].append(
            StorePickupEntry(
                store=s.store,
                quantity=s.quantity,
                modifierName=s.modifier_name,
                updateTime=s.update_time.isoformat() if s.update_time else None
            )
        )

    pickup_items = [
        PickupItem(itemCode=code, storePickup=stocks)
        for code, stocks in pickup_dict.items()
    ]

    return PickupStockResponse(pickupItems=pickup_items)
