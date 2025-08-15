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

@router.get("", summary="获取过去几天下过订单或有库存无订单的产品信息", response_model=ProductListResponse)
async def get_products(
    days: Optional[int] = Query(7, description="过去几天的订单，默认7天，-1表示不限时间"),
    categoryIds: Optional[List[int]] = Query(None, description="按分类 ID 过滤，可传多个，-1表示全部分类，不传表示fruit/veg"),
    noorder: Optional[bool] = Query(False, description="是否返回有库存但无订单的商品"),
    limit: int = Query(50, ge=1, le=500, description="每页条数，默认50，最大500"),
    offset: int = Query(0, ge=0, description="偏移量，用于分页"),
    db: AsyncSession = Depends(get_db_odoo)
):
    # 时间过滤
    if days is not None and days != -1:
        start_dt = datetime.now() - timedelta(days=days)
    else:
        start_dt = None

    # 分类过滤
    if categoryIds is None:
        category_filter = or_(
            ProductCategory.name.ilike('%fruit%'),
            ProductCategory.name.ilike('%veg%')
        )
    elif -1 in categoryIds:
        category_filter = None
    else:
        category_filter = ProductTemplate.categ_id.in_(categoryIds)

    # 子查询：库存
    stock_subq = (
        select(
            StockQuant.product_id.label("pid"),
            func.sum(StockQuant.quantity).label("stock_qty")
        )
        .group_by(StockQuant.product_id)
    ).subquery()

    # 子查询：订单
    order_conditions = [SaleOrder.state == 'sale']
    if days != -1 and start_dt:
        order_conditions.append(SaleOrder.date_order >= start_dt)

    order_subq = (
        select(
            SaleOrderLine.product_id.label("pid"),
            func.count(SaleOrderLine.id).label("order_count")
        )
        .join(SaleOrder, SaleOrder.id == SaleOrderLine.order_id)
        .where(*order_conditions)
        .group_by(SaleOrderLine.product_id)
    ).subquery()

    # 主查询
    stmt = (
        select(
            ProductProduct.id,
            ProductProduct.default_code,
            ProductProduct.barcode,
            ProductTemplate.name,
            ProductTemplate.categ_id,
            ProductCategory.name.label("category_name"),
            func.coalesce(order_subq.c.order_count, 0).label("order_count"),
            func.coalesce(stock_subq.c.stock_qty, 0).label("stock_qty")
        )
        .join(ProductTemplate, ProductProduct.product_tmpl_id == ProductTemplate.id)
        .join(ProductCategory, ProductTemplate.categ_id == ProductCategory.id, isouter=True)
        .join(stock_subq, stock_subq.c.pid == ProductProduct.id, isouter=True)
        .join(order_subq, order_subq.c.pid == ProductProduct.id, isouter=True)
    )

    # 分类过滤
    if category_filter is not None:
        stmt = stmt.where(category_filter)

    # noorder 筛选
    if noorder:
        stmt = stmt.where(stock_subq.c.stock_qty > 0) \
                   .where(order_subq.c.order_count.is_(None)) \
                   .order_by(stock_subq.c.stock_qty.desc())
    else:
        if days != -1:
            # days!=-1 的情况只显示有订单产品
            stmt = stmt.where(order_subq.c.order_count > 0) \
                       .order_by(order_subq.c.order_count.desc())
        else:
            # days=-1 → 显示所有产品，按订单数降序
            stmt = stmt.order_by(func.coalesce(order_subq.c.order_count, 0).desc())

    # --- 总数 ---
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # --- 分页 ---
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    rows = result.all()

    products = []
    for r in rows:
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
            "orderCount": int(r.order_count or 0),
            "stockQty": float(r.stock_qty or 0)
        })

    return {"total": total, "products": products}


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
