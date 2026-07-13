import json
import os
import time
from functools import lru_cache
from fastapi import APIRouter, Query, Depends, HTTPException, Response, Request, status
from fastapi import APIRouter, Query, Depends, HTTPException, Response, Request, status, Body
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_, text, and_
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, date
from uuid import UUID
import asyncio
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from dependencies.permission import PermissionChecker
from database import get_db_odoo, get_db_store_sqlserver_factory, get_db_stock
from models.product import ProductProduct, ProductTemplate, ProductCategory, StockQuant, ObjTab, CatTab, PriceTab, UMETab, PosTab, SdpTab, DeptTab
from models.stock import ProductSnapshot, InstorePriceSession, InstorePriceItem, InstorePriceApprovalLog, InstorePricePrintLog
from models.label_template import LabelTemplate
from models.pickup import SaleOrder, SaleOrderLine
from schemas.product import ProductListResponse, ProductCategoryResponse
from helper import getOdooAccount, to_utc_naive, getDB, verify_token, getStoreMapping
from graphqlschema.schema import UserInformation
from label_print.template_loader import get_template_by_id
from label_print.pdf_engine import LabelPDFEngine

router = APIRouter(prefix="/product", tags=["Product"])

# ODOO_URL, ODOO_USER, ODOO_PASSWORD, ODOO_DB = getOdooAccount()

# # 全局 session 缓存
# odoo_client = httpx.AsyncClient(base_url=ODOO_URL)
# odoo_cookies = None

NETWORK_IMAGE_DIR = r"\\172.16.30.8\image"
IMAGE_URL_CACHE_TTL_SECONDS = 300
_image_url_cache: Dict[str, str] = {}
_image_url_cache_loaded_at: float | None = None

INSTOREPRICE_SORT_FIELDS = {
    "submitted_date": InstorePriceSession.create_time,
    "submitted_at": InstorePriceSession.create_time,
    "submitted_by": InstorePriceSession.creator_id,
    "status": InstorePriceItem.status,
    "upc": InstorePriceItem.upc,
    "price": InstorePriceItem.new_price,
}

INSTOREPRICE_LOG_SORT_FIELDS = {
    "action_time": InstorePriceApprovalLog.action_time,
    "action_by": InstorePriceApprovalLog.action_by,
    "upc": InstorePriceApprovalLog.upc,
    "action": InstorePriceApprovalLog.action,
    "session_id": InstorePriceApprovalLog.session_id,
}

def get_all_image_url() -> Dict[str, str]:
    try:
        global _image_url_cache
        global _image_url_cache_loaded_at

        now = time.monotonic()
        if (
            _image_url_cache_loaded_at is not None
            and now - _image_url_cache_loaded_at < IMAGE_URL_CACHE_TTL_SECONDS
        ):
            return _image_url_cache

        image_url_map: Dict[str, str] = {}
        for entry in os.scandir(NETWORK_IMAGE_DIR):
            if not entry.is_file() or not entry.name.lower().endswith(".png"):
                continue
            barcode = os.path.splitext(entry.name)[0].strip()
            if not barcode:
                continue
            image_url = f"/product/image/{barcode}"
            image_url_map[barcode] = image_url
            barcode_no_zero = barcode.lstrip("0")
            if barcode_no_zero:
                image_url_map.setdefault(barcode_no_zero, image_url)
            image_url_map.setdefault(barcode.zfill(14), image_url)
        _image_url_cache = image_url_map
        _image_url_cache_loaded_at = now
        return _image_url_cache
    except OSError:
        return {}


def get_image_url(barcode: str) -> str | None:
    image_url_map = get_all_image_url()
    barcode_clean = barcode.strip()
    if not barcode_clean:
        return None
    return (
        image_url_map.get(barcode_clean)
        or image_url_map.get(barcode_clean.lstrip("0"))
        or image_url_map.get(barcode_clean.zfill(14))
    )

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

