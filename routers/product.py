import json
import os
from fastapi import APIRouter, Query, Depends, HTTPException, Response, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_, text
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, date
import asyncio
from fastapi.concurrency import run_in_threadpool

from dependencies.permission import PermissionChecker
from database import get_db_odoo, get_db_store_sqlserver_factory
from models.product import ProductProduct, ProductTemplate, IrAttachment, ProductCategory, StockQuant, ObjTab, CatTab, PriceTab, UMETab, PosTab
from models.pickup import SaleOrder, SaleOrderLine
from schemas.product import ProductListResponse, ProductCategoryResponse
from helper import getOdooAccount, to_utc_naive, getDB

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

async def _get_product_common(
    barcode: str,
    store: str,
    db: AsyncSession,
    try_without_checkdigit: bool = False  # 👈 是否允许去掉最后一位再查
):
    now = datetime.now()

    # --- 1️⃣ 查询商品信息 + 分类名称 ---
    result = await db.execute(
        select(ObjTab, CatTab.F1023)
        .join(CatTab, ObjTab.F17 == CatTab.F17, isouter=True)
        .where(ObjTab.F01 == barcode)
    )
    row = result.first()

    if not row and try_without_checkdigit:
        # 试着去掉最后一位再补齐14位，防止最后一位是校验位
        barcode = '0' + barcode[:len(barcode) - 1]
        result = await db.execute(
            select(ObjTab, CatTab.F1023)
            .join(CatTab, ObjTab.F17 == CatTab.F17, isouter=True)
            .where(ObjTab.F01 == barcode)
        )
        row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="商品未找到")

    product, category_name = row

    # --- 2️⃣ 查询价格信息 ---
    price_result = await db.execute(
        select(PriceTab).where(PriceTab.F01 == (product.F122 if product.F122 else barcode))
    )
    prices = price_result.scalars().all()
    if not prices:
        raise HTTPException(status_code=404, detail="价格信息未找到")

    # --- 3️⃣ 促销价逻辑 ---
    valid_prices = []
    for p in prices:
        start, end = p.F35, p.F129
        if end:
            end = end.replace(hour=23, minute=59, second=59)
        if (start and end and start <= now <= end) or p.F113.strip() == "REG":
            valid_prices.append(p)

    chosen_price = (
        next((p for p in valid_prices if p.F113.strip() == "INSTORE"), None)
        or next((p for p in valid_prices if p.F113.strip() not in ("REG", "INSTORE")), None)
        or next((p for p in valid_prices if p.F113.strip() == "REG"), None)
    )
    if not chosen_price:
        raise HTTPException(status_code=404, detail="有效价格未找到")

    original_price_obj = next((p for p in prices if p.F113.strip() == "REG"), None)
    original_price = original_price_obj.F30 if original_price_obj else None

    # --- 4️⃣ 判断单位类型 ---
    if (product.F82 and product.F82.strip() == "1") or (chosen_price.F33 and chosen_price.F33.strip() == "I"):
        unit_type = "lb"
    else:
        unit_type = "ea"

    # --- 5️⃣ 中文名 / 法文名 ---
    chinese_name = product.F255.strip() if product.F255 else None
    french_name = None
    pos_result = await db.execute(select(PosTab).where(PosTab.F01 == barcode))
    pos = pos_result.scalars().first()
    if pos and pos.F2095:
        if store == 'MT':
            french_name = pos.F2095
        else:
            chinese_name = pos.F2095

    def _is_tax_on(value):
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value == 1
        return str(value).strip() == "1"

    tax_fields = [pos.F81, pos.F96, pos.F97, pos.F98, pos.F89] if pos else []
    tax = 1 if any(_is_tax_on(v) for v in tax_fields) else 0

    # --- 6️⃣ 图片 ---
    image_file_name = f"{barcode.strip()}.png"
    image_path = os.path.join(NETWORK_IMAGE_DIR, image_file_name)
    image_url = f"/product/image/{barcode}" if os.path.exists(image_path) else None

    # --- 返回结果 ---
    return {
        "barcode": product.F01.strip() if product.F01 else None,
        "name_en": product.F29.strip() if product.F29 else None,
        "name_cn": chinese_name,
        "name_fr": french_name,
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
        "unit_type": unit_type.strip() if unit_type else None,
        "image_url": image_url,
        "tax": tax,
        "like_code": product.F122.strip() if product.F122 else None,
    }

