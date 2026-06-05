from fastapi import APIRouter, Query, Depends, HTTPException, status
from typing import List, Optional
from datetime import date, timedelta
from pydantic import BaseModel
from sqlalchemy import text, bindparam
from database import get_db_store_sqlserver_factory
from helper import verify_token
from graphqlschema.schema import UserInformation
import math
from collections import defaultdict
import calendar

router = APIRouter(prefix="/report/sales", tags=["Sales Report"])

class SalesDataPoint(BaseModel):
    date: Optional[str] = None
    month: Optional[str] = None
    week_start: Optional[str] = None
    week_end: Optional[str] = None
    qty: float
    amount: float
    weight: float

class SalesItem(BaseModel):
    upc: str
    name_en: Optional[str]
    name_cn: Optional[str]
    daily_sales: Optional[List[SalesDataPoint]] = None
    week_sales: Optional[List[SalesDataPoint]] = None
    month_sales: Optional[List[SalesDataPoint]] = None
    total_qty: float
    total_amount: float
    total_weight: float

class DailySummary(BaseModel):
    date: Optional[str] = None
    month: Optional[str] = None
    week_start: Optional[str] = None
    week_end: Optional[str] = None
    total_qty: float
    total_amount: float
    total_weight: float

class PaginatedSalesResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: List[SalesItem]
    daily_summaries: Optional[List[DailySummary]] = None
    week_summaries: Optional[List[DailySummary]] = None
    month_summaries: Optional[List[DailySummary]] = None

@router.get("/items", response_model=PaginatedSalesResponse, response_model_exclude_none=True)
async def get_sales_items(
    store: str = Query(..., description="门店代码"),
    start_date: date = Query(..., description="开始日期 (YYYY-MM-DD)"),
    end_date: date = Query(..., description="结束日期 (YYYY-MM-DD)"),
    mode: str = Query("D", pattern="^[DWM]$", description="统计维度: D-日, W-周, M-月"),
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

    # 1.5 准备统计周期
    periods = []
    if mode == 'D':
        curr = start_date
        while curr <= end_date:
            periods.append((curr, curr))
            curr += timedelta(days=1)
    elif mode == 'W':
        # MT: 周四(3)开始。其它: 周五(4)开始。
        target_start_weekday = 3 if store == 'MT' else 4
        target_end_weekday = (target_start_weekday - 1 + 7) % 7
        curr = start_date
        while curr <= end_date:
            days_until_end = (target_end_weekday - curr.weekday() + 7) % 7
            p_end = curr + timedelta(days=days_until_end)
            p_end = min(p_end, end_date)
            periods.append((curr, p_end))
            curr = p_end + timedelta(days=1)
    elif mode == 'M':
        curr = start_date
        while curr <= end_date:
            _, last_day = calendar.monthrange(curr.year, curr.month)
            p_end = date(curr.year, curr.month, last_day)
            p_end = min(p_end, end_date)
            periods.append((curr, p_end))
            curr = p_end + timedelta(days=1)

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
        raw_summary_rows = summary_res.all()
        daily_summaries = []
        for p_start, p_end in periods:
            p_qty, p_amount, p_weight = 0.0, 0.0, 0.0
            for row in raw_summary_rows:
                if p_start <= row.sale_date <= p_end:
                    p_qty += float(row.total_qty or 0)
                    p_amount += float(row.total_amount or 0)
                    p_weight += float(row.total_weight or 0)

            summary_data = {
                "total_qty": p_qty,
                "total_amount": p_amount,
                "total_weight": p_weight
            }
            if mode == 'D':
                summary_data["date"] = str(p_start)
            elif mode == 'W':
                summary_data["week_start"] = str(p_start)
                summary_data["week_end"] = str(p_end)
            elif mode == 'M':
                summary_data["month"] = p_start.strftime("%Y-%m")
                
            daily_summaries.append(DailySummary(**summary_data))

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
        
        # 3) 分批获取这些 UPC 在时间范围内的每日明细，防止 page_size 过大导致 SQL 参数超限或性能问题
        details_map = defaultdict(list)
        batch_size = 1000
        
        details_sql = text(f"""
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

        for i in range(0, len(paged_upcs), batch_size):
            batch_upcs = paged_upcs[i : i + batch_size]
            details_res = await db.execute(details_sql, {
                "start_date": start_date,
                "end_date": end_date,
                "upcs": tuple(batch_upcs)
            })
            
            batch_details = details_res.all()
            items_daily_data = defaultdict(list)
            for d in batch_details:
                items_daily_data[d.upc].append(d)
                
            for u in batch_upcs:
                u_daily = items_daily_data[u]
                u_periods = []
                for p_start, p_end in periods:
                    p_qty, p_amount, p_weight = 0.0, 0.0, 0.0
                    for d in u_daily:
                        if p_start <= d.sale_date <= p_end:
                            p_qty += float(d.qty or 0)
                            p_amount += float(d.amount or 0)
                            p_weight += float(d.weight or 0)

                    data_point = {
                        "qty": p_qty,
                        "amount": p_amount,
                        "weight": p_weight
                    }
                    if mode == 'D':
                        data_point["date"] = str(p_start)
                    elif mode == 'W':
                        data_point["week_start"] = str(p_start)
                        data_point["week_end"] = str(p_end)
                    elif mode == 'M':
                        data_point["month"] = p_start.strftime("%Y-%m")
                        
                    u_periods.append(SalesDataPoint(**data_point))
                details_map[u] = u_periods
            
        for row in paged_rows:
            sales_data = details_map.get(row.upc, [])
            item_params = {
                "upc": row.upc,
                "name_en": row.name_en,
                "name_cn": row.name_cn,
                "total_qty": float(row.total_qty or 0),
                "total_amount": float(row.total_amount or 0),
                "total_weight": float(row.total_weight or 0)
            }
            if mode == 'D':
                item_params["daily_sales"] = sales_data
            elif mode == 'W':
                item_params["week_sales"] = sales_data
            elif mode == 'M':
                item_params["month_sales"] = sales_data
            
            items.append(SalesItem(**item_params))

    # 根据模式动态设置返回的汇总字段名
    response_data = {
        "total": total_items,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total_items / page_size) if page_size > 0 else 0,
        "items": items,
    }
    if mode == 'D':
        response_data["daily_summaries"] = daily_summaries
    elif mode == 'W':
        response_data["week_summaries"] = daily_summaries
    elif mode == 'M':
        response_data["month_summaries"] = daily_summaries

    return PaginatedSalesResponse(**response_data)