@lru_cache(maxsize=1)
def _load_hr_department_mapping():
    mapping_path = os.path.join(os.path.dirname(__file__), "report", "hr_departments_mapping.json")
    with open(mapping_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _get_sales_permissions_for_store(user: UserInformation, store: str):
    store_permission = next((item for item in (user.store_department or []) if item.storename == store), None)
    department_names = {item.department_name for item in (store_permission.departments if store_permission else []) if item.department_name}
    subdepartment_names = {item.department_name for item in (store_permission.subdepartments if store_permission else []) if item.department_name}
    department_ids = {str(item.department_id) for item in (store_permission.departments if store_permission else []) if item.department_id}
    subdepartment_ids = {str(item.department_id) for item in (store_permission.subdepartments if store_permission else []) if item.department_id}
    return {
        "departments": department_names,
        "subdepartments": subdepartment_names,
        "department_ids": department_ids,
        "subdepartment_ids": subdepartment_ids,
    }

def _collect_hr_sales_mapping(nodes, target_name: str, parent_name: str = ""):
    for node in nodes:
        node_name = node.get("name", "")
        full_name = f"{parent_name}/{node_name}" if parent_name else node_name
        if node_name == target_name or full_name == target_name:
            sales_department_ids = {str(item) for item in node.get("map_departments", [])}
            sales_subdepartment_ids = {str(item) for item in node.get("map_subdepartments", [])}
            return sales_department_ids, sales_subdepartment_ids
        found_departments, found_subdepartments = _collect_hr_sales_mapping(
            node.get("departments", []),
            target_name,
            full_name,
        )
        if found_departments or found_subdepartments:
            return found_departments, found_subdepartments
    return set(), set()

def _resolve_requested_sales_scope(
    user: UserInformation,
    store: str,
    hr_department: Optional[str],
):
    store_permission = next((item for item in (user.store_department or []) if item.storename == store), None)
    permissions = _get_sales_permissions_for_store(user, store)
    allowed_departments = set(permissions["departments"])
    allowed_subdepartments = set(permissions["subdepartments"])

    if not allowed_departments and not allowed_subdepartments:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to access this store department.")

    if not hr_department:
        return allowed_departments, allowed_subdepartments

    hr_store_name = getStoreMapping().get(store)
    if not hr_store_name:
        raise HTTPException(status_code=400, detail="Invalid store.")

    hr_store_node = next((item for item in _load_hr_department_mapping() if item.get("name") == hr_store_name), None)
    if not hr_store_node:
        raise HTTPException(status_code=400, detail="HR department mapping not found for store.")

    mapped_department_ids, mapped_subdepartment_ids = _collect_hr_sales_mapping(hr_store_node.get("departments", []), hr_department)
    if not mapped_department_ids and not mapped_subdepartment_ids:
        raise HTTPException(status_code=400, detail="Invalid HR department for this store.")

    requested_departments = {
        item.department_name
        for item in (store_permission.departments if store_permission else [])
        if item.department_name and str(item.department_id) in mapped_department_ids
    }
    requested_subdepartments = {
        item.department_name
        for item in (store_permission.subdepartments if store_permission else [])
        if item.department_name and str(item.department_id) in mapped_subdepartment_ids
    }

    requested_departments &= allowed_departments
    requested_subdepartments &= allowed_subdepartments

    if not requested_departments and not requested_subdepartments:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to access this department.")

    return requested_departments, requested_subdepartments

def _build_sales_scope_filter(allowed_departments: set[str], allowed_subdepartments: set[str]):
    department_conditions = []
    if allowed_departments:
        department_conditions.append(ProductSnapshot.department.in_(sorted(allowed_departments)))
    if allowed_subdepartments:
        department_conditions.append(ProductSnapshot.subdepartment.in_(sorted(allowed_subdepartments)))
    return or_(*department_conditions) if department_conditions else None

def _ensure_product_sales_scope(
    user: UserInformation,
    store: str,
    department: Optional[str],
    subdepartment: Optional[str],
):
    allowed_departments, allowed_subdepartments = _resolve_requested_sales_scope(user, store, None)
    if department and department in allowed_departments:
        return
    if subdepartment and subdepartment in allowed_subdepartments:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You don't have permission to access this department.",
    )

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

    # --- 新增：提取各类型的详细价格信息 ---
    def _format_price_detail(p):
        if not p:
            return None
        detail = {
            "unit_price": p.F30,
            "pack_qty": p.F142,
            "pack_price": p.F140,
            "valid_from": p.F35,
            "valid_to": p.F129.replace(hour=23, minute=59, second=59) if p.F129 else None
        }
        return None if all(value is None for value in detail.values()) else detail

    instore_price_obj = next((p for p in valid_prices if p.F113.strip() == "INSTORE"), None)
    special_price_obj = next((p for p in valid_prices if p.F113.strip() not in ("REG", "INSTORE")), None)
    regular_price_obj = next((p for p in valid_prices if p.F113.strip() == "REG"), None)

    # --- 4️⃣ 判断单位类型 ---
    if (product.F82 and product.F82.strip() == "1") or (chosen_price.F33 and chosen_price.F33.strip() == "I"):
        unit_type = "lb"
    else:
        unit_type = "ea"

    # --- 5️⃣ 中文名 / 法文名 ---
    chinese_name = product.F255.strip() if product.F255 else None
    french_name = None
    # 联表查询 POS_TAB, SDP_TAB, DEPT_TAB 获取部门和子部门名称
    pos_stmt = (
        select(PosTab, SdpTab.F1022, DeptTab.F238)
        .outerjoin(SdpTab, PosTab.F04 == SdpTab.F04)
        .outerjoin(DeptTab, SdpTab.F03 == DeptTab.F03)
        .where(PosTab.F01 == barcode)
    )
    pos_res = await db.execute(pos_stmt)
    pos_row = pos_res.first()
    pos, subdept_name, dept_name = pos_row if pos_row else (None, None, None)

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
    image_url = get_image_url(barcode)

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
        "department": dept_name.strip() if dept_name else None,
        "subdepartment": subdept_name.strip() if subdept_name else None,
        "instore_price": _format_price_detail(instore_price_obj),
        "special_price": _format_price_detail(special_price_obj),
        "regular_price": _format_price_detail(regular_price_obj),
    }

