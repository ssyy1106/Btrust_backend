from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Optional
from datetime import date, timedelta
from pydantic import BaseModel
import json
import calendar
import math
import os
from collections import defaultdict

from database import get_db
from models.invoice import Invoice, InvoiceDetail
from helper import getDB, getStores
from dependencies.permission import PermissionChecker

router = APIRouter(prefix="/report", tags=["Report"])

# 扁平化的单行数据模型
class InvoiceSalesItemFlat(BaseModel):
    store: str
    department: str
    department_name: str
    invoice_total: float
    sales_total: float
    difference: float
    invoice_period_from: Optional[date] = None
    invoice_period_to: Optional[date] = None

# 顶层响应模型，包含合计和列表
class PaginatedInvoiceSalesResponse(BaseModel):
    total: int
    total_pages: int
    current_page: int
    page_size: int
    invoice_total: float
    sales_total: float
    difference: float
    items: List[InvoiceSalesItemFlat]

def get_week_periods(start_date: date, end_date: date) -> List[tuple[date, date]]:
    """
    Generates weekly periods from Friday to Thursday.
    Example: start=2026-01-01 (Thu) -> first period is (2026-01-01, 2026-01-01)
             next period is (2026-01-02, 2026-01-08)
    """
    periods = []
    current_date = start_date
    while current_date <= end_date:
        # weekday(): Monday is 0, Thursday is 3.
        days_until_thursday = (3 - current_date.weekday() + 7) % 7
        period_end = current_date + timedelta(days=days_until_thursday)
        period_end = min(period_end, end_date)
        periods.append((current_date, period_end))
        current_date = period_end + timedelta(days=1)
    return periods

def get_month_periods(start_date: date, end_date: date) -> List[tuple[date, date]]:
    periods = []
    current_date = start_date
    while current_date <= end_date:
        _, last_day_of_month = calendar.monthrange(current_date.year, current_date.month)
        period_end = date(current_date.year, current_date.month, last_day_of_month)
        period_end = min(period_end, end_date)
        periods.append((current_date, period_end))
        current_date = period_end + timedelta(days=1)
    return periods

def get_day_periods(start_date: date, end_date: date) -> List[tuple[date, date]]:
    periods = []
    current_date = start_date
    while current_date <= end_date:
        periods.append((current_date, current_date))
        current_date += timedelta(days=1)
    return periods

def generate_periods(start_date: date, end_date: date, period_type: str) -> List[tuple[date, date]]:
    if period_type == 'D':
        return get_day_periods(start_date, end_date)
    if period_type == 'W':
        return get_week_periods(start_date, end_date)
    if period_type == 'M':
        return get_month_periods(start_date, end_date)
    return [(start_date, end_date)]

