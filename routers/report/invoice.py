from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Optional
from datetime import date
from pydantic import BaseModel
import json
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

# 顶层响应模型，包含合计和列表
class InvoiceSalesResponse(BaseModel):
    total: int
    invoice_total: float
    sales_total: float
    difference: float
    items: List[InvoiceSalesItemFlat]


@router.get("/invoice_vs_sales", response_model=InvoiceSalesResponse)
async def invoice_vs_sales(
    store: Optional[List[str]] = Query(None, description="Stores"),
    date_specific: Optional[date] = Query(None, alias="date", description="Specific date"),
    invoice_start_date: Optional[date] = Query(None, description="Invoice start date"),
    invoice_end_date: Optional[date] = Query(None, description="Invoice end date"),
    entry_start_date: Optional[date] = Query(None, description="Entry start date"),
    entry_end_date: Optional[date] = Query(None, description="Entry end date"),
    department: Optional[List[int]] = Query(None, description="Departments"),
    supplier: Optional[List[int]] = Query(None, description="Suppliers"),
    status: Optional[int] = Query(None, description="Status (0, 1, 2)"),
    db: AsyncSession = Depends(get_db),
    user = Depends(PermissionChecker(required_roles=["invoice:search", "invoice:view"]))
):
    # 1. 权限与门店校验
    stores = getStores(user, store)
    if not stores:
        return []

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
    
    # 2. 确定时间范围
    # 逻辑：优先使用 date_specific，其次 invoice_date，最后 entry_date
    # 用于 Sales 查询的日期范围
    sales_start = date.today()
    sales_end = date.today()
    
    # 用于 Invoice 查询的过滤条件
    invoice_filters = []
    if date_specific:
        sales_start = date_specific
        sales_end = date_specific
        invoice_filters.append(Invoice.invoicedate == date_specific)
    else:
        # 如果指定了 invoice dates
        if invoice_start_date:
            invoice_filters.append(Invoice.invoicedate >= invoice_start_date)
            sales_start = invoice_start_date
        if invoice_end_date:
            invoice_filters.append(Invoice.invoicedate <= invoice_end_date)
            sales_end = invoice_end_date
        
        # 如果指定了 entry dates
        if entry_start_date:
            invoice_filters.append(Invoice.entrytime >= entry_start_date)
            # 如果没有 invoice date 确定的 sales range，则使用 entry date
            if not invoice_start_date: 
                sales_start = entry_start_date
        if entry_end_date:
            invoice_filters.append(Invoice.entrytime <= entry_end_date)
            if not invoice_end_date:
                sales_end = entry_end_date

    # 3. 查询 Invoice 数据 (PostgreSQL Async)
    if stores:
        invoice_filters.append(Invoice.store.in_(stores))
    
    if supplier:
        invoice_filters.append(Invoice.supplierid.in_(supplier))
    
    if status is not None:
        invoice_filters.append(Invoice.status == status)
    
    # 3a. 按门店聚合 Invoice 总金额
    if department:
        # 如果筛选了部门，Store Total 应该是这些部门的明细汇总
        stmt_store = (
            select(Invoice.store, func.sum(InvoiceDetail.totalamount).label("total_amount"))
            .join(InvoiceDetail, Invoice.id == InvoiceDetail.invoiceid)
            .where(and_(*invoice_filters, InvoiceDetail.department.in_(department)))
            .group_by(Invoice.store)
        )
    else:
        stmt_store = (
            select(Invoice.store, func.sum(Invoice.totalamount).label("total_amount"))
            .where(and_(*invoice_filters))
            .group_by(Invoice.store)
        )
    
    result_store = await db.execute(stmt_store)
    invoice_map = {row.store: float(row.total_amount or 0) for row in result_store.all()}

    # 3b. 按门店和部门聚合 Invoice 总金额
    invoice_dept_map = defaultdict(float)
    if invoice_dept_ids:
        # InvoiceDetail.department is Integer, convert ids to int
        target_dept_ids = [int(x) for x in invoice_dept_ids if x.isdigit()]
        
        if target_dept_ids:
            stmt_dept = (
                select(Invoice.store, InvoiceDetail.department, func.sum(InvoiceDetail.totalamount).label("total_amount"))
                .join(InvoiceDetail, Invoice.id == InvoiceDetail.invoiceid)
                .where(and_(*invoice_filters, InvoiceDetail.department.in_(target_dept_ids)))
                .group_by(Invoice.store, InvoiceDetail.department)
            )
            result_dept = await db.execute(stmt_dept)
            for row in result_dept.all():
                invoice_dept_map[(row.store, str(row.department))] = float(row.total_amount or 0)

    # 4. 查询 Sales 数据 (PostgreSQL Sync via helper.getDB)
    sales_map = {}
    dept_sales_map = defaultdict(float)
    subdept_sales_map = defaultdict(float)
    
    s_date_str = sales_start.strftime('%Y-%m-%d')
    e_date_str = sales_end.strftime('%Y-%m-%d')
    
    store_sql_list = "(" + ",".join([f"'{s}'" for s in stores]) + ")"
    
    with getDB() as conn:
        with conn.cursor() as cursor:
            # 4a. 按门店聚合 Sales
            sql_store = f"""
                SELECT store, sum(total_amount) 
                FROM day_department_aggregate 
                WHERE day >= '{s_date_str}' AND day <= '{e_date_str}' 
                AND store IN {store_sql_list}
                GROUP BY store
            """
            cursor.execute(sql_store)
            for row in cursor.fetchall():
                sales_map[row[0]] = float(row[1] or 0)

            # 4b. 查询 Department Sales
            if sales_dept_ids:
                ids_str = "'" + "','".join(list(sales_dept_ids)) + "'"
                sql_dept_sales = f"""
                    SELECT store, department, SUM(total_amount)
                    FROM day_department_aggregate
                    WHERE day >= '{s_date_str}' AND day <= '{e_date_str}'
                    AND store IN {store_sql_list}
                    AND department IN ({ids_str})
                    GROUP BY store, department
                """
                cursor.execute(sql_dept_sales)
                for row in cursor.fetchall():
                    dept_sales_map[(row[0], str(row[1]))] = float(row[2] or 0.0)

            # 4c. 查询 SubDepartment Sales
            if sales_subdept_ids:
                ids_str = "'" + "','".join(list(sales_subdept_ids)) + "'"
                sql_subdept_sales = f"""
                    SELECT store, sub_department, SUM(total_amount)
                    FROM day_subdepartment_aggregate
                    WHERE day >= '{s_date_str}' AND day <= '{e_date_str}'
                    AND store IN {store_sql_list}
                    AND sub_department IN ({ids_str})
                    GROUP BY store, sub_department
                """
                cursor.execute(sql_subdept_sales)
                for row in cursor.fetchall():
                    subdept_sales_map[(row[0], str(row[1]))] = float(row[2] or 0.0)

    # 5. 合并结果 (扁平化处理)
    items_list = []

    def process_node(node, store_code):
        # 根据映射计算当前节点的 Sales
        sales = 0.0
        for d_id in node.get("map_departments", []):
            sales += dept_sales_map.get((store_code, str(d_id)), 0.0)
        for sd_id in node.get("map_subdepartments", []):
            sales += subdept_sales_map.get((store_code, str(sd_id)), 0.0)
        
        # 获取当前节点的 Invoice 总计
        invoice_total = invoice_dept_map.get((store_code, str(node.get("id"))), 0.0)
        
        difference = sales - invoice_total
        
        # 添加当前节点到列表
        items_list.append(InvoiceSalesItemFlat(
            store=store_code,
            department=str(node.get("id")),
            department_name=node.get("name"),
            invoice_total=round(invoice_total, 2),
            sales_total=round(sales, 2),
            difference=round(difference, 2)
        ))

        # 递归处理子节点
        for child_node in node.get("departments", []):
            process_node(child_node, store_code)

    all_stores = sorted(list(set(invoice_map.keys()) | set(sales_map.keys())))
    
    for s in all_stores:
        if invoice_mapping:
            for dept_node in invoice_mapping:
                process_node(dept_node, s)

    # 计算全局合计
    # 使用 Store Total Map 来计算全局总计，确保即使 mapping 不完整，总数也是准确的门店总计
    # 如果希望总计等于列表项之和，可以改用 sum(item.invoice_total for item in items_list)
    # 这里采用 sum(invoice_map) 逻辑，代表查询范围内的真实总金额
    grand_invoice_total = sum(invoice_map.values())
    grand_sales_total = sum(sales_map.values())
    grand_difference = grand_sales_total - grand_invoice_total

    return InvoiceSalesResponse(
        total=len(items_list),
        invoice_total=round(grand_invoice_total, 2),
        sales_total=round(grand_sales_total, 2),
        difference=round(grand_difference, 2),
        items=items_list
    )