@router.get("/search")
async def search_products(
    q: str = Query(..., description="搜索关键词"),
    store: str = Query(..., description="店名"),
    limit: int = Query(10, ge=1, le=100, description="返回最多条数"),
    db: AsyncSession = Depends(get_db_stock),
    user: UserInformation = Depends(verify_token)
):
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store."
        )

    allowed_departments, allowed_subdepartments = _resolve_requested_sales_scope(user, store, None)
    scope_filter = _build_sales_scope_filter(allowed_departments, allowed_subdepartments)

    query_str = f"%{q}%"
    conditions = [
        ProductSnapshot.store == store,
        or_(
            ProductSnapshot.barcode.ilike(query_str),
            ProductSnapshot.name_en.ilike(query_str),
            ProductSnapshot.name_fr.ilike(query_str),
            ProductSnapshot.name_cn.ilike(query_str)
        )
    ]
    if scope_filter is not None:
        conditions.append(scope_filter)

    stmt = (
        select(ProductSnapshot)
        .where(*conditions)
        .order_by(ProductSnapshot.barcode.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    products = result.scalars().all()

    return [
        {
            "barcode": p.barcode,
            "name_en": p.name_en,
            "name_cn": p.name_cn,
            "name_fr": p.name_fr,
            "brand": p.brand,
            "specification": p.specification,
            "category_code": str(p.category_code) if p.category_code else None,
            "category_name": p.category_name,
            "price_type": p.price_type,
            "unit_price": p.unit_price,
            "pack_qty": p.pack_qty,
            "pack_price": p.pack_price,
            "valid_from": p.valid_from,
            "valid_to": p.valid_to,
            "original_price": p.original_price,
            "unit_type": p.unit_type,
            "image_url": p.image_url,
            "tax": p.tax,
            "store": p.store,
            "department": p.department,
            "subdepartment": p.subdepartment
        }
        for p in products
    ]

class InstorePriceCreateRequest(BaseModel):
    price_type: str = "instore"
    price: float
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    package_deal_enabled: bool = False
    package_qty: Optional[int] = None
    package_price: Optional[float] = None
    label_type: List[int] = []

class PrintProductRequest(BaseModel):
    barcode: str
    print_count: int = 1

class LabelPrintRequest(BaseModel):
    template_id: int
    products: List[PrintProductRequest]

class ApprovedLabelPrintRequest(BaseModel):
    session_id: UUID
    upc: str
    label_type: int = Field(..., ge=1)
    print_count: int = Field(1, ge=1)

class InstorePriceApprovalRequest(BaseModel):
    session_ids: List[UUID]
    status: str  # 'approve' or 'reject'

@router.get("/labelprint/search")
async def search_label_templates(
    db: AsyncSession = Depends(get_db_stock)
):
    stmt = select(LabelTemplate).order_by(LabelTemplate.id.asc())
    result = await db.execute(stmt)
    templates = result.scalars().all()

    return [
        {
            "id": template.id,
            "code": template.code,
            "name": template.name,
            "description": template.description,
            "category": template.category,
            "version": template.version,
            "is_system": template.is_system,
            "created_by": template.created_by,
            "template_json": template.template_json,
            "created_at": template.created_at,
            "updated_at": template.updated_at,
        }
        for template in templates
    ]

@router.get("/search/{barcode}")
async def search_product_with_details(
    barcode: str,
    store: str = Query(..., description="店名"),
    db_stock: AsyncSession = Depends(get_db_stock),
    db_sqlserver: AsyncSession = Depends(get_db_from_store),
    user: UserInformation = Depends(verify_token)
):
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store."
        )

    # 1. 获取基础商品信息 (复用 _get_product_common)
    try:
        product_info = await _get_product_common(barcode, store, db_sqlserver, try_without_checkdigit=True)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Product with barcode {barcode} not found in store {store}")
        raise e

    _ensure_product_sales_scope(
        user,
        store,
        product_info.get("department"),
        product_info.get("subdepartment"),
    )

    main_barcode_for_sales = product_info['barcode'] # _get_product_common 可能会返回填充后的条码

    # 2. 获取 mix_match 信息 (不含销量)
    mix_match_items = []
    mix_id_query = text("SELECT TOP 1 F32 FROM PRICEACT_TAB WHERE F01 = :barcode AND F32 >= 1")
    mix_id_result = await db_sqlserver.execute(mix_id_query, {"barcode": main_barcode_for_sales})
    mix_id = mix_id_result.scalar_one_or_none()

    if mix_id:
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
        mix_match_result = await db_sqlserver.execute(mix_match_query, {"mix_id": mix_id})
        mix_rows = mix_match_result.all()

        for row in mix_rows:
            upc_from_sql = row.UPC.strip() if row.UPC else ''
            if not upc_from_sql: continue
            mix_match_items.append({
                "barcode": upc_from_sql,
                "name_en": row.ENG.strip() if row.ENG else None,
                "name_cn": row.CHN.strip() if row.CHN else None,
                "name_fr": row.FRN.strip() if row.FRN else None,
                "brand": row.Brand.strip() if row.Brand else None,
                "size": row.Size.strip() if row.Size else None,
                "mix_id": row.Mix_ID,
                "mix_name": row.Mix_Name.strip() if row.Mix_Name else None
            })
    product_info["mix_match"] = {"items": mix_match_items}

    # 3. 查询 pendingRequest 信息
    pending_request = None
    # 查找该 UPC 对应的 pending 状态的 InstorePriceItem
    stmt_item = select(InstorePriceItem).where(
        InstorePriceItem.upc == main_barcode_for_sales,
        InstorePriceItem.store == store,
        InstorePriceItem.status == 'pending'
    )
    item_result = await db_stock.execute(stmt_item)
    instore_item = item_result.scalar_one_or_none()

    if instore_item:
        # 如果找到了 item，则查询对应的 session
        stmt_session = select(InstorePriceSession).where(
            InstorePriceSession.id == instore_item.session_id
        )
        session_result = await db_stock.execute(stmt_session)
        instore_session = session_result.scalar_one_or_none()

        if instore_session:
            # 构造 pendingRequest 字典
            pending_request = {
                "status": instore_item.status,
                "session_id": str(instore_session.id),
                "submittedBy": instore_session.creator_id, # 假设 creator_id 就是提交人名称或ID
                "submittedAt": instore_session.create_time.isoformat() if instore_session.create_time else None,
                "price_type": instore_item.price_type,
                "old_price": float(instore_item.old_price) if instore_item.old_price is not None else None,
                "new_price": float(instore_item.new_price),
                "fromDate": instore_item.from_date.isoformat() if instore_item.from_date else None,
                "toDate": instore_item.to_date.isoformat() if instore_item.to_date else None,
                "package_deal_enabled": instore_item.package_deal_enabled,
                "pack_qty": instore_item.package_qty,
                "package_price": float(instore_item.package_price) if instore_item.package_price is not None else None,
                "label_types": instore_item.label_types if instore_item.label_types else []
            }

    product_info["pendingRequest"] = pending_request

    return product_info

@router.post("/instoreprice/approvals")
async def approve_instore_price_requests(
    body: InstorePriceApprovalRequest,
    store: str = Query(..., description="Store code"),
    db_stock: AsyncSession = Depends(get_db_stock),
    db_sqlserver: AsyncSession = Depends(get_db_from_store),
    user: UserInformation = Depends(verify_token)
):
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store."
        )

    # 校验状态参数
    if body.status not in ['approve', 'reject']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status must be either 'approve' or 'reject'."
        )

    # 1. 查找对应 session_id 的所有 items
    stmt = select(InstorePriceItem).where(
        InstorePriceItem.session_id.in_(body.session_ids),
        InstorePriceItem.store == store,
    )
    result = await db_stock.execute(stmt)
    items = result.scalars().all()

    if not items:
        return {
            "status": "success",
            "message": "No items found for the provided session IDs.",
            "processed_count": 0
        }

    allowed_departments, allowed_subdepartments = _resolve_requested_sales_scope(user, store, None)
    scope_filter = _build_sales_scope_filter(allowed_departments, allowed_subdepartments)
    if scope_filter is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this department."
        )

    access_stmt = (
        select(InstorePriceItem.id)
        .join(
            ProductSnapshot,
            and_(
                ProductSnapshot.barcode == InstorePriceItem.upc,
                ProductSnapshot.store == InstorePriceItem.store,
                ProductSnapshot.store == store,
            )
        )
        .where(
            InstorePriceItem.session_id.in_(body.session_ids),
            InstorePriceItem.store == store,
            scope_filter,
        )
        .distinct()
    )
    access_result = await db_stock.execute(access_stmt)
    accessible_item_ids = set(access_result.scalars().all())
    requested_item_ids = {item.id for item in items}
    if accessible_item_ids != requested_item_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to approve one or more items in this department.",
        )

    current_user_name = user.realname or user.username

    for item in items:
        if body.status == 'approve':
            # 更新 SQL Server 里的价格表 PRICEACT_TAB
            update_price_query = text("""
                UPDATE PRICE_TAB
                SET F30 = :new_price,
                    F140 = :package_price,
                    F142 = :package_qty
                WHERE F113 = 'INSTORE' AND F01 = :upc
            """)
            await db_sqlserver.execute(update_price_query, {
                "new_price": item.new_price,
                "package_price": item.package_price,
                "package_qty": item.package_qty,
                "upc": item.upc
            })

        # 2. 将数据记录到审批日志表
        log_entry = InstorePriceApprovalLog(
            item_id=item.id,
            session_id=item.session_id,
            upc=item.upc,
            action=body.status,
            action_by=current_user_name,
            action_time=datetime.now(),
            snapshot_price=item.new_price,
            snapshot_data={
                "price_type": item.price_type,
                "old_price": float(item.old_price) if item.old_price is not None else None,
                "new_price": float(item.new_price),
                "from_date": item.from_date.isoformat() if item.from_date else None,
                "to_date": item.to_date.isoformat() if item.to_date else None,
                "package_deal_enabled": item.package_deal_enabled,
                "package_qty": item.package_qty,
                "package_price": float(item.package_price) if item.package_price else None,
                "label_types": item.label_types,
                "original_status": item.status
            }
        )
        db_stock.add(log_entry)

        # 3. 清除 instoreprice_item 里的数据
        # 注意：由于数据库中针对 item_id 存在 ON DELETE CASCADE 约束，
        # 如果需要保留日志，请确保数据库中的该约束不会在删除 item 时删掉 log。
        await db_stock.delete(item)

    if body.status == 'approve':
        await db_sqlserver.commit()
    await db_stock.commit()

    return {
        "status": "success",
        "processed_count": len(items),
        "action": body.status
    }

