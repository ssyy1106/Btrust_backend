from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy import func, select, update, insert
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
import json
from sqlalchemy.orm import aliased

from models.partner import ResPartner
from dependencies.permission import PermissionChecker
from models.storestock import StoreStock
from models.pickup import SaleOrder, SaleOrderLine
from models.product import ProductProduct, ProductTemplate
from database import get_db_storestock, get_db_odoo
from helper import getStoreNameOdoo
from schemas.storestock import (
    StockUpdateEntry,
    StockEntry,
    StockItem,
    StockResponse
)

router = APIRouter(prefix="/storestock", tags=["StoreStock"])

def check_store(store, user):
    # 判断store参数是否正确
    if store not in (user.store or []):
        raise HTTPException(status_code=403, detail="No permission for this store: "+ store)

# 更新库存 API
@router.post("/update-stock")
async def update_stock(
    stock_updates: List[StockUpdateEntry],
    db: AsyncSession = Depends(get_db_storestock),
    user = Depends(PermissionChecker(required_roles=["storestock:insert", "storestock:view"]))
    #current_user: dict = Depends(get_current_user)
):
    now = datetime.now()
    for entry in stock_updates:
        if entry.store:
            check_store(entry.store, user)
        store = entry.store or (user.store[0] if user.store else "")
        # 先尝试更新
        result = await db.execute(
            update(StoreStock)
            .where(StoreStock.item_code == entry.itemCode, StoreStock.store == store)
            .values(
                quantity=entry.quantity,
                update_time=now,
                modifier_id=int(user.id),
                modifier_name=user.realname
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
                    modifier_id=int(user.id),
                    modifier_name=user.realname
                )
            )
    await db.commit()
    return {"message": "Stock updated successfully"}

def parse_product_name(raw_name) -> Dict[str, str]:
    """统一解析产品名称，返回 {lang_code: name_str} 格式"""
    if isinstance(raw_name, str):
        try:
            parsed = json.loads(raw_name)
            if isinstance(parsed, dict):
                return parsed
            else:
                return {"en_US": raw_name}
        except json.JSONDecodeError:
            return {"en_US": raw_name}
    elif isinstance(raw_name, dict):
        return raw_name
    else:
        return {"en_US": str(raw_name)}
    
# 查询库存 API
@router.get("/get-stock", response_model=StockResponse)
async def get_stock(
    store: List[str] = Query(..., description="Store list"),  # 必须传参
    days: int = Query(7, description="Days to look back for orders"),
    db_store: AsyncSession = Depends(get_db_storestock),
    db_odoo: AsyncSession = Depends(get_db_odoo),
    user = Depends(PermissionChecker(required_roles=["storestock:search", "storestock:view"]))
):
    # 检查权限
    for s in store:
        check_store(s, user)

    # 计算时间范围
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)

    # 1️⃣ 从 Odoo 获取最近 days 天有订单的 item_code + 店铺
    ParentPartner = aliased(ResPartner)

    stmt_order = (
        select(
            ProductProduct.default_code.label("item_code"),
            ResPartner.name.label("partner_name"),
            ParentPartner.name.label("parent_partner_name"),
            ProductTemplate.name.label("product_name"),
            func.max(SaleOrder.date_order).label("last_order_date")
        )
        .select_from(SaleOrderLine)  # 固定起点，避免 join 歧义
        .join(SaleOrder, SaleOrderLine.order_id == SaleOrder.id)
        .join(ProductProduct, SaleOrderLine.product_id == ProductProduct.id)
        .join(ProductTemplate, ProductProduct.product_tmpl_id == ProductTemplate.id)
        .join(ResPartner, SaleOrder.partner_id == ResPartner.id)
        .outerjoin(ParentPartner, ResPartner.parent_id == ParentPartner.id)
        .where(SaleOrder.state == 'sale')
        .where(SaleOrder.date_order >= start_dt)
        .where(SaleOrder.date_order < end_dt)
        .group_by(ProductProduct.default_code, ResPartner.name, ParentPartner.name, ProductTemplate.name)
    )

    order_result = await db_odoo.execute(stmt_order)
    order_rows = order_result.all()

    # 组织 Odoo 订单数据
    order_map: Dict[str, Dict[str, Dict]] = defaultdict(dict)  
    # {item_code: {store_code: {name, last_order_date}}}
    for row in order_rows:
        store_code = getStoreNameOdoo([row.partner_name, row.parent_partner_name])
        if store_code in store:  # 只保留查询的 store
            order_map[row.item_code][store_code] = {
                "name": parse_product_name(row.product_name),
                "last_order_date": row.last_order_date
            }

    # 2️⃣ 从 storestock 查库存
    stmt_stock = select(StoreStock).where(StoreStock.store.in_(store))
    result_stock = await db_store.execute(stmt_stock)
    stock_rows = result_stock.scalars().all()

    stock_map = defaultdict(dict)  # {item_code: {store: StockEntry}}
    for r in stock_rows:
        stock_map[r.item_code][r.store] = StockEntry(
            store=r.store,
            quantity=r.quantity,
            update_time=r.update_time,
            modifier_id=r.modifier_id,
            modifier_name=r.modifier_name
        )

    # 3️⃣ 合并数据：订单里有的 (item_code, store) 必须有返回
    stock_items = []
    for item_code, store_data in order_map.items():
        stock_list = []
        name = None
        for s in store:
            if s in store_data:
                name = store_data[s]["name"]
                last_order_date = store_data[s]["last_order_date"]
            else:
                last_order_date = None

            entry = stock_map.get(item_code, {}).get(
                s,
                StockEntry(
                    store=s,
                    quantity=0,
                    update_time=None,
                    modifier_id=None,
                    modifier_name=None
                )
            )
            # 给库存 entry 增加 last_order_date
            entry_dict = entry.dict()
            entry_dict["last_order_date"] = last_order_date
            stock_list.append(StockEntry(**entry_dict))

        stock_items.append(
            StockItem(
                itemCode=item_code,
                name=name,
                stock=stock_list
            )
        )

    return StockResponse(stockEntries=stock_items)