@router.get("/invoice_vs_sales", response_model=PaginatedInvoiceSalesResponse)
async def invoice_vs_sales(
    store: Optional[List[str]] = Query(None, description="Stores"),
    date_specific: Optional[date] = Query(None, alias="date", description="Specific date"),
    invoice_start_date: Optional[date] = Query(None, description="Invoice start date"),
    invoice_end_date: Optional[date] = Query(None, description="Invoice end date"),
    entry_start_date: Optional[date] = Query(None, description="Entry start date"),
    entry_end_date: Optional[date] = Query(None, description="Entry end date"),
    department: Optional[List[int]] = Query(None, description="Departments"),
    supplier: Optional[List[int]] = Query(None, description="Suppliers"),
    status: int = Query(0, description="Status (0, 1, 2)"),
    group_by_period: Optional[str] = Query(None, regex="^[DWM]$", description="Group by period: D (Day), W (Week), M (Month)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=1000000, description="Page size"),
    sort_by: str = Query("store", description="Sort by field (e.g., store, department, invoice_total)"),
    sort_order: str = Query("asc", regex="^(asc|desc)$", description="Sort order: asc or desc"),
    db: AsyncSession = Depends(get_db),
    user = Depends(PermissionChecker(required_roles=["invoice:search", "invoice:view", "invoice:report"]))
):
    # 1. 权限与门店校验
    stores = getStores(user, store)
    if not stores:
        return PaginatedInvoiceSalesResponse(
            total=0, total_pages=0, current_page=1, page_size=page_size,
            invoice_total=0, sales_total=0, difference=0, items=[]
        )

    # 从 invoice_departments_mapping.json 加载部门映射
    mapping_path = os.path.join(os.path.dirname(__file__), "invoice_departments_mapping.json")
    invoice_mapping = []
    if os.path.exists(mapping_path):
        with open(mapping_path, 'r', encoding='utf-8') as f:
            invoice_mapping = json.load(f)
            
    # 如果指定了部门，过滤 mapping (假设 department 参数对应 mapping 中的 id)
    if department:
        str_dept_ids = [str(d) for d in department]
        invoice_mapping = [n for n in invoice_mapping if str(n.get("id")) in str_dept_ids]

    # 收集所有部门ID以便进行批量查询
    invoice_dept_ids = set()
    sales_dept_ids = set()
    sales_subdept_ids = set()

    def collect_ids(node):
        if "id" in node:
            invoice_dept_ids.add(str(node["id"]))
        for d in node.get("map_departments", []):
            sales_dept_ids.add(str(d))
        for sd in node.get("map_subdepartments", []):
            sales_subdept_ids.add(str(sd))
        for child in node.get("departments", []):
            collect_ids(child)

    for dept_node in invoice_mapping:
        collect_ids(dept_node)
    
    # 2. 确定整体时间范围
    # 逻辑：优先使用 date_specific，其次 invoice_date，最后 entry_date
    overall_start = date.today()
    overall_end = date.today()
    
    # 用于 Invoice 查询的非分组情况下的日期过滤条件
    date_invoice_filters = []
    if date_specific:
        overall_start = date_specific
        overall_end = date_specific
        date_invoice_filters.append(Invoice.invoicedate == date_specific)
    else:
        # 如果指定了 invoice dates
        has_invoice_date = False
        if invoice_start_date:
            date_invoice_filters.append(Invoice.invoicedate >= invoice_start_date)
            overall_start = invoice_start_date
            has_invoice_date = True
        if invoice_end_date:
            date_invoice_filters.append(Invoice.invoicedate <= invoice_end_date)
            overall_end = invoice_end_date
            has_invoice_date = True
        
        # 如果指定了 entry dates
        if entry_start_date:
            date_invoice_filters.append(Invoice.entrytime >= entry_start_date)
            # 如果没有 invoice date 确定的 sales range，则使用 entry date
            if not has_invoice_date: 
                overall_start = entry_start_date
        if entry_end_date:
            date_invoice_filters.append(Invoice.entrytime <= entry_end_date)
            if not has_invoice_date:
                overall_end = entry_end_date

    # 生成时间段
    if group_by_period:
        periods = generate_periods(overall_start, overall_end, group_by_period)
    else:
        periods = [(overall_start, overall_end)]

    # 通用的非日期过滤条件
    base_invoice_filters = []
    if stores:
        base_invoice_filters.append(Invoice.store.in_(stores))
    if supplier:
        base_invoice_filters.append(Invoice.supplierid.in_(supplier))
    base_invoice_filters.append(Invoice.status == status)

    all_items_list = []
    grand_invoice_total = 0.0
    grand_sales_total = 0.0

    for p_start, p_end in periods:
        # 3. 查询当期 Invoice 数据
        period_invoice_filters = list(base_invoice_filters)
        if group_by_period:
            period_invoice_filters.extend([Invoice.invoicedate >= p_start, Invoice.invoicedate <= p_end])
        else:
            period_invoice_filters.extend(date_invoice_filters)

        stmt_store_invoice = (
            select(Invoice.store, func.sum(InvoiceDetail.totalamount if department else Invoice.totalamount).label("total_amount"))
            .where(and_(*period_invoice_filters))
        )
        if department:
            stmt_store_invoice = stmt_store_invoice.join(InvoiceDetail, Invoice.id == InvoiceDetail.invoiceid).where(InvoiceDetail.department.in_(department))
        stmt_store_invoice = stmt_store_invoice.group_by(Invoice.store)
        
        result_store_invoice = await db.execute(stmt_store_invoice)
        invoice_map = {row.store: float(row.total_amount or 0) for row in result_store_invoice.all()}

        invoice_dept_map = defaultdict(float)
        if invoice_dept_ids:
            target_dept_ids = [int(x) for x in invoice_dept_ids if x.isdigit()]
            if target_dept_ids:
                stmt_dept_invoice = (
                    select(Invoice.store, InvoiceDetail.department, func.sum(InvoiceDetail.totalamount).label("total_amount"))
                    .join(InvoiceDetail, Invoice.id == InvoiceDetail.invoiceid)
                    .where(and_(*period_invoice_filters, InvoiceDetail.department.in_(target_dept_ids)))
                    .group_by(Invoice.store, InvoiceDetail.department)
                )
                result_dept_invoice = await db.execute(stmt_dept_invoice)
                for row in result_dept_invoice.all():
                    invoice_dept_map[(row.store, str(row.department))] = float(row.total_amount or 0)

        # 4. 查询当期 Sales 数据
        sales_map, dept_sales_map, subdept_sales_map = {}, defaultdict(float), defaultdict(float)
        s_date_str, e_date_str = p_start.strftime('%Y-%m-%d'), p_end.strftime('%Y-%m-%d')
        store_sql_list = "(" + ",".join([f"'{s}'" for s in stores]) + ")"
        
        with getDB() as conn:
            with conn.cursor() as cursor:
                sql_sales_store = f"SELECT store, sum(total_amount) FROM day_department_aggregate WHERE day >= '{s_date_str}' AND day <= '{e_date_str}' AND store IN {store_sql_list} GROUP BY store"
                cursor.execute(sql_sales_store)
                for row in cursor.fetchall(): sales_map[row[0]] = float(row[1] or 0)

                if sales_dept_ids:
                    ids_str = "'" + "','".join(list(sales_dept_ids)) + "'"
                    sql_dept_sales = f"SELECT store, department, SUM(total_amount) FROM day_department_aggregate WHERE day >= '{s_date_str}' AND day <= '{e_date_str}' AND store IN {store_sql_list} AND department IN ({ids_str}) GROUP BY store, department"
                    cursor.execute(sql_dept_sales)
                    for row in cursor.fetchall(): dept_sales_map[(row[0], str(row[1]))] = float(row[2] or 0.0)

                if sales_subdept_ids:
                    ids_str = "'" + "','".join(list(sales_subdept_ids)) + "'"
                    sql_subdept_sales = f"SELECT store, sub_department, SUM(total_amount) FROM day_subdepartment_aggregate WHERE day >= '{s_date_str}' AND day <= '{e_date_str}' AND store IN {store_sql_list} AND sub_department IN ({ids_str}) GROUP BY store, sub_department"
                    cursor.execute(sql_subdept_sales)
                    for row in cursor.fetchall(): subdept_sales_map[(row[0], str(row[1]))] = float(row[2] or 0.0)

        # 5. 合并当期结果
        period_items_list = []
        def process_node(node, store_code, target_list):
            sales = sum(dept_sales_map.get((store_code, str(d_id)), 0.0) for d_id in node.get("map_departments", [])) + \
                    sum(subdept_sales_map.get((store_code, str(sd_id)), 0.0) for sd_id in node.get("map_subdepartments", []))
            invoice_total = invoice_dept_map.get((store_code, str(node.get("id"))), 0.0)
            
            target_list.append(InvoiceSalesItemFlat(
                store=store_code,
                department=str(node.get("id")),
                department_name=node.get("name"),
                invoice_total=round(invoice_total, 2),
                sales_total=round(sales, 2),
                difference=round(sales - invoice_total, 2),
                invoice_period_from=p_start if group_by_period else invoice_start_date,
                invoice_period_to=p_end if group_by_period else invoice_end_date
            ))
            for child_node in node.get("departments", []):
                process_node(child_node, store_code, target_list)

        all_period_stores = sorted(list(set(invoice_map.keys()) | set(sales_map.keys())))
        for s in all_period_stores:
            if invoice_mapping:
                for dept_node in invoice_mapping:
                    process_node(dept_node, s, period_items_list)
        
        all_items_list.extend(period_items_list)
        grand_invoice_total += sum(invoice_map.values())

        # 如果指定了部门，合计值为所选部门的销售额；否则为门店总销售额
        if department:
            grand_sales_total += sum(dept_sales_map.values()) + sum(subdept_sales_map.values())
        else:
            grand_sales_total += sum(sales_map.values())

    # 6. Sorting
    sortable_fields = {
        "store", "department", "department_name", "invoice_total",
        "sales_total", "difference", "invoice_period_from", "invoice_period_to"
    }
    if sort_by not in sortable_fields:
        sort_by = "store"  # default sort

    reverse = sort_order == "desc"
    try:
        all_items_list.sort(key=lambda item: (
            getattr(item, sort_by) is None,
            getattr(item, sort_by)
        ), reverse=reverse)
    except AttributeError:
        # Fallback if sort_by is somehow invalid
        pass

    # 7. Pagination
    total_items = len(all_items_list)
    total_pages = math.ceil(total_items / page_size) if page_size > 0 else 0
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    paginated_items = all_items_list[start_index:end_index]

    # 8. 计算最终合计 and return
    grand_difference = grand_sales_total - grand_invoice_total

    return PaginatedInvoiceSalesResponse(
        total=total_items,
        total_pages=total_pages,
        current_page=page,
        page_size=page_size,
        invoice_total=round(grand_invoice_total, 2),
        sales_total=round(grand_sales_total, 2),
        difference=round(grand_difference, 2),
        items=paginated_items
    )

    # # 5. 合并结果 (扁平化处理)
    # items_list = []

    # def process_node(node, store_code):
        # 根据映射计算当前节点的 Sales