@router.post("/labelprint")
async def label_print(
    store: str = Query(..., description="门店代码"),
    request_body: ApprovedLabelPrintRequest = Body(...),
    db: AsyncSession = Depends(get_db_stock),
    user: UserInformation = Depends(verify_token)
):
    """
    打印已审批的商品标签。
    只允许打印 instoreprice_approval_log 中 action=approve 且包含指定 label_type 的数据。
    """
    if store not in user.store:
        raise HTTPException(status_code=403, detail="No permission for this store")

    upc = request_body.upc.zfill(14)

    log_stmt = (
        select(InstorePriceApprovalLog)
        .where(
            InstorePriceApprovalLog.session_id == request_body.session_id,
            InstorePriceApprovalLog.upc == upc,
            InstorePriceApprovalLog.action == "approve",
        )
        .order_by(InstorePriceApprovalLog.action_time.desc(), InstorePriceApprovalLog.id.desc())
    )
    log_result = await db.execute(log_stmt)
    approval_logs = log_result.scalars().all()

    matched_log = next(
        (
            log for log in approval_logs
            if request_body.label_type in ((log.snapshot_data or {}).get("label_types") or [])
        ),
        None,
    )
    if not matched_log:
        raise HTTPException(
            status_code=404,
            detail="No approved label print record found for the given session_id, upc, and label_type.",
        )

    template_json = await get_template_by_id(db, request_body.label_type)
    if not template_json:
        raise HTTPException(status_code=404, detail="Label template not found")

    snapshot_stmt = select(ProductSnapshot).where(
        ProductSnapshot.barcode == upc,
        ProductSnapshot.store == store
    )
    snapshot_result = await db.execute(snapshot_stmt)
    snapshot = snapshot_result.scalar_one_or_none()

    if not snapshot:
        raise HTTPException(status_code=404, detail="No product information found in snapshot")

    _ensure_product_sales_scope(
        user,
        store,
        snapshot.department,
        snapshot.subdepartment,
    )

    print_data = [{
        "barcode": snapshot.barcode,
        "name_cn": snapshot.name_cn,
        "name_en": snapshot.name_en,
        "unit_price": float(matched_log.snapshot_price) if matched_log.snapshot_price is not None else (float(snapshot.unit_price) if snapshot.unit_price else 0.0),
        "specification": snapshot.specification,
        "brand": snapshot.brand,
        "print_count": request_body.print_count
    }]

    engine = LabelPDFEngine(template_json)
    pdf_buffer = engine.generate(print_data)

    current_user_name = user.realname or user.username
    print_log_stmt = select(InstorePricePrintLog).where(
        InstorePricePrintLog.approval_log_id == matched_log.id,
        InstorePricePrintLog.label_id == request_body.label_type,
    )
    print_log_result = await db.execute(print_log_stmt)
    print_log = print_log_result.scalar_one_or_none()

    if print_log:
        print_log.print_count += 1
        print_log.printed_by = current_user_name
        print_log.printed_time = datetime.now()
    else:
        db.add(InstorePricePrintLog(
            approval_log_id=matched_log.id,
            label_id=request_body.label_type,
            printed_by=current_user_name,
            printed_time=datetime.now(),
            print_count=1,
        ))

    await db.commit()

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="label_{upc}.pdf"'}
    )

