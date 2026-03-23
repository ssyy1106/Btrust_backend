from fastapi import APIRouter, Query
from typing import List, Optional
from datetime import date, datetime
from pydantic import BaseModel
from helper import getShiftDB, getDB, getStoreMapping, getStores, getStoreWithId, getCostConfig
from dependencies.permission import PermissionChecker
from fastapi import Depends
import json
import os
import psycopg2
from collections import defaultdict
import calendar


router = APIRouter(prefix="/report", tags=["Report"])

class LaborSalesDepartmentItem(BaseModel):
    id: str
    name: str
    labor_hours: float
    sales: float
    sales_per_labor_hour: float
    
    children: List['LaborSalesDepartmentItem'] = []

LaborSalesDepartmentItem.model_rebuild()

class LaborSalesItem(BaseModel):
    store: str
    labor_hours: float
    sales: float
    sales_per_labor_hour: float
    departments: List[LaborSalesDepartmentItem] = []

class MonthlyStat(BaseModel):
    year: int
    month: int
    labor_hours: float
    sales: float
    sales_per_labor_hour: float
    labor_cost: Optional[float] = 0.0
    other_cost: Optional[float] = 0.0
    total_cost: Optional[float] = 0.0
    turnover_count: Optional[int] = 0
    start_headcount: Optional[int] = 0

class LaborSalesDepartmentMonthItem(BaseModel):
    id: str
    name: str
    monthly_data: List[MonthlyStat]
    children: List['LaborSalesDepartmentMonthItem'] = []

LaborSalesDepartmentMonthItem.model_rebuild()

class LaborSalesMonthItem(BaseModel):
    store: str
    monthly_data: List[MonthlyStat]
    departments: List[LaborSalesDepartmentMonthItem] = []

