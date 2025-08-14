import json
from fastapi import APIRouter, Query, Depends
from sqlalchemy import select, func, or_
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from dependencies.permission import PermissionChecker
from database import get_db_odoo
from models.product import ProductProduct, ProductTemplate, ProductCategory, StockQuant
from models.pickup import SaleOrder, SaleOrderLine
from schemas.product import ProductListResponse, ProductCategoryResponse

router = APIRouter(prefix="/product", tags=["Product"])

@router.get("/", summary="获取过去几天下过订单或有库存无订单的产品信息", response_model=ProductListResponse)
async def get_products(
    days: Optional[int] = Query(7, description="过去几天的订单，默认7天"),
    categoryId: Optional[int] = Query(None, description="按分类 ID 过滤"),
    noorder: Optional[bool] = Query(False, description="是否返回有库存但无订单的商品"),
    db: AsyncSession = Depends(get_db_odoo)
):
    # 计算起始时间
    start_dt = datetime.now() - timedelta(days=days)

    # 分类筛选条件
    if categoryId:
        category_filter = ProductTemplate.categ_id == categoryId
    else:
        category_filter = or_(
            ProductCategory.name.ilike('%fruit%'),
            ProductCategory.name.ilike('%veg%')
        )

    if noorder:
        # 子查询：过去 days 天有订单的 product_id
        subq_orders = (
            select(SaleOrderLine.product_id)
            .join(SaleOrder, SaleOrder.id == SaleOrderLine.order_id)
            .where(SaleOrder.date_order >= start_dt)
            .where(SaleOrder.state == 'sale')
            .distinct()
        )

        # 主查询：有库存且不在子查询里的产品
        stmt = (
            select(
                ProductProduct.id,
                ProductProduct.default_code,
                ProductProduct.barcode,
                ProductTemplate.name,
                ProductTemplate.categ_id,
                ProductCategory.name.label("category_name"),
                func.sum(StockQuant.quantity).label("stock_qty")
            )
            .join(ProductTemplate, ProductProduct.product_tmpl_id == ProductTemplate.id)
            .join(ProductCategory, ProductTemplate.categ_id == ProductCategory.id, isouter=True)
            .join(StockQuant, StockQuant.product_id == ProductProduct.id)
            .where(StockQuant.quantity > 0)
            .where(~ProductProduct.id.in_(subq_orders))  # 排除有订单的
            .where(category_filter)
            .group_by(
                ProductProduct.id, ProductProduct.default_code, ProductProduct.barcode,
                ProductTemplate.name, ProductTemplate.categ_id, ProductCategory.name
            )
            .order_by(func.sum(StockQuant.quantity).desc())
        )
    else:
        # 原逻辑：过去 days 天内有订单的商品
        stmt = (
            select(
                ProductProduct.id,
                ProductProduct.default_code,
                ProductProduct.barcode,
                ProductTemplate.name,
                ProductTemplate.categ_id,
                ProductCategory.name.label("category_name"),
                func.count(SaleOrderLine.id).label("order_count")
            )
            .join(ProductTemplate, ProductProduct.product_tmpl_id == ProductTemplate.id)
            .join(ProductCategory, ProductTemplate.categ_id == ProductCategory.id, isouter=True)
            .join(SaleOrderLine, SaleOrderLine.product_id == ProductProduct.id)
            .join(SaleOrder, SaleOrder.id == SaleOrderLine.order_id)
            .where(SaleOrder.date_order >= start_dt)
            .where(SaleOrder.state == 'sale')
            .where(category_filter)
            .group_by(
                ProductProduct.id, ProductProduct.default_code, ProductProduct.barcode,
                ProductTemplate.name, ProductTemplate.categ_id, ProductCategory.name
            )
            .order_by(func.count(SaleOrderLine.id).desc())
        )

    result = await db.execute(stmt)
    rows = result.all()

    products = []
    for r in rows:
        # 处理 name 字段
        if isinstance(r.name, str):
            try:
                parsed = json.loads(r.name)
                name_dict = parsed if isinstance(parsed, dict) else {"en_US": r.name}
            except json.JSONDecodeError:
                name_dict = {"en_US": r.name}
        elif isinstance(r.name, dict):
            name_dict = r.name
        else:
            name_dict = {"en_US": str(r.name)}

        products.append({
            "id": r.id,
            "itemCode": r.default_code,
            "name": name_dict,
            "barcode": r.barcode,
            "categoryId": r.categ_id,
            "categoryName": r.category_name,
            "orderCount": getattr(r, "order_count", None),
            "stockQty": getattr(r, "stock_qty", None)
        })

    return {"products": products}


@router.get("/category", summary="获取产品分类信息", response_model=ProductCategoryResponse)
async def get_product_categories(
    db: AsyncSession = Depends(get_db_odoo)
    # user = Depends(PermissionChecker(required_roles=["product:category:view"]))
):
    stmt = select(ProductCategory.id, ProductCategory.name, ProductCategory.parent_id)
    result = await db.execute(stmt)
    rows = result.all()

    parent_ids = {r.parent_id for r in rows if r.parent_id}
    parent_map = {}
    if parent_ids:
        parent_stmt = select(ProductCategory.id, ProductCategory.name).where(ProductCategory.id.in_(parent_ids))
        parent_rows = await db.execute(parent_stmt)
        parent_map = {pid: pname for pid, pname in parent_rows}

    categories = [
        {
            "id": r.id,
            "name": r.name,
            "parent_id": r.parent_id,
            "parent_name": parent_map.get(r.parent_id)
        }
        for r in rows
    ]

    return {"categories": categories}