@router.post("/instoreprice/{barcode}")
async def create_instore_price_request(
    barcode: str,
    body: InstorePriceCreateRequest,
    store: str = Query(..., description="店名"),
    db_stock: AsyncSession = Depends(get_db_stock),
    db_sqlserver: AsyncSession = Depends(get_db_from_store),
    user: UserInformation = Depends(verify_token)
):
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store."
        )

    # 1. 获取当前商品价格信息 (用于 old_price)
    try:
        product_info = await _get_product_common(barcode, store, db_sqlserver, try_without_checkdigit=True)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Product not found in store database")

    _ensure_product_sales_scope(
        user,
        store,
        product_info.get("department"),
        product_info.get("subdepartment"),
    )

    current_price = product_info.get("unit_price")
    barcode_padded = product_info['barcode'] 

    # 2. 创建新 Session
    new_session = InstorePriceSession(
        creator_id=user.realname or user.username,
        create_time=datetime.now()
    )
    db_stock.add(new_session)
    await db_stock.flush() # 提前获取生成的 session.id

    # 3. 检查是否存在旧记录
    stmt_existing = select(InstorePriceItem).where(
        InstorePriceItem.upc == barcode_padded,
        InstorePriceItem.store == store,
    )
    res_existing = await db_stock.execute(stmt_existing)
    existing_item = res_existing.scalar_one_or_none()

    if existing_item:
        # 记录到审批日志 (将旧的 Item 状态快照存入日志，标记为 auto_reject)
        log_entry = InstorePriceApprovalLog(
            item_id=existing_item.id,
            session_id=existing_item.session_id,
            upc=existing_item.upc,
            action='auto_reject',
            action_by=user.realname or user.username,
            snapshot_price=existing_item.new_price,
            snapshot_data={
                "price_type": existing_item.price_type,
                "new_price": float(existing_item.new_price),
                "from_date": existing_item.from_date.isoformat() if existing_item.from_date else None,
                "to_date": existing_item.to_date.isoformat() if existing_item.to_date else None,
                "package_deal_enabled": existing_item.package_deal_enabled,
                "package_qty": existing_item.package_qty,
                "package_price": float(existing_item.package_price) if existing_item.package_price else None,
                "label_types": existing_item.label_types,
                "status": existing_item.status
            }
        )
        db_stock.add(log_entry)

        # 更新现有记录为新申请的内容
        existing_item.session_id = new_session.id
        existing_item.store = store
        existing_item.status = 'pending'
        existing_item.price_type = body.price_type
        existing_item.old_price = current_price
        existing_item.new_price = body.price
        existing_item.from_date = body.from_date
        existing_item.to_date = body.to_date
        existing_item.package_deal_enabled = body.package_deal_enabled
        existing_item.package_qty = body.package_qty
        existing_item.package_price = body.package_price
        existing_item.label_types = body.label_type
        existing_item.update_time = datetime.now()
    else:
        # 创建全新的记录
        new_item = InstorePriceItem(
            session_id=new_session.id,
            upc=barcode_padded,
            store=store,
            status='pending',
            price_type=body.price_type,
            old_price=current_price,
            new_price=body.price,
            from_date=body.from_date,
            to_date=body.to_date,
            package_deal_enabled=body.package_deal_enabled,
            package_qty=body.package_qty,
            package_price=body.package_price,
            label_types=body.label_type
        )
        db_stock.add(new_item)

    await db_stock.commit()

    return {
        "status": "success",
        "session_id": str(new_session.id),
        "submitted_at": new_session.create_time.strftime("%Y-%m-%d %H:%M:%S")
    }

