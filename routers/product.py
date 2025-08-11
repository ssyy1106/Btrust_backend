# routers/product.py
import json
from fastapi import APIRouter, Query, Depends
from sqlalchemy import select
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies.permission import PermissionChecker
from database import get_db_odoo
from models.product import ProductProduct, ProductTemplate, ProductCategory
from schemas.product import ProductListResponse, ProductCategoryResponse

router = APIRouter(prefix="/product", tags=["Product"])


@router.get("/", summary="获取产品信息", response_model=ProductListResponse)
async def get_products(
    itemCode: Optional[List[str]] = Query(None, description="按 itemCode 过滤"),
    categoryId: Optional[int] = Query(None, description="按分类 ID 过滤"),
    db: AsyncSession = Depends(get_db_odoo)
    #user = Depends(PermissionChecker(required_roles=["product:view"]))
):
    stmt = (
        select(
            ProductProduct.id,
            ProductProduct.default_code,
            ProductProduct.barcode,
            ProductTemplate.name,
            ProductTemplate.categ_id,
            ProductCategory.name.label("category_name")
        )
        .join(ProductTemplate, ProductProduct.product_tmpl_id == ProductTemplate.id)
        .join(ProductCategory, ProductTemplate.categ_id == ProductCategory.id, isouter=True)
    )

    if itemCode:
        stmt = stmt.where(ProductProduct.default_code.in_(itemCode))
    if categoryId:
        stmt = stmt.where(ProductTemplate.categ_id == categoryId)

    result = await db.execute(stmt)
    rows = result.all()

    products = []
    for r in rows:
        # 处理 name 字段
        name_dict = {}
        if isinstance(r.name, str):
            try:
                # 尝试解析为 JSON
                parsed = json.loads(r.name)
                if isinstance(parsed, dict):
                    name_dict = parsed
                else:
                    name_dict = {"en_US": r.name}
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
            "categoryName": r.category_name
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