# --- v2 接口 ---
@router.get("/v2/{barcode}")
async def get_product_v2(barcode: str, request: Request, db: AsyncSession = Depends(get_db_from_store)):
    barcode = barcode.zfill(14)
    store = request.query_params.get("store")
    if not store:
        raise HTTPException(status_code=400, detail="store 参数必填")
    return await _get_product_common(barcode, store, db, try_without_checkdigit=True)


# --- v1 接口 ---
@router.get("/{barcode}")
async def get_product(barcode: str, request: Request, db: AsyncSession = Depends(get_db_from_store)):
    barcode = barcode.zfill(14)
    store = request.query_params.get("store")
    if not store:
        raise HTTPException(status_code=400, detail="store 参数必填")
    return await _get_product_common(barcode, store, db, try_without_checkdigit=False)


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

@router.get("/sales/{barcode}")
async def get_product_sales(
    barcode: str,
    start_date: date,
    end_date: date,
    request: Request,
    db: AsyncSession = Depends(get_db_from_store)
):
    store = request.query_params.get("store")
    if not store:
        raise HTTPException(status_code=400, detail="store 参数必填")

    # 1. Get base product info
    barcode_padded = barcode.zfill(14)
    try:
        product_info = await _get_product_common(barcode_padded, store, db, try_without_checkdigit=True)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Product with barcode {barcode} not found in store {store}")
        raise e

    # 2. Get sales data for the main product
    main_barcode_for_sales = product_info['barcode']

    def sync_get_sales_data(b, s, sd, ed):
        with getDB() as conn:
            with conn.cursor() as cursor:
                upc_to_query = b.lstrip('0') if b else ''
                if not upc_to_query:
                    return (0, 0.0)
                
                sql = """
                    SELECT COALESCE(SUM(total_count) , 0), COALESCE(SUM(total_amount), 0)
                    FROM day_upc_aggregate
                    WHERE normalized_upc = %s AND store = %s AND day BETWEEN %s AND %s
                """
                cursor.execute(sql, (upc_to_query, s, sd, ed))
                result = cursor.fetchone()
                return result or (0, 0.0)

    sales_count, sales_amount = await run_in_threadpool(sync_get_sales_data, main_barcode_for_sales, store, start_date, end_date)
    product_info['sales_count'] = sales_count
    product_info['sales_amount'] = float(sales_amount)

    # 3. Get mix & match data
    mix_match_items = []
    
    # 3.1 Get mix_id for the input barcode
    mix_id_query = text("SELECT TOP 1 F32 FROM PRICEACT_TAB WHERE F01 = :barcode AND F32 >= 1")
    mix_id_result = await db.execute(mix_id_query, {"barcode": main_barcode_for_sales})
    mix_id = mix_id_result.scalar_one_or_none()

    def sync_get_sales_for_barcodes(barcodes, s, sd, ed):
        sales_data = {}
        if not barcodes: return sales_data
        upcs_to_query = tuple(b.lstrip('0') for b in barcodes if b)
        if not upcs_to_query: return sales_data

        with getDB() as conn:
            with conn.cursor() as cursor:
                sql = "SELECT normalized_upc, COALESCE(SUM(total_count) , 0), COALESCE(SUM(total_amount), 0) FROM day_upc_aggregate WHERE normalized_upc IN %s AND store = %s AND day BETWEEN %s AND %s GROUP BY normalized_upc"
                cursor.execute(sql, (upcs_to_query, s, sd, ed))
                for row in cursor.fetchall():
                    sales_data[row[0]] = {"sales_count": row[1], "sales_amount": row[2]}
        return sales_data
    
    if mix_id:
        # 3.2 Get all items in that mix_id group
        mix_match_query = text(f"""
            SELECT DISTINCT p.F01 as UPC, o.F155 as Brand, o.F29 as ENG, 
                            CASE WHEN '{store}' = 'MT' THEN NULL ELSE p.F2095 END as CHN,
                            CASE WHEN '{store}' = 'MT' THEN p.F2095 ELSE NULL END as FRN,
                            o.F22 as Size, pr.F32 as Mix_ID, m.F1019 as Mix_Name
            FROM POS_TAB p
            LEFT JOIN PRICEACT_TAB pr ON p.F01 = pr.F01
            LEFT JOIN OBJ_TAB o ON p.F01 = o.F01
            LEFT JOIN MIX_TAB m ON pr.F32 = m.F32
            WHERE pr.F32 = :mix_id
        """)
        mix_match_result = await db.execute(mix_match_query, {"mix_id": mix_id})
        mix_rows = mix_match_result.all()

        barcodes_in_mix = [row.UPC.strip() for row in mix_rows if row.UPC]
        
        # 3.3 Batch query sales data for all mix-match items
        sales_map = await run_in_threadpool(sync_get_sales_for_barcodes, barcodes_in_mix, store, start_date, end_date)

        # 3.4 Format mix_match items
        for row in mix_rows:
            upc_from_sql = row.UPC.strip() if row.UPC else ''
            if not upc_from_sql: continue
            upc_for_sales_map = upc_from_sql.lstrip('0')
            sales = sales_map.get(upc_for_sales_map, {"sales_count": 0, "sales_amount": 0.0})
            mix_match_items.append({"barcode": upc_from_sql, "name_en": row.ENG.strip() if row.ENG else None, "name_cn": row.CHN.strip() if row.CHN else None, "name_fr": row.FRN.strip() if row.FRN else None, "sales": sales["sales_count"], "sales_count": sales["sales_count"], "sales_amount": float(sales["sales_amount"]), "brand": row.Brand.strip() if row.Brand else None, "size": row.Size.strip() if row.Size else None, "mix_id": row.Mix_ID, "mix_name": row.Mix_Name.strip() if row.Mix_Name else None})

    product_info["mix_match"] = {"items": mix_match_items}

    # 4. Get like match data
    like_match_items = []
    like_code = product_info.get('like_code')

    if like_code:
        # 4.1 Get all items with the same like_code
        like_match_query = text(f"""
            SELECT DISTINCT o.F01 as UPC, o.F155 as Brand, o.F29 as ENG,
                            CASE WHEN '{store}' = 'MT' THEN NULL ELSE p.F2095 END as CHN,
                            CASE WHEN '{store}' = 'MT' THEN p.F2095 ELSE NULL END as FRN,
                            o.F22 as Size, o.F122 as Like_Code
            FROM OBJ_TAB o
            LEFT JOIN POS_TAB p ON o.F01 = p.F01
            WHERE o.F122 = :like_code
            ORDER BY o.F01
        """)
        like_match_result = await db.execute(like_match_query, {"like_code": like_code})
        like_rows = like_match_result.all()

        if len(like_rows) > 1:
            barcodes_in_like_group = [row.UPC.strip() for row in like_rows if row.UPC]
            
            # 4.2 Batch query sales data for all like-match items
            like_sales_map = await run_in_threadpool(sync_get_sales_for_barcodes, barcodes_in_like_group, store, start_date, end_date)

            # 4.3 Format like_match items
            for row in like_rows:
                upc_from_sql = row.UPC.strip() if row.UPC else ''
                if not upc_from_sql: continue
                upc_for_sales_map = upc_from_sql.lstrip('0')
                sales = like_sales_map.get(upc_for_sales_map, {"sales_count": 0, "sales_amount": 0.0})
                like_match_items.append({"barcode": upc_from_sql, "name_en": row.ENG.strip() if row.ENG else None, "name_cn": row.CHN.strip() if row.CHN else None, "name_fr": row.FRN.strip() if row.FRN else None, "sales": sales["sales_count"], "sales_count": sales["sales_count"], "sales_amount": float(sales["sales_amount"]), "brand": row.Brand.strip() if row.Brand else None, "size": row.Size.strip() if row.Size else None, "like_code": row.Like_Code.strip() if row.Like_Code else None})

    product_info["like_match"] = {"items": like_match_items}
    return product_info

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
        start_dt_utc = to_utc_naive(start_dt)
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
        order_conditions.append(SaleOrder.date_order >= start_dt_utc)

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
