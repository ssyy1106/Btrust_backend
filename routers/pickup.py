from fastapi import APIRouter, Query, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional
from dateutil import parser

from models.partner import ResPartner
from models.pickup import SaleOrder, SaleOrderLine
from models.product import ProductProduct, ProductTemplate, ProductCategory, StockQuant
from models.user import ResUsers
from helper import getStoreNameOdoo
from dependencies.permission import PermissionChecker
from database import get_db_odoo
from schemas.pickup import PickupItem, StoreQuantity, PickupSummaryResponse

router = APIRouter(prefix="/pickup", tags=["PickUp"])

# 默认值函数：返回 ISO8601 带本地时区
def default_start():
    return (datetime.now().astimezone() - timedelta(days=1)).isoformat()

def default_end():
    return datetime.now().astimezone().isoformat()

@router.get("/pickup-summary", response_model=PickupSummaryResponse)
async def get_pickup_summary(
    start_date: Optional[str] = Query(default_factory=default_start, description="起始日期 ISO8601 带时区"),
    end_date: Optional[str] = Query(default_factory=default_end, description="结束日期 ISO8601 带时区"),
    shift_hour: int = Query(16, ge=0, le=23, description="班次开始小时"),
    categoryIds: Optional[list[int]] = Query(None, description="按分类 ID 过滤，多值用逗号分隔"),
    db: AsyncSession = Depends(get_db_odoo),
    user = Depends(PermissionChecker(required_roles=["pickup:search", "pickup:view"]))
):
    # 解析带时区时间并加 shift_hour
    start_dt_local = parser.isoparse(start_date) + timedelta(hours=shift_hour)
    end_dt_local = parser.isoparse(end_date) + timedelta(days=1, hours=shift_hour - 24)

    # 转换为 UTC naive，和 Odoo date_order 对齐
    start_dt_utc = start_dt_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_dt_utc = end_dt_local.astimezone(timezone.utc).replace(tzinfo=None)

    # 父级 partner 别名
    ParentPartner = aliased(ResPartner)

    # 子查询：每个 product 的总库存
    stock_subq = (
        select(
            StockQuant.product_id,
            func.sum(StockQuant.quantity).label("total_stock")
        )
        .group_by(StockQuant.product_id)
        .subquery()
    )

    stmt = (
        select(
            ProductProduct.default_code,
            ProductTemplate.name.label("product_name"),
            ProductCategory.name.label("category_name"),
            ResPartner.name.label("partner_name"),
            ParentPartner.name.label("parent_partner_name"),
            func.sum(SaleOrderLine.product_uom_qty).label("total_quantity"),
            stock_subq.c.total_stock
        )
        .join(SaleOrder, SaleOrderLine.order_id == SaleOrder.id)
        .join(ProductProduct, SaleOrderLine.product_id == ProductProduct.id)
        .join(ProductTemplate, ProductProduct.product_tmpl_id == ProductTemplate.id)
        .join(ProductCategory, ProductTemplate.categ_id == ProductCategory.id)
        .join(ResPartner, SaleOrder.partner_id == ResPartner.id)
        .outerjoin(ParentPartner, ResPartner.parent_id == ParentPartner.id)
        .outerjoin(stock_subq, stock_subq.c.product_id == ProductProduct.id)
        .where(ProductTemplate.type != 'service')
        .where(SaleOrder.date_order >= start_dt_utc)
        .where(SaleOrder.date_order < end_dt_utc)
        .where(SaleOrder.state == 'sale')
        .where(ProductProduct.default_code.isnot(None))
    )

    # 分类过滤
    if categoryIds:
        stmt = stmt.where(ProductTemplate.categ_id.in_(categoryIds))

    stmt = stmt.group_by(
        ProductProduct.default_code,
        ProductTemplate.name,
        ProductCategory.name,
        ResPartner.name,
        ParentPartner.name,
        stock_subq.c.total_stock
    )

    result = await db.execute(stmt)
    rows = result.all()

    # 按商品汇总每个门店
    pickup_dict = defaultdict(list)
    for default_code, product_name, category_name, partner_name, parent_name, qty, total_stock in rows:
        if default_code is None:
            continue
        store_names = [n for n in [partner_name, parent_name] if n]
        pickup_dict[default_code].append(
            StoreQuantity(
                store=getStoreNameOdoo(store_names),
                quantity=int(qty)
            )
        )

    # 构建返回对象
    pickup_items = [
        PickupItem(
            itemCode=code,
            orders=orders,
            totalStock=int(next((r[6] for r in rows if r[0] == code and r[6] is not None), 0)),
            categoryName=next((r[2] for r in rows if r[0] == code), None)
        )
        for code, orders in pickup_dict.items()
    ]

    return PickupSummaryResponse(pickupItems=pickup_items)
