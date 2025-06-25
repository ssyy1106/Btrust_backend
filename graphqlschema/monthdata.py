import datetime
from helper import getDB, getDepartmentName, getStoreStr
from graphqlschema.schema import MonthData, MonthSummary, MonthDetail, MonthSearchParameter, Product
from graphqlschema.upc import UPC, getUPC
from graphqlschema.department import getDepartments

def check_month(param: MonthSearchParameter) -> bool:
    from_month, to_month = param.FromMonth, param.ToMonth
    stores, kind, id = param.Store, param.SearchKind, param.SearchID
    if from_month > to_month:
        return False
    if kind not in ['Department', 'SubDepartment', 'UPC', 'Store']:
        return False
    for store in stores:
        if store not in ['NY', 'MS', 'MT', 'TE']:
            return False
    return True


# def getMonthData(param: MonthSearchParameter) -> MonthData:
#     start = datetime.datetime.now()
#     from_month, to_month = param.FromMonth, param.ToMonth
#     store, kind, id = getStoreStr(param.Store), param.SearchKind, param.SearchID
#     top_product = param.TopProduct
#     table = 'month_department_aggregate'
#     column = 'department'
#     UseID = True if id else False
#     if kind == 'SubDepartment':
#         table = 'month_subdepartment_aggregate'
#         column = 'sub_department'
#     elif kind == 'UPC':
#         table = 'month_upc_aggregate'
#         column = 'upc'

#     with getDB() as conn:
#         with conn.cursor() as cursor:
#             products = []
#             if kind == 'Store':
#                 # get top product info
#                 monthUPCTable = 'month_upc_max_aggregate' if top_product <= 20 else 'month_upc_aggregate'
#                 sql = f"""
#                     select sum(total_amount) as total_amount, upc 
#                     from {monthUPCTable} 
#                     where month between '{from_month}' and '{to_month}' 
#                     and store in {store} 
#                     group by upc 
#                     order by sum(total_amount) desc 
#                     limit {top_product}
#                 """
#                 cursor.execute(sql)
#                 rows = cursor.fetchall()
#                 for row in rows:
#                     products.append(Product(totalamount=row[0], upc=getUPC(row[1])))

#                 sql = f"""
#                     select month, store, sum(total_amount) as total_amount, sum(transactions) as transactions
#                     from {table}
#                     where month between '{from_month}' and '{to_month}' and store in {store}
#                     group by store, month
#                 """
#             else:
#                 sql = f"""
#                     select month, store, total_amount, {column}, transactions
#                     from {table}
#                     where month between '{from_month}' and '{to_month}' and store in {store}
#                 """
#                 if UseID:
#                     sql += f" and {column} = '{id}'"
#             try:
#                 cursor.execute(sql)
#                 rows = cursor.fetchall()

#                 # 🆕 Fetch cost data
#                 if kind == 'Department':
#                     cost_sql = f"""
#                         select store, month, department, sum(cost) as total_cost
#                         from cost_imports
#                         where month between '{from_month}' and '{to_month}' and store in {store}
#                         group by store, month, department
#                     """
#                     cursor.execute(cost_sql)
#                     cost_rows = cursor.fetchall()
#                     cost_map = {(row[0], row[1], row[2]): row[3] for row in cost_rows}
#                 else:
#                     cost_sql = f"""
#                         select store, month, sum(cost) as total_cost
#                         from cost_imports
#                         where month between '{from_month}' and '{to_month}' and store in {store}
#                         group by store, month
#                     """
#                     cursor.execute(cost_sql)
#                     cost_rows = cursor.fetchall()
#                     cost_map = {(row[0], row[1]): row[2] for row in cost_rows}

#                 items = len(rows)
#                 total_amount = 0.0
#                 total_cost = 0.0
#                 details = []
#                 for row in rows:
#                     if kind == 'Store':
#                         # (month, store_name, total_amount, transactions)
#                         month, store_name, sale_amount, transactions = row
#                         id_value = ''
#                         cost_amount = cost_map.get((store_name, month), 0.0)
#                     else:
#                         # (month, store_name, total_amount, id_value, transactions)
#                         month, store_name, sale_amount, id_value, transactions = row
#                         if kind == 'Department':
#                             cost_amount = cost_map.get((store_name, month, id_value), 0.0)
#                         else:
#                             cost_amount = 0.0

#                     gross_profit = float(sale_amount) - float(cost_amount)
#                     total_amount += float(sale_amount)
#                     total_cost += float(cost_amount)

#                     detail = MonthDetail(
#                         amount=sale_amount,
#                         month=month,
#                         store=store_name,
#                         idkind=kind,
#                         id=id_value,
#                         name='',
#                         transactions=transactions,
#                         cost=cost_amount,
#                         grossprofit=gross_profit,
#                     )
#                     if kind == 'Department' and id_value.isdigit():
#                         detail.name = getDepartmentName(int(id_value))
#                     details.append(detail)