@router.get("/instoreprice/search")
async def search_instore_price_items(
    store: str = Query(..., description="Store code"),
    q: Optional[str] = Query(None, description="Search keyword"),
    department: Optional[str] = Query(None, description="HR department name"),
    from_date: Optional[date] = Query(None, description="Submitted date from"),
    to_date: Optional[date] = Query(None, description="Submitted date to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: str = Query("submitted_date"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db_stock: AsyncSession = Depends(get_db_stock),
    user: UserInformation = Depends(verify_token)
):
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store."
        )

    allowed_departments, allowed_subdepartments = _resolve_requested_sales_scope(user, store, department)

    sort_column = INSTOREPRICE_SORT_FIELDS.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=400, detail=f"Unsupported sort_by: {sort_by}")

    conditions = [
        ProductSnapshot.store == store,
        InstorePriceItem.store == store,
    ]

    scope_filter = _build_sales_scope_filter(allowed_departments, allowed_subdepartments)
    if scope_filter is not None:
        conditions.append(scope_filter)

    if q and q.strip():
        keyword = f"%{q.strip()}%"
        conditions.append(
            or_(
                ProductSnapshot.barcode.ilike(keyword),
                ProductSnapshot.name_en.ilike(keyword),
                ProductSnapshot.name_cn.ilike(keyword),
                ProductSnapshot.name_fr.ilike(keyword),
                ProductSnapshot.department.ilike(keyword),
                ProductSnapshot.subdepartment.ilike(keyword),
            )
        )

    if from_date:
        conditions.append(func.date(InstorePriceSession.create_time) >= from_date)
    if to_date:
        conditions.append(func.date(InstorePriceSession.create_time) <= to_date)

    base_stmt = (
        select(InstorePriceItem, InstorePriceSession, ProductSnapshot)
        .join(InstorePriceSession, InstorePriceSession.id == InstorePriceItem.session_id)
        .join(
            ProductSnapshot,
            and_(
                ProductSnapshot.barcode == InstorePriceItem.upc,
                ProductSnapshot.store == InstorePriceItem.store,
                ProductSnapshot.store == store,
            )
        )
        .where(*conditions)
    )

    count_stmt = (
        select(func.count())
        .select_from(InstorePriceItem)
        .join(InstorePriceSession, InstorePriceSession.id == InstorePriceItem.session_id)
        .join(
            ProductSnapshot,
            and_(
                ProductSnapshot.barcode == InstorePriceItem.upc,
                ProductSnapshot.store == InstorePriceItem.store,
                ProductSnapshot.store == store,
            )
        )
        .where(*conditions)
    )

    order_clause = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
    stmt = (
        base_stmt
        .order_by(order_clause, InstorePriceItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    total_result = await db_stock.execute(count_stmt)
    total = total_result.scalar() or 0

    result = await db_stock.execute(stmt)
    rows = result.all()

    items = []
    for instore_item, instore_session, snapshot in rows:
        reviewed_by = instore_session.modifier_id
        reviewed_at = instore_session.update_time if reviewed_by and instore_item.status != "pending" else None

        items.append({
            "session_id": str(instore_session.id),
            "item": {
                "upc": snapshot.barcode,
                "name_en": snapshot.name_en,
                "name_ch": snapshot.name_cn,
                "specification": snapshot.specification,
                "unit_type": snapshot.unit_type,
                "image_url": snapshot.image_url,
                "department": snapshot.department,
                "subdepartment": snapshot.subdepartment,
            },
            "current_price": {
                "price_type": snapshot.price_type.lower() if snapshot.price_type else "instore",
                "price": float(snapshot.unit_price) if snapshot.unit_price is not None else None,
                "from_date": snapshot.valid_from.date().isoformat() if snapshot.valid_from else None,
                "to_date": snapshot.valid_to.date().isoformat() if snapshot.valid_to else None,
                "package_qty": snapshot.pack_qty,
                "package_price": float(snapshot.pack_price) if snapshot.pack_price is not None else None,
            },
            "proposed_price": {
                "price_type": instore_item.price_type,
                "price": float(instore_item.new_price) if instore_item.new_price is not None else None,
                "from_date": instore_item.from_date.isoformat() if instore_item.from_date else None,
                "to_date": instore_item.to_date.isoformat() if instore_item.to_date else None,
                "package_qty": instore_item.package_qty if instore_item.package_deal_enabled else None,
                "package_price": float(instore_item.package_price) if instore_item.package_price is not None and instore_item.package_deal_enabled else None,
            },
            "status": instore_item.status,
            "reviewed_by": reviewed_by,
            "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
            "submitted_at": instore_session.create_time.isoformat() if instore_session.create_time else None,
            "submitted_by": instore_session.creator_id,
        })

    pages = (total + page_size - 1) // page_size if total else 0
    return {
        "Items": items,
        "pagination": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    }

@router.get("/instoreprice/log/search")
async def search_instore_price_logs(
    store: str = Query(..., description="Store code"),
    session_id: Optional[UUID] = Query(None),
    upc: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    date: Optional[date] = Query(None, description="Action date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: str = Query("action_time"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db_stock: AsyncSession = Depends(get_db_stock),
    user: UserInformation = Depends(verify_token)
):
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store."
        )

    sort_column = INSTOREPRICE_LOG_SORT_FIELDS.get(sort_by)
    if sort_column is None:
        raise HTTPException(status_code=400, detail=f"Unsupported sort_by: {sort_by}")

    conditions = []

    if session_id:
        conditions.append(InstorePriceApprovalLog.session_id == session_id)
    if upc:
        conditions.append(InstorePriceApprovalLog.upc.ilike(f"%{upc}%"))
    if action:
        conditions.append(InstorePriceApprovalLog.action == action)
    if date:
        conditions.append(func.date(InstorePriceApprovalLog.action_time) == date)

    # 关联 ProductSnapshot 以获取商品详情，并确保数据属于指定 store
    base_stmt = (
        select(InstorePriceApprovalLog, ProductSnapshot)
        .join(
            ProductSnapshot,
            and_(
                ProductSnapshot.barcode == InstorePriceApprovalLog.upc,
                ProductSnapshot.store == store
            )
        )
        .where(*conditions)
    )

    count_stmt = (
        select(func.count())
        .select_from(InstorePriceApprovalLog)
        .join(
            ProductSnapshot,
            and_(
                ProductSnapshot.barcode == InstorePriceApprovalLog.upc,
                ProductSnapshot.store == store
            )
        )
        .where(*conditions)
    )

    order_clause = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
    stmt = (
        base_stmt
        .order_by(order_clause, InstorePriceApprovalLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    total_result = await db_stock.execute(count_stmt)
    total = total_result.scalar() or 0

    result = await db_stock.execute(stmt)
    rows = result.all()

    approval_log_ids = [log.id for log, _ in rows]
    print_log_map: dict[tuple[int, int], InstorePricePrintLog] = {}
    if approval_log_ids:
        print_log_stmt = select(InstorePricePrintLog).where(
            InstorePricePrintLog.approval_log_id.in_(approval_log_ids)
        )
        print_log_result = await db_stock.execute(print_log_stmt)
        print_logs = print_log_result.scalars().all()
        print_log_map = {
            (print_log.approval_log_id, int(print_log.label_id)): print_log
            for print_log in print_logs
        }

    items = []
    for log, snapshot in rows:
        label_types = ((log.snapshot_data or {}).get("label_types") or [])
        label_print_status = []
        for label_type in label_types:
            print_log = print_log_map.get((log.id, int(label_type)))
            label_print_status.append({
                "label_type": int(label_type),
                "printed": print_log is not None,
                "print_count": print_log.print_count if print_log else 0,
            })

        items.append({
            "id": log.id,
            "session_id": str(log.session_id),
            "upc": log.upc,
            "action": log.action,
            "action_by": log.action_by,
            "action_time": log.action_time.isoformat() if log.action_time else None,
            "snapshot_price": float(log.snapshot_price) if log.snapshot_price else None,
            "snapshot_data": log.snapshot_data,
            "label_print_status": label_print_status,
            "name_en": snapshot.name_en,
            "name_ch": snapshot.name_cn,
            "department": snapshot.department,
            "subdepartment": snapshot.subdepartment,
        })

    pages = (total + page_size - 1) // page_size if total else 0
    return {
        "Items": items,
        "pagination": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
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
        sales_count = 0
        sales_amount = 0.0
        upc_to_query = b.lstrip('0') if b else ''
        if not upc_to_query:
            return (0, 0.0)
        
        today = date.today()
        hist_end = min(ed, today - timedelta(days=1))

        with getDB() as conn:
            with conn.cursor() as cursor:
                # 1. Historical Data
                if sd <= hist_end:
                    sql = """
                        SELECT COALESCE(SUM(total_count) , 0), COALESCE(SUM(total_amount), 0)
                        FROM day_upc_aggregate
                        WHERE normalized_upc = %s AND store = %s AND day BETWEEN %s AND %s
                    """
                    cursor.execute(sql, (upc_to_query, s, sd, hist_end))
                    result = cursor.fetchone()
                    if result:
                        sales_count += float(result[0] or 0)
                        sales_amount += float(result[1] or 0)
                
                # 2. Today's Data
                if sd <= today <= ed:
                    qty_logic = "CASE WHEN weight IS NOT NULL AND weight <> 'NaN' THEN weight WHEN sales_qty IS NOT NULL AND sales_qty <> 'NaN' THEN sales_qty ELSE CASE WHEN unit_price = 0 OR unit_price IS NULL THEN 0 ELSE CASE WHEN MOD(total_amount + COALESCE(total_discount, 0), unit_price) = 0 THEN (total_amount + COALESCE(total_discount, 0)) / unit_price WHEN MOD(total_amount, unit_price) = 0 THEN total_amount / unit_price ELSE (total_amount + COALESCE(total_discount, 0)) / unit_price END END END"
                    sql = f"""
                        SELECT COALESCE(SUM({qty_logic}), 0), COALESCE(SUM(total_amount), 0)
                        FROM sale_item
                        WHERE ltrim(upc, '0') = %s AND store = %s AND date = %s
                    """
                    cursor.execute(sql, (upc_to_query, s, today))
                    result = cursor.fetchone()
                    if result:
                        sales_count += float(result[0] or 0)
                        sales_amount += float(result[1] or 0)
        return (sales_count, sales_amount)

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
        
        today = date.today()
        hist_end = min(ed, today - timedelta(days=1))

        with getDB() as conn:
            with conn.cursor() as cursor:
                # 1. Historical Data
                if sd <= hist_end:
                    sql = "SELECT normalized_upc, COALESCE(SUM(total_count) , 0), COALESCE(SUM(total_amount), 0) FROM day_upc_aggregate WHERE normalized_upc IN %s AND store = %s AND day BETWEEN %s AND %s GROUP BY normalized_upc"
                    cursor.execute(sql, (upcs_to_query, s, sd, hist_end))
                    for row in cursor.fetchall():
                        u = row[0]
                        if u not in sales_data: sales_data[u] = {"sales_count": 0, "sales_amount": 0.0}
                        sales_data[u]["sales_count"] += float(row[1] or 0)
                        sales_data[u]["sales_amount"] += float(row[2] or 0)
                
                # 2. Today's Data
                if sd <= today <= ed:
                    qty_logic = "CASE WHEN weight IS NOT NULL AND weight <> 'NaN' THEN weight WHEN sales_qty IS NOT NULL AND sales_qty <> 'NaN' THEN sales_qty ELSE CASE WHEN unit_price = 0 OR unit_price IS NULL THEN 0 ELSE CASE WHEN MOD(total_amount + COALESCE(total_discount, 0), unit_price) = 0 THEN (total_amount + COALESCE(total_discount, 0)) / unit_price WHEN MOD(total_amount, unit_price) = 0 THEN total_amount / unit_price ELSE (total_amount + COALESCE(total_discount, 0)) / unit_price END END END"
                    sql = f"""
                        SELECT ltrim(upc, '0'), COALESCE(SUM({qty_logic}), 0), COALESCE(SUM(total_amount), 0)
                        FROM sale_item
                        WHERE ltrim(upc, '0') IN %s AND store = %s AND date = %s
                        GROUP BY ltrim(upc, '0')
                    """
                    cursor.execute(sql, (upcs_to_query, s, today))
                    for row in cursor.fetchall():
                        u = row[0]
                        if u not in sales_data: sales_data[u] = {"sales_count": 0, "sales_amount": 0.0}
                        sales_data[u]["sales_count"] += float(row[1] or 0)
                        sales_data[u]["sales_amount"] += float(row[2] or 0)

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

def calculate_periods(store: str, mode: str, count: int, today: date):
    """
    辅助函数：模拟 routers/product.py 中 get_product_sales_trend 的周期计算逻辑
    """
    periods = []
    if mode == 'W':
        # MT: 周四(3)开始。其它: 周五(4)开始。
        target_start_weekday = 3 if store == 'MT' else 4
        # 找到最近的一个起始日期（即本周的起始日）
        p1_start = today - timedelta(days=(today.weekday() - target_start_weekday + 7) % 7)
        for i in range(count):
            start = p1_start - timedelta(weeks=i)
            end = start + timedelta(days=6)
            # 对于 Period 1，如果结束日期在未来，则只统计到今天
            periods.append((start, min(end, today) if i == 0 else end))
    else:  # 月度模式
        curr = today
        for i in range(count):
            p_start = curr.replace(day=1)
            p_end = curr # 当前月到今天，之前的月到月末
            periods.append((p_start, p_end))
            # 移动到上个月最后一天
            curr = p_start - timedelta(days=1)
    return periods

@router.get("/sales/trend/{barcode}")
async def get_product_sales_trend(
    barcode: str,
    request: Request,
    store: str = Query(..., description="store 参数必填"),
    count: int = Query(4, ge=1, description="返回周期数"),
    mode: str = Query("W", pattern="^[WM]$"),
    db: AsyncSession = Depends(get_db_from_store)
):
    # 1. 获取基础商品信息
    barcode_padded = barcode.zfill(14)
    try:
        product_info = await _get_product_common(barcode_padded, store, db, try_without_checkdigit=True)
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Product with barcode {barcode} not found in store {store}")
        raise e

    # 2. 确定时间周期
    today = date.today()
    periods = calculate_periods(store, mode, count, today)

    # 3. 定义同步销售查询函数 (复用 get_product_sales 逻辑)
    def sync_get_sales_data(b, s, sd, ed):
        sales_count = 0
        sales_amount = 0.0
        upc_to_query = b.lstrip('0') if b else ''
        if not upc_to_query:
            return (0, 0.0)
        
        today_val = date.today()
        hist_end = min(ed, today_val - timedelta(days=1))

        with getDB() as conn:
            with conn.cursor() as cursor:
                if sd <= hist_end:
                    sql = """
                        SELECT COALESCE(SUM(total_count) , 0), COALESCE(SUM(total_amount), 0)
                        FROM day_upc_aggregate
                        WHERE normalized_upc = %s AND store = %s AND day BETWEEN %s AND %s
                    """
                    cursor.execute(sql, (upc_to_query, s, sd, hist_end))
                    result = cursor.fetchone()
                    if result:
                        sales_count += float(result[0] or 0)
                        sales_amount += float(result[1] or 0)
                
                if sd <= today_val <= ed:
                    qty_logic = "CASE WHEN weight IS NOT NULL AND weight <> 'NaN' THEN weight WHEN sales_qty IS NOT NULL AND sales_qty <> 'NaN' THEN sales_qty ELSE CASE WHEN unit_price = 0 OR unit_price IS NULL THEN 0 ELSE CASE WHEN MOD(total_amount + COALESCE(total_discount, 0), unit_price) = 0 THEN (total_amount + COALESCE(total_discount, 0)) / unit_price WHEN MOD(total_amount, unit_price) = 0 THEN total_amount / unit_price ELSE (total_amount + COALESCE(total_discount, 0)) / unit_price END END END"
                    sql = f"""
                        SELECT COALESCE(SUM({qty_logic}), 0), COALESCE(SUM(total_amount), 0)
                        FROM sale_item
                        WHERE ltrim(upc, '0') = %s AND store = %s AND date = %s
                    """
                    cursor.execute(sql, (upc_to_query, s, today_val))
                    result = cursor.fetchone()
                    if result:
                        sales_count += float(result[0] or 0)
                        sales_amount += float(result[1] or 0)
        return (sales_count, sales_amount)

    def sync_get_sales_for_barcodes(barcodes, s, sd, ed):
        sales_data = {}
        if not barcodes: return sales_data
        upcs_to_query = tuple(b.lstrip('0') for b in barcodes if b)
        if not upcs_to_query: return sales_data
        
        today_val = date.today()
        hist_end = min(ed, today_val - timedelta(days=1))

        with getDB() as conn:
            with conn.cursor() as cursor:
                if sd <= hist_end:
                    sql = "SELECT normalized_upc, COALESCE(SUM(total_count) , 0), COALESCE(SUM(total_amount), 0) FROM day_upc_aggregate WHERE normalized_upc IN %s AND store = %s AND day BETWEEN %s AND %s GROUP BY normalized_upc"
                    cursor.execute(sql, (upcs_to_query, s, sd, hist_end))
                    for row in cursor.fetchall():
                        u = row[0]
                        if u not in sales_data: sales_data[u] = {"sales_count": 0, "sales_amount": 0.0}
                        sales_data[u]["sales_count"] += float(row[1] or 0)
                        sales_data[u]["sales_amount"] += float(row[2] or 0)
                
                if sd <= today_val <= ed:
                    qty_logic = "CASE WHEN weight IS NOT NULL AND weight <> 'NaN' THEN weight WHEN sales_qty IS NOT NULL AND sales_qty <> 'NaN' THEN sales_qty ELSE CASE WHEN unit_price = 0 OR unit_price IS NULL THEN 0 ELSE CASE WHEN MOD(total_amount + COALESCE(total_discount, 0), unit_price) = 0 THEN (total_amount + COALESCE(total_discount, 0)) / unit_price WHEN MOD(total_amount, unit_price) = 0 THEN total_amount / unit_price ELSE (total_amount + COALESCE(total_discount, 0)) / unit_price END END END"
                    sql = f"""
                        SELECT ltrim(upc, '0'), COALESCE(SUM({qty_logic}), 0), COALESCE(SUM(total_amount), 0)
                        FROM sale_item
                        WHERE ltrim(upc, '0') IN %s AND store = %s AND date = %s
                        GROUP BY ltrim(upc, '0')
                    """
                    cursor.execute(sql, (upcs_to_query, s, today_val))
                    for row in cursor.fetchall():
                        u = row[0]
                        if u not in sales_data: sales_data[u] = {"sales_count": 0, "sales_amount": 0.0}
                        sales_data[u]["sales_count"] += float(row[1] or 0)
                        sales_data[u]["sales_amount"] += float(row[2] or 0)
        return sales_data

    # 4. 获取趋势销售数据
    main_barcode = product_info['barcode']
    sales_trend = []
    for i, (p_start, p_end) in enumerate(periods):
        sc, sa = await run_in_threadpool(sync_get_sales_data, main_barcode, store, p_start, p_end)
        sales_trend.append({
            "period": i + 1,
            "start_date": p_start.strftime("%Y-%m-%d"),
            "end_date": p_end.strftime("%Y-%m-%d"),
            "sales_count": sc,
            "sales_amount": float(sa)
        })
    product_info["sales"] = sales_trend

    # 5. 为 Period 1 获取 mix_match 和 like_match
    p1_start, p1_end = periods[0]
    
    # 5.1 Mix Match
    mix_match_items = []
    mix_id_query = text("SELECT TOP 1 F32 FROM PRICEACT_TAB WHERE F01 = :barcode AND F32 >= 1")
    mix_id_result = await db.execute(mix_id_query, {"barcode": main_barcode})
    mix_id = mix_id_result.scalar_one_or_none()
    if mix_id:
        mix_match_query = text(f"SELECT DISTINCT p.F01 as UPC, o.F155 as Brand, o.F29 as ENG, CASE WHEN '{store}' = 'MT' THEN NULL ELSE p.F2095 END as CHN, CASE WHEN '{store}' = 'MT' THEN p.F2095 ELSE NULL END as FRN, o.F22 as Size, pr.F32 as Mix_ID, m.F1019 as Mix_Name FROM POS_TAB p LEFT JOIN PRICEACT_TAB pr ON p.F01 = pr.F01 LEFT JOIN OBJ_TAB o ON p.F01 = o.F01 LEFT JOIN MIX_TAB m ON pr.F32 = m.F32 WHERE pr.F32 = :mix_id")
        mix_match_result = await db.execute(mix_match_query, {"mix_id": mix_id})
        mix_rows = mix_match_result.all()
        barcodes_in_mix = [row.UPC.strip() for row in mix_rows if row.UPC]
        sales_map = await run_in_threadpool(sync_get_sales_for_barcodes, barcodes_in_mix, store, p1_start, p1_end)
        for row in mix_rows:
            u_sql = row.UPC.strip() if row.UPC else ''
            if not u_sql: continue
            u_sales_map = u_sql.lstrip('0')
            sales = sales_map.get(u_sales_map, {"sales_count": 0, "sales_amount": 0.0})
            mix_match_items.append({"barcode": u_sql, "name_en": row.ENG.strip() if row.ENG else None, "name_cn": row.CHN.strip() if row.CHN else None, "name_fr": row.FRN.strip() if row.FRN else None, "sales": sales["sales_count"], "sales_count": sales["sales_count"], "sales_amount": float(sales["sales_amount"]), "brand": row.Brand.strip() if row.Brand else None, "size": row.Size.strip() if row.Size else None, "mix_id": row.Mix_ID, "mix_name": row.Mix_Name.strip() if row.Mix_Name else None})
    product_info["mix_match"] = {"items": mix_match_items}

    # 5.2 Like Match
    like_match_items = []
    like_code = product_info.get('like_code')
    if like_code:
        like_match_query = text(f"SELECT DISTINCT o.F01 as UPC, o.F155 as Brand, o.F29 as ENG, CASE WHEN '{store}' = 'MT' THEN NULL ELSE p.F2095 END as CHN, CASE WHEN '{store}' = 'MT' THEN p.F2095 ELSE NULL END as FRN, o.F22 as Size, o.F122 as Like_Code FROM OBJ_TAB o LEFT JOIN POS_TAB p ON o.F01 = p.F01 WHERE o.F122 = :like_code ORDER BY o.F01")
        like_match_result = await db.execute(like_match_query, {"like_code": like_code})
        like_rows = like_match_result.all()
        if len(like_rows) > 1:
            barcodes_in_like = [row.UPC.strip() for row in like_rows if row.UPC]
            like_sales_map = await run_in_threadpool(sync_get_sales_for_barcodes, barcodes_in_like, store, p1_start, p1_end)
            for row in like_rows:
                u_sql = row.UPC.strip() if row.UPC else ''
                if not u_sql: continue
                u_sales_map = u_sql.lstrip('0')
                sales = like_sales_map.get(u_sales_map, {"sales_count": 0, "sales_amount": 0.0})
                like_match_items.append({"barcode": u_sql, "name_en": row.ENG.strip() if row.ENG else None, "name_cn": row.CHN.strip() if row.CHN else None, "name_fr": row.FRN.strip() if row.FRN else None, "sales": sales["sales_count"], "sales_count": sales["sales_count"], "sales_amount": float(sales["sales_amount"]), "brand": row.Brand.strip() if row.Brand else None, "size": row.Size.strip() if row.Size else None, "like_code": row.Like_Code.strip() if row.Like_Code else None})
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