@router.get("/labor_vs_sales", response_model=List[LaborSalesItem])
def get_labor_vs_sales(
    start_date: date,
    end_date: date,
    store: Optional[List[str]] = Query(None, description="门店（多个）"),
    user = Depends(PermissionChecker(required_roles=["organization:user:add"]))
    #store: Optional[str] = Query(None, description="Store code: MS, NY, TE, MT, RH")
):
    target_stores = getStores(user, store)
    # Mapping: Sales Store -> HR Store Name
    # store_hr = B1,B2,Terra,Montreal,BVW corresponds to store = MS,NY,TE,MT,RH
    store_mapping = getStoreMapping()
    mapping_stores = [store_mapping[store] for store in target_stores if store in store_mapping]

    if not target_stores:
        return []

    # Initialize results
    results = {s: {"sales": 0.0, "hours": 0.0} for s in target_stores}

    # Load Department Mapping
    mapping_path = os.path.join(os.path.dirname(__file__), "hr_departments_mapping.json")
    hr_mapping = []
    if os.path.exists(mapping_path):
        with open(mapping_path, 'r', encoding='utf-8') as f:
            hr_mapping = json.load(f)

    # Collect IDs for batch query
    sales_dept_ids = set()
    sales_subdept_ids = set()
    hr_dept_ids = set()

    def collect_ids(node):
        if "id" in node:
            hr_dept_ids.add(str(node["id"]))
        for d in node.get("map_departments", []):
            sales_dept_ids.add(str(d))
        for sd in node.get("map_subdepartments", []):
            sales_subdept_ids.add(str(sd))
        for child in node.get("departments", []):
            collect_ids(child)

    for store_node in hr_mapping:
        if store_node.get("name") in [store_mapping.get(s) for s in target_stores]:
            for dept in store_node.get("departments", []):
                collect_ids(dept)

    dept_sales_map = defaultdict(float)
    subdept_sales_map = defaultdict(float)
    hr_hours_map = defaultdict(float)

    # 1. Query Sales Data
    # Using getDB() for Sales Database (day_department_aggregate)
    try:
        with getDB() as conn:
            with conn.cursor() as cursor:
                stores_str = "'" + "','".join(target_stores) + "'"
                sql_sales = f"""
                    SELECT store, SUM(total_amount)
                    FROM day_department_aggregate
                    WHERE day >= '{start_date}' AND day <= '{end_date}'
                    AND store IN ({stores_str})
                    GROUP BY store
                """
                cursor.execute(sql_sales)
                rows = cursor.fetchall()
                for row in rows:
                    s_store = row[0]
                    s_amount = row[1]
                    if s_store in results:
                        results[s_store]["sales"] = float(s_amount) if s_amount else 0.0
                
                # Query Department Sales
                if sales_dept_ids:
                    ids_str = "'" + "','".join(sales_dept_ids) + "'"
                    sql_dept_sales = f"""
                        SELECT store, department, SUM(total_amount)
                        FROM day_department_aggregate
                        WHERE day >= '{start_date}' AND day <= '{end_date}'
                        AND store IN ({stores_str})
                        AND department IN ({ids_str})
                        GROUP BY store, department
                    """
                    cursor.execute(sql_dept_sales)
                    for row in cursor.fetchall():
                        dept_sales_map[(row[0], str(row[1]))] = float(row[2]) if row[2] else 0.0

                # Query SubDepartment Sales
                if sales_subdept_ids:
                    ids_str = "'" + "','".join(sales_subdept_ids) + "'"
                    sql_subdept_sales = f"""
                        SELECT store, sub_department, SUM(total_amount)
                        FROM day_subdepartment_aggregate
                        WHERE day >= '{start_date}' AND day <= '{end_date}'
                        AND store IN ({stores_str})
                        AND sub_department IN ({ids_str})
                        GROUP BY store, sub_department
                    """
                    cursor.execute(sql_subdept_sales)
                    for row in cursor.fetchall():
                        subdept_sales_map[(row[0], str(row[1]))] = float(row[2]) if row[2] else 0.0

    except Exception as e:
        print(f"Error querying Sales DB: {e}")

    # 2. Query HR Data
    # Using getShiftDB() for HR Database (SysDepartment, SysEmployeeDayHours)
    try:
        with getShiftDB() as conn:
            with conn.cursor() as cursor:
                # 得到时间段内所有部门的人力hours，然后循环得到每个部门的所属店 把hours加到该店
                # Get Department IDs
                hr_store_names_str = "'" + "','".join(mapping_stores) + "'"
                
                # Hierarchy: Btrust -> Operation -> Store
                sql_dept = f"""
                    SELECT d.Id, d.DepartmentName
                    FROM SysDepartment d
                    JOIN SysDepartment op ON d.ParentId = op.Id
                    JOIN SysDepartment b ON op.ParentId = b.Id
                    WHERE b.DepartmentName = 'Btrust' AND op.DepartmentName = 'Operation'
                        AND d.DepartmentName IN ({hr_store_names_str})
                """
                cursor.execute(sql_dept)
                dept_rows = cursor.fetchall()
                
                hr_store_id_map = {} # DeptId -> StoreCode
                store_ids = []
                
                # Reverse map for lookup
                hr_name_to_store = {v: k for k, v in store_mapping.items()}
                
                for row in dept_rows:
                    store_id = row[0]
                    store_name = row[1]
                    if store_name in hr_name_to_store:
                        sale_store_name = hr_name_to_store[store_name]
                        if sale_store_name in target_stores:
                            hr_store_id_map[store_id] = sale_store_name
                            store_ids.append(str(store_id))
                # Query Hours
                if store_ids:
                    sql_hours = f"""
                        SELECT DepartmentId, SUM(hours)
                        FROM SysEmployeeDayHours
                        WHERE WorkDate >= '{start_date}' AND WorkDate <= '{end_date}'
                        GROUP BY DepartmentId
                    """
                    cursor.execute(sql_hours)
                    hour_rows = cursor.fetchall()
                    for row in hour_rows:
                        store_code = getStoreWithId(row[0])
                        if str(store_code) in store_ids:
                            h_val = row[1]
                            results[hr_store_id_map[store_code]]["hours"] += float(h_val) if h_val else 0.0
                
                # Query Specific Department Hours
                if hr_dept_ids:
                    ids_str = "'" + "','".join(hr_dept_ids) + "'"
                    sql_dept_hours = f"""
                        SELECT DepartmentId, SUM(hours)
                        FROM SysEmployeeDayHours
                        WHERE WorkDate >= '{start_date}' AND WorkDate <= '{end_date}'
                        AND DepartmentId IN ({ids_str})
                        GROUP BY DepartmentId
                    """
                    cursor.execute(sql_dept_hours)
                    for row in cursor.fetchall():
                        hr_hours_map[str(row[0])] = float(row[1]) if row[1] else 0.0

    except Exception as e:
        print(f"Error querying HR DB: {e}")

    def build_dept_tree(node, store_code):
        sales = 0.0
        for d_id in node.get("map_departments", []):
            sales += dept_sales_map.get((store_code, str(d_id)), 0.0)
        for sd_id in node.get("map_subdepartments", []):
            sales += subdept_sales_map.get((store_code, str(sd_id)), 0.0)
        
        hours = hr_hours_map.get(str(node.get("id")), 0.0)
        
        children = []
        for child in node.get("departments", []):
            children.append(build_dept_tree(child, store_code))
            
        sph = sales / hours if hours > 0 else 0.0
        
        return LaborSalesDepartmentItem(
            id=str(node.get("id")),
            name=node.get("name"),
            labor_hours=round(hours, 2),
            sales=round(sales, 2),
            sales_per_labor_hour=round(sph, 2),
            children=children
        )

    # 3. Format Response
    response_list = []
    for s in target_stores:
        sales = results[s]["sales"]
        hours = results[s]["hours"]
        sph = sales / hours if hours > 0 else 0.0
        
        store_depts = []
        hr_store_name = store_mapping.get(s)
        store_node = next((item for item in hr_mapping if item["name"] == hr_store_name), None)
        if store_node:
            for dept_node in store_node.get("departments", []):
                store_depts.append(build_dept_tree(dept_node, s))

        response_list.append(LaborSalesItem(
            store=s,
            labor_hours=round(hours, 2),
            sales=round(sales, 2),
            sales_per_labor_hour=round(sph, 2),
            departments=store_depts
        ))
        
    return response_list

