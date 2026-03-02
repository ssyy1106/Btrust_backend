from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List, Optional
from datetime import date

from database import get_db
from models.invoice import Invoice
from helper import getDB, getStores
from dependencies.permission import PermissionChecker

router = APIRouter(prefix="/report", tags=["Report"])

@router.get("/invoice_vs_sales")
async def invoice_vs_sales(
    store: Optional[List[str]] = Query(None, description="Stores"),
    date_specific: Optional[date] = Query(None, alias="date", description="Specific date"),
    invoice_start_date: Optional[date] = Query(None, description="Invoice start date"),
    invoice_end_date: Optional[date] = Query(None, description="Invoice end date"),
    entry_start_date: Optional[date] = Query(None, description="Entry start date"),
    entry_end_date: Optional[date] = Query(None, description="Entry end date"),
    db: AsyncSession = Depends(get_db),
    user = Depends(PermissionChecker(required_roles=["invoice:search", "invoice:view"]))
):
    # 1. 权限与门店校验
    stores = getStores(user, store)
    
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
    
    # 聚合 Invoice Total Amount by Store
    stmt = (
        select(Invoice.store, func.sum(Invoice.totalamount).label("total_amount"))
        .where(and_(*invoice_filters))
        .group_by(Invoice.store)
    )
    
    result = await db.execute(stmt)
    invoice_rows = result.all()
    invoice_map = {row.store: (row.total_amount or 0) for row in invoice_rows}

    # 4. 查询 Sales 数据 (PostgreSQL Sync via helper.getDB)
    sales_map = {}
    
    s_date_str = sales_start.strftime('%Y-%m-%d')
    e_date_str = sales_end.strftime('%Y-%m-%d')
    
    if stores:
        store_sql_list = "(" + ",".join([f"'{s}'" for s in stores]) + ")"
    else:
        return []

    # 使用 day_department_aggregate 表 (参考 graphqlschema/datedata.py)
    sql = f"""
        SELECT store, sum(total_amount) 
        FROM day_department_aggregate 
        WHERE day >= '{s_date_str}' AND day <= '{e_date_str}' 
        AND store IN {store_sql_list}
        GROUP BY store
    """
    
    with getDB() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            for row in rows:
                sales_map[row[0]] = (row[1] or 0)

    # 5. 合并结果
    report_data = []
    all_stores = set(invoice_map.keys()) | set(sales_map.keys())
    
    for s in sorted(list(all_stores)):
        inv_amt = float(invoice_map.get(s, 0))
        sale_amt = float(sales_map.get(s, 0))
        report_data.append({
            "store": s,
            "invoice_total": inv_amt,
            "sales_total": sale_amt,
            "difference": sale_amt - inv_amt
        })
        
    return report_data
