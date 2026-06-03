from fastapi import APIRouter, Query, Depends, HTTPException, status
from typing import List, Optional
from datetime import date
from pydantic import BaseModel
from sqlalchemy import text, bindparam
from database import get_db_store_sqlserver_factory
from helper import verify_token
from graphqlschema.schema import UserInformation
import math
from collections import defaultdict

router = APIRouter(prefix="/report/sales", tags=["Sales Report"])

class DailySales(BaseModel):
    date: str
    qty: float
    amount: float
    weight: float

class SalesItem(BaseModel):
    upc: str
    name_en: Optional[str]
    name_cn: Optional[str]
    daily_sales: List[DailySales]
    total_qty: float
    total_amount: float
    total_weight: float

class DailySummary(BaseModel):
    date: str
    total_qty: float
    total_amount: float
    total_weight: float

class PaginatedSalesResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: List[SalesItem]
    daily_summaries: List[DailySummary]

@router.get("/items", response_model=PaginatedSalesResponse)
async def get_sales_items(
    store: str = Query(..., description="门店代码"),
    start_date: date = Query(..., description="开始日期 (YYYY-MM-DD)"),
    end_date: date = Query(..., description="结束日期 (YYYY-MM-DD)"),
    department: Optional[List[str]] = Query(None, description="部门 ID 列表"),
    subdepartment: Optional[List[str]] = Query(None, description="子部门 ID 列表"),
    barcode: Optional[str] = Query(None, description="条码模糊查询"),
    name: Optional[str] = Query(None, description="名称模糊查询"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=99999, description="每页数量"),
    sort_by: str = Query("amount", regex="^(qty|amount|weight|upc)$", description="排序字段"),
    sort_dir: str = Query("desc", regex="^(asc|desc)$", description="排序方向"),
    user: UserInformation = Depends(verify_token)
):
    # 1. 权限校验：确保用户有权限访问该门店
    if store not in user.store:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this store."
        )

    # 2. 准备 SQL 查询条件
    # 默认 R.F1034=3 表示每日报表类型
    where_clauses = ["R.F1034=3", "CAST(R.F254 AS DATE) BETWEEN :start_date AND :end_date"]
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "store": store,
        "offset": (page - 1) * page_size,
        "limit": page_size
    }

    if department:
        where_clauses.append("S.F03 IN :depts")
        params["depts"] = tuple(department)
    if subdepartment:
        where_clauses.append("S.F04 IN :subdepts")
        params["subdepts"] = tuple(subdepartment)
    if barcode:
        where_clauses.append("R.F01 LIKE :barcode")
        params["barcode"] = f"%{barcode}%"
    if name:
        where_clauses.append("(O.F29 LIKE :name OR O.F255 LIKE :name OR P.F2095 LIKE :name)")
        params["name"] = f"%{name}%"

    where_str = " AND ".join(where_clauses)
    
    # 排序字段映射到 SQL 聚合函数
    sort_map = {
        "qty": "SUM(R.F64)",
        "amount": "SUM(R.F65)",
        "weight": "SUM(R.F67)",
        "upc": "LTRIM(RTRIM(R.F01))"
    }
    sort_column = sort_map.get(sort_by, "SUM(R.F65)")

    async_session_factory = get_db_store_sqlserver_factory(store)
    
    daily_summaries = []
    total_items = 0
    items = []

    async for db in async_session_factory():
        # 1) 获取符合条件的总商品数（去重 UPC）
        count_query = text(f"""
            SELECT COUNT(DISTINCT R.F01)
            FROM RPT_ITM_D R
            LEFT JOIN OBJ_TAB O ON R.F01 = O.F01
            LEFT JOIN POS_TAB P ON R.F01 = P.F01
            LEFT JOIN SDP_TAB S ON P.F04 = S.F04
            WHERE {where_str}
        """)
        
        if department: count_query = count_query.bindparams(bindparam("depts", expanding=True))
        if subdepartment: count_query = count_query.bindparams(bindparam("subdepts", expanding=True))
            
        count_res = await db.execute(count_query, params)
        total_items = count_res.scalar() or 0
        
        if total_items == 0:
            break

        # 1.5) 获取搜寻时间段内该筛选范围的每日合计
        summary_query = text(f"""
            SELECT 
                CAST(R.F254 AS DATE) as sale_date,
                SUM(R.F64) as total_qty,
                SUM(R.F65) as total_amount,
                SUM(R.F67) as total_weight
            FROM RPT_ITM_D R
            LEFT JOIN OBJ_TAB O ON R.F01 = O.F01
            LEFT JOIN POS_TAB P ON R.F01 = P.F01
            LEFT JOIN SDP_TAB S ON P.F04 = S.F04
            WHERE {where_str}
            GROUP BY CAST(R.F254 AS DATE)
            ORDER BY sale_date ASC
        """)
        if department: summary_query = summary_query.bindparams(bindparam("depts", expanding=True))
        if subdepartment: summary_query = summary_query.bindparams(bindparam("subdepts", expanding=True))

        summary_res = await db.execute(summary_query, params)
        daily_summaries = [
            DailySummary(
                date=str(row.sale_date),
                total_qty=float(row.total_qty or 0),
                total_amount=float(row.total_amount or 0),
                total_weight=float(row.total_weight or 0)
            )
            for row in summary_res.all()
        ]

        # 2) 分页获取 UPC 列表及其汇总数据
        items_query = text(f"""
            SELECT 
                LTRIM(RTRIM(R.F01)) as upc,
                MAX(LTRIM(RTRIM(O.F29))) as name_en,
                MAX(CASE WHEN :store = 'MT' THEN LTRIM(RTRIM(O.F255)) ELSE COALESCE(LTRIM(RTRIM(P.F2095)), LTRIM(RTRIM(O.F255))) END) as name_cn,
                SUM(R.F64) as total_qty,
                SUM(R.F65) as total_amount,
                SUM(R.F67) as total_weight
            FROM RPT_ITM_D R
            LEFT JOIN OBJ_TAB O ON R.F01 = O.F01
            LEFT JOIN POS_TAB P ON R.F01 = P.F01
            LEFT JOIN SDP_TAB S ON P.F04 = S.F04
            WHERE {where_str}
            GROUP BY R.F01
            ORDER BY {sort_column} {sort_dir}
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """)
        
        if department: items_query = items_query.bindparams(bindparam("depts", expanding=True))
        if subdepartment: items_query = items_query.bindparams(bindparam("subdepts", expanding=True))
            
        items_res = await db.execute(items_query, params)
        paged_rows = items_res.all()
        
        if not paged_rows:
            break
            
        paged_upcs = [row.upc for row in paged_rows]
        
        # 3) 获取这些 UPC 在时间范围内的每日明细
        details_query = text(f"""
            SELECT 
                LTRIM(RTRIM(F01)) as upc,
                CAST(F254 AS DATE) as sale_date,
                SUM(F64) as qty,
                SUM(F65) as amount,
                SUM(F67) as weight
            FROM RPT_ITM_D
            WHERE F1034=3 
              AND CAST(F254 AS DATE) BETWEEN :start_date AND :end_date
              AND F01 IN :upcs
            GROUP BY F01, CAST(F254 AS DATE)
            ORDER BY F01, sale_date ASC
        """).bindparams(bindparam("upcs", expanding=True))
        
        details_res = await db.execute(details_query, {
            "start_date": start_date,
            "end_date": end_date,
            "upcs": tuple(paged_upcs)
        })
        details_rows = details_res.all()
        
        # 4) 聚合数据构建响应
        details_map = defaultdict(list)
        for d in details_rows:
            details_map[d.upc].append(DailySales(
                date=str(d.sale_date),
                qty=float(d.qty or 0),
                amount=float(d.amount or 0),
                weight=float(d.weight or 0)
            ))
            
        for row in paged_rows:
            items.append(SalesItem(
                upc=row.upc,
                name_en=row.name_en,
                name_cn=row.name_cn,
                daily_sales=details_map.get(row.upc, []),
                total_qty=float(row.total_qty or 0),
                total_amount=float(row.total_amount or 0),
                total_weight=float(row.total_weight or 0)
            ))

    return PaginatedSalesResponse(
        total=total_items,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total_items / page_size) if page_size > 0 else 0,
        items=items,
        daily_summaries=daily_summaries
    )