@router.get("/labor_vs_sales/month", response_model=List[LaborSalesMonthItem])
def get_labor_vs_sales_month(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    store: Optional[List[str]] = Query(None, description="门店（多个）"),
    user = Depends(PermissionChecker(required_roles=["organization:user:add"]))
):
    target_stores = getStores(user, store)
    store_mapping = getStoreMapping()
    mapping_stores = [store_mapping[store] for store in target_stores if store in store_mapping]

    if not target_stores:
        return []

    # Calculate Date Range
    start_date = date(start_year, start_month, 1)
    last_day = calendar.monthrange(end_year, end_month)[1]
    end_date = date(end_year, end_month, last_day)

    # Generate list of (year, month)
    months_list = []
    y, m = start_year, start_month
    while (y < end_year) or (y == end_year and m <= end_month):
        months_list.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    # Initialize Data Structures
    # store -> (year, month) -> val
    store_monthly_sales = defaultdict(lambda: defaultdict(float))
    store_monthly_hours = defaultdict(lambda: defaultdict(float))
    store_monthly_user_stats = defaultdict(lambda: defaultdict(lambda: {"start": 0, "turnover": 0}))
    
    # (store, dept_id) -> (year, month) -> val
    dept_monthly_sales = defaultdict(lambda: defaultdict(float))
    subdept_monthly_sales = defaultdict(lambda: defaultdict(float))
    
    # hr_dept_id -> (year, month) -> val
    hr_dept_monthly_hours = defaultdict(lambda: defaultdict(float))
    dept_monthly_user_stats = defaultdict(lambda: defaultdict(lambda: {"start": 0, "turnover": 0}))

    # Load Mapping
    mapping_path = os.path.join(os.path.dirname(__file__), "hr_departments_mapping.json")
    hr_mapping = []
    if os.path.exists(mapping_path):
        with open(mapping_path, 'r', encoding='utf-8') as f:
            hr_mapping = json.load(f)

    sales_dept_ids = set()
    sales_subdept_ids = set()
    hr_dept_ids = set()

    def collect_ids(node):
        if "id" in node:
            hr_dept_ids.add(str(node["id"]))
        for d in node.get("map_departments", []):
            sales_dept_ids.add(str(d))
        for sd in node.get("map_subdepartments", []):
            sales_subdept_ids.add(str(sd))
        for child in node.get("departments", []):
            collect_ids(child)

    for store_node in hr_mapping:
        if store_node.get("name") in [store_mapping.get(s) for s in target_stores]:
            for dept in store_node.get("departments", []):
                collect_ids(dept)

    # 1. Query Sales (Postgres)
    try:
        with getDB() as conn:
            with conn.cursor() as cursor:
                stores_str = "'" + "','".join(target_stores) + "'"
                
                # Store total sales by month
                sql_sales = f"""
                    SELECT store, CAST(EXTRACT(YEAR FROM day::Date) AS INTEGER), CAST(EXTRACT(MONTH FROM day::Date) AS INTEGER), SUM(total_amount)
                    FROM day_department_aggregate
                    WHERE day >= '{start_date}' AND day <= '{end_date}'
                    AND store IN ({stores_str})
                    GROUP BY store, CAST(EXTRACT(YEAR FROM day::Date) AS INTEGER), CAST(EXTRACT(MONTH FROM day::Date) AS INTEGER)
                """
                cursor.execute(sql_sales)
                for row in cursor.fetchall():
                    store_monthly_sales[row[0]][(row[1], row[2])] = float(row[3]) if row[3] else 0.0

                if sales_dept_ids:
                    ids_str = "'" + "','".join(sales_dept_ids) + "'"
                    sql_dept = f"""
                        SELECT store, department, CAST(EXTRACT(YEAR FROM day::Date) AS INTEGER), CAST(EXTRACT(MONTH FROM day::Date) AS INTEGER), SUM(total_amount)
                        FROM day_department_aggregate
                        WHERE day >= '{start_date}' AND day <= '{end_date}'
                        AND store IN ({stores_str}) AND department IN ({ids_str})
                        GROUP BY store, department, CAST(EXTRACT(YEAR FROM day::Date) AS INTEGER), CAST(EXTRACT(MONTH FROM day::Date) AS INTEGER)
                    """
                    cursor.execute(sql_dept)
                    for row in cursor.fetchall():
                        dept_monthly_sales[(row[0], str(row[1]))][(row[2], row[3])] = float(row[4]) if row[4] else 0.0

                if sales_subdept_ids:
                    ids_str = "'" + "','".join(sales_subdept_ids) + "'"
                    sql_subdept = f"""
                        SELECT store, sub_department, CAST(EXTRACT(YEAR FROM day::Date) AS INTEGER), CAST(EXTRACT(MONTH FROM day::Date) AS INTEGER), SUM(total_amount)
                        FROM day_subdepartment_aggregate
                        WHERE day >= '{start_date}' AND day <= '{end_date}'
                        AND store IN ({stores_str}) AND sub_department IN ({ids_str})
                        GROUP BY store, sub_department, CAST(EXTRACT(YEAR FROM day::Date) AS INTEGER), CAST(EXTRACT(MONTH FROM day::Date) AS INTEGER)
                    """
                    cursor.execute(sql_subdept)
                    for row in cursor.fetchall():
                        subdept_monthly_sales[(row[0], str(row[1]))][(row[2], row[3])] = float(row[4]) if row[4] else 0.0
    except Exception as e:
        print(f"Error querying Sales DB (Monthly): {e}")

    # 2. Query HR (SQL Server)
    try:
        with getShiftDB() as conn:
            with conn.cursor() as cursor:
                # Identify Store IDs
                hr_store_names_str = "'" + "','".join(mapping_stores) + "'"
                sql_dept = f"""
                    SELECT d.Id, d.DepartmentName
                    FROM SysDepartment d
                    JOIN SysDepartment op ON d.ParentId = op.Id
                    JOIN SysDepartment b ON op.ParentId = b.Id
                    WHERE b.DepartmentName = 'Btrust' AND op.DepartmentName = 'Operation'
                        AND d.DepartmentName IN ({hr_store_names_str})
                """
                cursor.execute(sql_dept)
                hr_store_id_map = {}
                hr_name_to_store = {v: k for k, v in store_mapping.items()}
                store_ids = []
                # for row in dept_rows: # Re-using var name from valid scope if available, but here we query fresh
                #     pass # fetchall returned to variable
                
                for row in cursor.fetchall(): # Process fetchall result
                    s_id, s_name = row[0], row[1]
                    if s_name in hr_name_to_store:
                        sale_store_name = hr_name_to_store[s_name]
                        if sale_store_name in target_stores:
                            hr_store_id_map[s_id] = sale_store_name
                            store_ids.append(str(s_id))
                
                if store_ids:
                    # Store Hours
                    sql_hours = f"""
                        SELECT DepartmentId, YEAR(WorkDate), MONTH(WorkDate), SUM(hours)
                        FROM SysEmployeeDayHours
                        WHERE WorkDate >= '{start_date}' AND WorkDate <= '{end_date}'
                        GROUP BY DepartmentId, YEAR(WorkDate), MONTH(WorkDate)
                    """
                    cursor.execute(sql_hours)
                    for row in cursor.fetchall():
                        store_code = getStoreWithId(row[0])
                        if str(store_code) in store_ids:
                            target_store = hr_store_id_map[store_code]
                            store_monthly_hours[target_store][(row[1], row[2])] += float(row[3]) if row[3] else 0.0
                    
                if hr_dept_ids:
                    ids_str = "'" + "','".join(hr_dept_ids) + "'"
                    sql_dept_hours = f"""
                        SELECT DepartmentId, YEAR(WorkDate), MONTH(WorkDate), SUM(hours)
                        FROM SysEmployeeDayHours
                        WHERE WorkDate >= '{start_date}' AND WorkDate <= '{end_date}'
                        AND DepartmentId IN ({ids_str})
                        GROUP BY DepartmentId, YEAR(WorkDate), MONTH(WorkDate)
                    """
                    cursor.execute(sql_dept_hours)
                    for row in cursor.fetchall():
                        hr_dept_monthly_hours[str(row[0])][(row[1], row[2])] = float(row[3]) if row[3] else 0.0
                
                # --- Get User Stats (Start Headcount & Turnover) ---
                # Build dept hierarchy for efficient store lookup locally
                cursor.execute("SELECT Id, ParentId FROM SysDepartment")
                dept_hierarchy = {row[0]: row[1] for row in cursor.fetchall()}
                
                dept_store_cache = {}
                for sid, sname in hr_store_id_map.items():
                    dept_store_cache[sid] = sname

                def get_store_for_dept(did):
                    if did in dept_store_cache: return dept_store_cache[did]
                    curr, path = did, []
                    found_store = None
                    while curr in dept_hierarchy and curr is not None:
                        if curr in dept_store_cache:
                            found_store = dept_store_cache[curr]; break
                        path.append(curr)
                        curr = dept_hierarchy[curr]
                        if curr in path: break
                    for p in path: dept_store_cache[p] = found_store
                    return found_store

                month_ranges = []
                for y, m in months_list:
                    s_date = date(y, m, 1)
                    l_day = calendar.monthrange(y, m)[1]
                    e_date = date(y, m, l_day)
                    month_ranges.append(((y, m), s_date, e_date))

                cursor.execute("SELECT DepartmentId, HireDate, TerminalDate FROM SysUser")
                for u_row in cursor.fetchall():
                    dept_id, h_str, t_str = u_row
                    if not dept_id: continue
                    target_store = get_store_for_dept(dept_id)
                    if not target_store: continue
                    
                    try:
                        h_date = datetime.strptime(h_str, "%Y-%m-%d").date() if h_str else None
                    except: h_date = None
                    if not h_date: continue
                    
                    try:
                        t_date = datetime.strptime(t_str, "%Y-%m-%d").date() if t_str else None
                    except: t_date = None
                    
                    for (y, m), m_start, m_end in month_ranges:
                        # Start Headcount: Active at start
                        if h_date <= m_start and (not t_date or t_date >= m_start):
                            store_monthly_user_stats[target_store][(y, m)]["start"] += 1
                            if str(dept_id) in hr_dept_ids:
                                dept_monthly_user_stats[str(dept_id)][(y, m)]["start"] += 1
                        
                        # Turnover: Terminated in month
                        if t_date and m_start <= t_date <= m_end:
                            store_monthly_user_stats[target_store][(y, m)]["turnover"] += 1
                            if str(dept_id) in hr_dept_ids:
                                dept_monthly_user_stats[str(dept_id)][(y, m)]["turnover"] += 1

    except Exception as e:
        print(f"Error querying HR DB (Monthly): {e}")

    # 创建一个从 HR 门店名称到销售门店代码的反向映射
    hr_name_to_store_map = {v: k for k, v in store_mapping.items()}

     # 2.5 Query Cost (Postgres - Cost DB)
    store_monthly_costs = defaultdict(lambda: defaultdict(lambda: {"cost": 0.0, "other_cost": 0.0, "total_cost": 0.0}))
    dept_monthly_costs = defaultdict(lambda: defaultdict(lambda: {"cost": 0.0, "other_cost": 0.0, "total_cost": 0.0}))

    try:
        (C_USER, C_PASS, C_HOST, C_DB, C_PORT) = getCostConfig()
        with psycopg2.connect(database=C_DB, host=C_HOST, user=C_USER, password=C_PASS, port=C_PORT) as cost_conn:
            with cost_conn.cursor() as cursor:
                # Construct month range strings
                s_m = f"{start_year}-{start_month:02d}"
                e_m = f"{end_year}-{end_month:02d}"

                stores_str = "'" + "','".join(mapping_stores) + "'"

                sql_cost = f"""
                    SELECT store, department_id, month, cost, other_cost, total_cost
                    FROM cost_hr_imports
                    WHERE month >= '{s_m}' AND month <= '{e_m}'
                    AND store IN ({stores_str})
                """
                cursor.execute(sql_cost)
                for row in cursor.fetchall():
                    c_store, c_dept_id, c_month, c_cost, c_other, c_total = row
                    try:
                        y_str, m_str = c_month.split('-')
                        y, m = int(y_str), int(m_str)
                    except:
                        continue
                    sales_store = hr_name_to_store_map.get(c_store)
                    if not sales_store:
                        continue
                    for k, v in [("cost", c_cost), ("other_cost", c_other), ("total_cost", c_total)]:
                        val = float(v or 0)
                        store_monthly_costs[c_store][(y, m)][k] += val
                        store_monthly_costs[sales_store][(y, m)][k] += val
                        if c_dept_id:
                            dept_monthly_costs[(c_store, str(c_dept_id))][(y, m)][k] += val
                            dept_monthly_costs[(sales_store, str(c_dept_id))][(y, m)][k] += val
                    # for k, v in [("cost", c_cost), ("other_cost", c_other), ("total_cost", c_total)]:
                    #     val = float(v or 0)
                    #     store_monthly_costs[c_store][(y, m)][k] += val
                    #     if c_dept_id:
                    #         dept_monthly_costs[(c_store, str(c_dept_id))][(y, m)][k] += val
    except Exception as e:
        print(f"Error querying Cost DB: {e}")

    # 3. Build Response
    def build_month_dept_tree(node, store_code):
        monthly_data = []
        for y, m in months_list:
            sales = 0.0
            for d_id in node.get("map_departments", []):
                sales += dept_monthly_sales[(store_code, str(d_id))][(y, m)]
            for sd_id in node.get("map_subdepartments", []):
                sales += subdept_monthly_sales[(store_code, str(sd_id))][(y, m)]
            
            hours = hr_dept_monthly_hours[str(node.get("id"))][(y, m)]
            sph = sales / hours if hours > 0 else 0.0
            
            # 此处的 store_code 是销售门店代码 ('MS')，与我们处理过的字典键一致
            # 使用 .get() 安全地访问，以防某些部门没有成本数据
            c_data = dept_monthly_costs.get((store_code, str(node.get("id"))), {}).get((y, m), {"cost": 0.0, "other_cost": 0.0, "total_cost": 0.0})
            
            u_data = dept_monthly_user_stats[str(node.get("id"))][(y, m)]
            
            monthly_data.append(MonthlyStat(
                year=y,
                month=m,
                labor_hours=round(hours, 2),
                sales=round(sales, 2),
                sales_per_labor_hour=round(sph, 2),
                labor_cost=round(c_data["cost"], 2),
                other_cost=round(c_data["other_cost"], 2),
                total_cost=round(c_data["total_cost"], 2),
                turnover_count=u_data["turnover"],
                start_headcount=u_data["start"]
            ))

        children = []
        for child in node.get("departments", []):
            children.append(build_month_dept_tree(child, store_code))
        return LaborSalesDepartmentMonthItem(
            id=str(node.get("id")),
            name=node.get("name"),
            monthly_data=monthly_data,
            children=children
        )

    response_list = []
    for s in target_stores:
        # Store Level Data
        store_monthly_stats = []
        for y, m in months_list:
            sales = store_monthly_sales[s][(y, m)]
            hours = store_monthly_hours[s][(y, m)]
            sph = sales / hours if hours > 0 else 0.0
            # 使用 .get() 安全地访问
            c_data = store_monthly_costs.get(s, {}).get((y, m), {"cost": 0.0, "other_cost": 0.0, "total_cost": 0.0})
            u_data = store_monthly_user_stats[s][(y, m)]
            store_monthly_stats.append(MonthlyStat(
                year=y,
                month=m,
                labor_hours=round(hours, 2),
                sales=round(sales, 2),
                sales_per_labor_hour=round(sph, 2),
                labor_cost=round(c_data["cost"], 2),
                other_cost=round(c_data["other_cost"], 2),
                total_cost=round(c_data["total_cost"], 2),
                turnover_count=u_data["turnover"],
                start_headcount=u_data["start"]
            ))
        
        store_depts = []
        hr_store_name = store_mapping.get(s)
        store_node = next((item for item in hr_mapping if item["name"] == hr_store_name), None)
        if store_node:
            for dept_node in store_node.get("departments", []):
                store_depts.append(build_month_dept_tree(dept_node, s))
        
        response_list.append(LaborSalesMonthItem(
            store=s,
            monthly_data=store_monthly_stats,
            departments=store_depts
        ))

    return response_list
