from fastapi import APIRouter, Query, Depends
from sqlalchemy import func, select, update, insert
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.partner import ResPartner
from helper import getStoreNameOdoo
from dependencies.permission import PermissionChecker
from models.pickup import SaleOrder, SaleOrderLine
from models.user import ResCompany
from models.product import ProductProduct
from models.user import ResUsers
from database import get_db_odoo
from schemas.pickup import (
    StoreQuantity,
    PickupItem,
    PickupSummaryResponse
)

router = APIRouter(prefix="/pickup", tags=["PickUp"])

def default_start():
    return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

def default_end():
    return datetime.now().strftime('%Y-%m-%d')

@router.get("/pickup-summary", response_model=PickupSummaryResponse)
async def get_pickup_summary(
    start_date: Optional[str] = Query(default_factory=default_start, description="起始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(default_factory=default_end, description="结束日期 YYYY-MM-DD"),
    shift_hour: int = Query(16, ge=0, le=23, description="班次开始小时"),
    db: AsyncSession = Depends(get_db_odoo),
    user = Depends(PermissionChecker(required_roles=["pickup:search", "pickup:view"]))
):
    # 需要增加user的store筛选，但是现在bos系统和登录系统的store名称不同，暂时不加处理
    # 计算时间范围
    start_dt = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(hours=shift_hour)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1, hours=shift_hour - 24)

    # 给父级 partner 创建别名
    ParentPartner = aliased(ResPartner)

    stmt = (
        select(
            ProductProduct.default_code,
            ResPartner.name.label("partner_name"),
            ParentPartner.name.label("parent_partner_name"),
            func.sum(SaleOrderLine.product_uom_qty).label("total_quantity")
        )
        .join(SaleOrder, SaleOrderLine.order_id == SaleOrder.id)
        .join(ProductProduct, SaleOrderLine.product_id == ProductProduct.id)
        .join(ResPartner, SaleOrder.partner_id == ResPartner.id)          # 直接关联订单partner
        .outerjoin(ParentPartner, ResPartner.parent_id == ParentPartner.id)
        .where(SaleOrder.date_order >= start_dt)
        .where(SaleOrder.date_order < end_dt)
        .where(SaleOrder.state == 'sale')
        .where(ProductProduct.default_code.isnot(None))
        .group_by(ProductProduct.default_code, ResPartner.name, ParentPartner.name)
    )

    result = await db.execute(stmt)
    rows = result.all()

    pickup_dict = defaultdict(list)
    for default_code, partner_name, parent_name, qty in rows:
        if default_code is None:
            continue
        store_names = [n for n in [partner_name, parent_name] if n]
        pickup_dict[default_code].append(
            StoreQuantity(
                store=getStoreNameOdoo(store_names),
                quantity=int(qty)
            )
        )

    pickup_items = [
        PickupItem(itemCode=code, orders=orders) for code, orders in pickup_dict.items()
    ]
    return PickupSummaryResponse(pickupItems=pickup_items)
