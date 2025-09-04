import json
import os
from fastapi import APIRouter, Query, Depends, HTTPException, Response, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from dependencies.permission import PermissionChecker
from database import get_db_odoo, get_db_store_sqlserver_factory
from models.product import ProductProduct, ProductTemplate, IrAttachment, ProductCategory, StockQuant, ObjTab, CatTab, PriceTab
from models.pickup import SaleOrder, SaleOrderLine
from schemas.product import ProductListResponse, ProductCategoryResponse
from helper import getOdooAccount

router = APIRouter(prefix="/product", tags=["Product"])

# ODOO_URL, ODOO_USER, ODOO_PASSWORD, ODOO_DB = getOdooAccount()

# # 全局 session 缓存
# odoo_client = httpx.AsyncClient(base_url=ODOO_URL)
# odoo_cookies = None

NETWORK_IMAGE_DIR = r"\\172.16.30.8\image"

def normalize_end_date(end_date: datetime):
    """把结束日期的时间补到当天 23:59:59"""
    if end_date and end_date.time() == datetime.min.time():
        return end_date + timedelta(days=1) - timedelta(seconds=1)
    return end_date

async def get_db_from_store(request: Request):
    store = request.query_params.get("store")
    if not store:
        raise HTTPException(status_code=400, detail="store 参数必填")
    get_db = get_db_store_sqlserver_factory(store)
    async for db in get_db():
        yield db

@router.get("/{barcode}")
async def get_product(
        barcode: str, 
        db: AsyncSession = Depends(get_db_from_store),
    ):
    now = datetime.now()

    # 1️⃣ 查询商品信息 + 分类名称
    result = await db.execute(
        select(ObjTab, CatTab.F1023)
        .join(CatTab, ObjTab.F17 == CatTab.F17, isouter=True)
        .where(ObjTab.F01 == barcode)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="商品未找到")

    product, category_name = row

    # 2️⃣ 查询价格信息
    price_result = await db.execute(
        select(PriceTab).where(PriceTab.F01 == barcode)
    )
    prices = price_result.scalars().all()
    if not prices:
        raise HTTPException(status_code=404, detail="价格信息未找到")

    # 3️⃣ 促销价优先逻辑
    valid_prices = []
    for p in prices:
        start = p.F35
        end = p.F129
        if end:
            end = end.replace(hour=23, minute=59, second=59)
        if start and end and start <= now <= end:
            valid_prices.append(p)

    chosen_price = next((p for p in valid_prices if p.F113.strip() not in ("REG", "INSTORE")), None)
    if not chosen_price:
        chosen_price = next((p for p in valid_prices if p.F113.strip() == "INSTORE"), None)
    if not chosen_price:
        chosen_price = next((p for p in valid_prices if p.F113.strip() == "REG"), None)

    if not chosen_price:
        raise HTTPException(status_code=404, detail="有效价格未找到")

    # 原价字段
    original_price_obj = next((p for p in prices if p.F113.strip() == "INSTORE"), None)
    if not original_price_obj:
        original_price_obj = next((p for p in prices if p.F113.strip() == "REG"), None)
    original_price = original_price_obj.F30 if original_price_obj else None

    # ---------- 图片 ----------
    image_file_name = f"{barcode.strip()}.png"
    image_path = os.path.join(NETWORK_IMAGE_DIR, image_file_name)
    image_url = f"/product/image/{barcode}" if os.path.exists(image_path) else None

    # 返回结果
    return {
        "barcode": product.F01.strip() if product.F01 else None,
        "name_en": product.F29.strip() if product.F29 else None,
        "name_cn": product.F255.strip() if product.F255 else None,
        "brand": product.F155.strip() if product.F155 else None,
        "specification": product.F22.strip() if product.F22 else None,
        "category_code": product.F17,
        "category_name": category_name.strip() if category_name else None,
        "price_type": chosen_price.F113.strip() if chosen_price.F113 else None,
        "unit_price": chosen_price.F30,
        "pack_qty": chosen_price.F142,
        "pack_price": chosen_price.F140,
        "valid_from": chosen_price.F35,
        "valid_to": chosen_price.F129.replace(hour=23, minute=59, second=59) if chosen_price.F129 else None,
        "original_price": original_price,
        "image_url": image_url
    }

@router.get("/image/{barcode}")
async def get_product_image(barcode: str):
    image_file_name = f"{barcode.strip()}.png"
    image_path = os.path.join(NETWORK_IMAGE_DIR, image_file_name)
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="图片未找到")
    
    return Response(
        content=open(image_path, "rb").read(),
        media_type="image/png"
    )

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
