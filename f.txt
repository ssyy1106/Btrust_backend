from fastapi import APIRouter, Query, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from datetime import datetime, timedelta, timezone
from dateutil import parser
from typing import Optional, List
from collections import defaultdict
import json

from models.partner import ResPartner
from models.pickup import SaleOrder, SaleOrderLine
from models.product import ProductProduct, ProductTemplate, ProductCategory, StockQuant
from models.storestock import StoreStock
from helper import getStoreNameOdoo
from dependencies.permission import PermissionChecker
from database import get_db_odoo, get_db_storestock
from schemas.pickup import PickupItem, StoreQuantity, PickupSummaryResponse

router = APIRouter(prefix="/pickup", tags=["PickUp"])

def default_start():
    return (datetime.now().astimezone() - timedelta(days=1)).isoformat()

def default_end():
    return datetime.now().astimezone().isoformat()

@router.get("/pickup-summary", response_model=PickupSummaryResponse)
async def get_pickup_summary(
    start_date: Optional[str] = Query(default_factory=default_start, description="起始日期 ISO8601 带时区"),
    end_date: Optional[str] = Query(default_factory=default_end, description="结束日期 ISO8601 带时区"),
    shift_hour: int = Query(16, ge=0, le=23, description="班次开始小时"),
    categoryIds: Optional[List[int]] = Query(None, description="按分类 ID 过滤，多值用逗号分隔"),
    order: bool = Query(True, description="是否只筛选有订单的产品"),
    db_odoo: AsyncSession = Depends(get_db_odoo),
    db_storestock: AsyncSession = Depends(get_db_storestock),
    user = Depends(PermissionChecker(required_roles=["pickup:search", "pickup:view"]))
):
    start_dt_local = parser.isoparse(start_date) + timedelta(hours=shift_hour)
    end_dt_local = parser.isoparse(end_date) + timedelta(days=1, hours=shift_hour - 24)
    start_dt_utc = start_dt_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_dt_utc = end_dt_local.astimezone(timezone.utc).replace(tzinfo=None)

    # 父级 partner 别名
    ParentPartner = aliased(ResPartner)

    # 总库存子查询
    stock_subq = (
        select(
            StockQuant.product_id,
            func.sum(StockQuant.quantity).label("total_stock")
        )
        .group_by(StockQuant.product_id)
        .subquery()
    )

    # 订单子查询：按 product_id + partner_id 聚合数量
    order_subq = (
        select(
            SaleOrderLine.product_id,
            ResPartner.id.label("partner_id"),
            ResPartner.name.label("partner_name"),
            ParentPartner.name.label("parent_partner_name"),
            func.sum(SaleOrderLine.product_uom_qty).label("order_quantity")
        )
        .join(SaleOrder, SaleOrderLine.order_id == SaleOrder.id)
        .join(ResPartner, SaleOrder.partner_id == ResPartner.id)
        .outerjoin(ParentPartner, ResPartner.parent_id == ParentPartner.id)
        .where(SaleOrder.state == 'sale')
        .where(SaleOrder.date_order >= start_dt_utc)
        .where(SaleOrder.date_order < end_dt_utc)
        .group_by(SaleOrderLine.product_id, ResPartner.id, ResPartner.name, ParentPartner.name)
        .subquery()
    )

    # 主查询
    stmt = (
        select(
            ProductProduct.id,
            ProductProduct.default_code,
            ProductTemplate.name.label("product_name"),
            ProductTemplate.categ_id,
            ProductCategory.name.label("category_name"),
            func.coalesce(stock_subq.c.total_stock, 0).label("total_stock"),
            order_subq.c.partner_name,
            order_subq.c.parent_partner_name,
            func.coalesce(order_subq.c.order_quantity, 0).label("order_quantity")
        )
        .join(ProductTemplate, ProductProduct.product_tmpl_id == ProductTemplate.id)
        .join(ProductCategory, ProductTemplate.categ_id == ProductCategory.id)
        .outerjoin(stock_subq, stock_subq.c.product_id == ProductProduct.id)
        .outerjoin(order_subq, order_subq.c.product_id == ProductProduct.id)
        .where(ProductTemplate.type != 'service')
        .where(ProductProduct.default_code.isnot(None))
    )

    if categoryIds:
        stmt = stmt.where(ProductTemplate.categ_id.in_(categoryIds))

    if order:
        stmt = stmt.where(order_subq.c.order_quantity.isnot(None))
    else:
        stmt = stmt.where(func.coalesce(order_subq.c.order_quantity, 0) == 0)
        stmt = stmt.where(stock_subq.c.total_stock > 0)

    result = await db_odoo.execute(stmt)
    rows = result.all()

    # 获取所有 item_codes
    item_codes = list({r.default_code for r in rows if r.default_code})

    # 查询 storestock
    storestock_rows = await db_storestock.execute(
        select(StoreStock).where(StoreStock.item_code.in_(item_codes))
    )
    storestock_list = storestock_rows.scalars().all()

    # 按 product 构建 orders 和 storeStock
    pickup_dict = defaultdict(list)
    orders_dict = defaultdict(lambda: defaultdict(int))  # {item_code: {store: quantity}}

    for r in rows:
        if not r.default_code:
            continue
        pickup_dict[r.default_code].append(r)
        store_names = [n for n in [r.partner_name, r.parent_partner_name] if n]
        store_code = getStoreNameOdoo(store_names)
        orders_dict[r.default_code][store_code] += int(r.order_quantity or 0)

    pickup_items = []
    for item_code, product_rows in pickup_dict.items():
        raw_name = product_rows[0].product_name
        if isinstance(raw_name, str):
            try:
                parsed = json.loads(raw_name)
                name_dict = parsed if isinstance(parsed, dict) else {"en_US": raw_name}
            except json.JSONDecodeError:
                name_dict = {"en_US": raw_name}
        elif isinstance(raw_name, dict):
            name_dict = raw_name
        else:
            name_dict = {"en_US": str(raw_name)}

        orders_list = [{"store": store, "quantity": qty} for store, qty in orders_dict[item_code].items()]

        store_stock_entries = [
            {
                "store": s.store,
                "quantity": s.quantity,
                "modifierName": s.modifier_name,
                "updateTime": s.update_time.isoformat() if s.update_time else None
            }
            for s in storestock_list if s.item_code == item_code
        ]

        pickup_items.append(
            PickupItem(
                itemCode=item_code,
                name=name_dict,
                orders=orders_list,
                stockAtHQ=int(product_rows[0].total_stock or 0),
                categoryName=product_rows[0].category_name,
                storeStock=store_stock_entries
            )
        )

    return PickupSummaryResponse(pickupItems=pickup_items)