#                 end = datetime.datetime.now()
#                 print(f"month data run time: {end-start} param: {param}")

#                 return MonthData(
#                     summary=MonthSummary(
#                         items=items,
#                         totalamount=total_amount,
#                         totalcost=total_cost,
#                         grossprofit=total_amount - total_cost,
#                     ),
#                     details=details,
#                     topproduct=products,
#                 )
#             except Exception as e:
#                 print(e)
#             return MonthData()

def getMonthData(param: MonthSearchParameter) -> MonthData:
    start = datetime.datetime.now()
    from_month, to_month = param.FromMonth, param.ToMonth
    store, kind, id = getStoreStr(param.Store), param.SearchKind, param.SearchID
    top_product = param.TopProduct
    table = 'month_department_aggregate'
    column = 'department'
    UseID = True if id else False

    if kind == 'SubDepartment':
        table = 'month_subdepartment_aggregate'
        column = 'sub_department'
    elif kind == 'UPC':
        table = 'month_upc_aggregate'
        column = 'upc'

    # ✅ 预先取部门对照字典
    departments_data = getDepartments(None).departments
    id_to_name = {d.id: d.name.get("en_us", "") for d in departments_data}

    with getDB() as conn:
        with conn.cursor() as cursor:
            products = []
            if kind == 'Store':
                # 获取 top product
                monthUPCTable = 'month_upc_max_aggregate' if top_product <= 20 else 'month_upc_aggregate'
                sql = f"""
                    select sum(total_amount) as total_amount, upc 
                    from {monthUPCTable} 
                    where month between '{from_month}' and '{to_month}' 
                    and store in {store} 
                    group by upc 
                    order by sum(total_amount) desc 
                    limit {top_product}
                """
                cursor.execute(sql)
                for row in cursor.fetchall():
                    products.append(Product(totalamount=row[0], upc=getUPC(row[1])))

                sql = f"""
                    select month, store, sum(total_amount) as total_amount, sum(transactions) as transactions
                    from {table}
                    where month between '{from_month}' and '{to_month}' and store in {store}
                    group by store, month
                """
            else:
                sql = f"""
                    select month, store, total_amount, {column}, transactions
                    from {table}
                    where month between '{from_month}' and '{to_month}' and store in {store}
                """
                if UseID:
                    sql += f" and {column} = '{id}'"

            try:
                cursor.execute(sql)
                rows = cursor.fetchall()

                # ✅ 按 kind 获取成本信息
                if kind == 'Department':
                    cost_sql = f"""
                        select store, month, department, sum(cost) as total_cost
                        from cost_imports
                        where month between '{from_month}' and '{to_month}' and store in {store}
                        group by store, month, department
                    """
                    cursor.execute(cost_sql)
                    cost_rows = cursor.fetchall()
                    cost_map = {(row[0], row[1], row[2]): row[3] for row in cost_rows}
                else:
                    cost_sql = f"""
                        select store, month, sum(cost) as total_cost
                        from cost_imports
                        where month between '{from_month}' and '{to_month}' and store in {store}
                        group by store, month
                    """
                    cursor.execute(cost_sql)
                    cost_rows = cursor.fetchall()
                    cost_map = {(row[0], row[1]): row[2] for row in cost_rows}

                items = len(rows)
                total_amount = 0.0
                total_cost = 0.0
                details = []

                for row in rows:
                    if kind == 'Store':
                        # (month, store_name, sale_amount, transactions)
                        month, store_name, sale_amount, transactions = row
                        id_value = ''
                        cost_amount = cost_map.get((store_name, month), 0.0)
                    else:
                        # (month, store_name, sale_amount, id_value, transactions)
                        month, store_name, sale_amount, id_value, transactions = row
                        if kind == 'Department':
                            # 将部门ID转成部门英文名再取成本
                            department_name = id_to_name.get(id_value, "")
                            cost_amount = cost_map.get((store_name, month, department_name), 0.0)
                        else:
                            cost_amount = 0.0

                    gross_profit = float(sale_amount) - float(cost_amount)
                    total_amount += float(sale_amount)
                    total_cost += float(cost_amount)

                    detail = MonthDetail(
                        amount=sale_amount,
                        month=month,
                        store=store_name,
                        idkind=kind,
                        id=id_value,
                        name='',
                        transactions=transactions,
                        cost=cost_amount,
                        grossprofit=gross_profit,
                    )
                    if kind in ('Department', 'SubDepartment') and id_value.isdigit():
                        detail.name = id_to_name.get(id_value, "")
                    details.append(detail)

                end = datetime.datetime.now()
                print(f"month data run time: {end - start} param: {param}")

                return MonthData(
                    summary=MonthSummary(
                        items=items,
                        totalamount=total_amount,
                        totalcost=total_cost,
                        grossprofit=total_amount - total_cost,
                    ),
                    details=details,
                    topproduct=products,
                )
            except Exception as e:
                print(e)
                return MonthData()