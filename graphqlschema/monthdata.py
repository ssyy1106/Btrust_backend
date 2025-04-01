import datetime
from helper import getDB, getDepartmentName, getStoreStr
from graphqlschema.schema import MonthData, MonthSummary, MonthDetail, MonthSearchParameter, Product

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
    with getDB() as conn:
        with conn.cursor() as cursor:
            products = []
            if kind == 'Store':
                # get top product info
                monthUPCTable = 'month_upc_max_aggregate' if top_product <= 20 else 'month_upc_aggregate'
                sql = f"select sum(total_amount) as total_amount, upc from {monthUPCTable} where month between '{from_month}' and '{to_month}' and store in {store} group by upc order by sum(total_amount) desc limit {top_product}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                for row in rows:
                    product = Product(totalamount = row[0], upc = row[1])
                    products.append(product)
                sql = f"select month, store, sum(total_amount) as total_amount, store, sum(transactions) from {table} where month between '{from_month}' and '{to_month}'"
                # if store != 'ALL':
                #     sql += " and store = '" + store + "'"
                sql += " and store in " + store
                sql += " group by store, month"
            else:
                sql = f"select month, store, total_amount, {column}, transactions from {table} where month between '{from_month}' and '{to_month}'"
                if UseID:
                    sql += " and " + column + " = '" + id + "'"
                sql += " and store in " + store
                # if store != 'ALL':
                #     sql += " and store = '" + store + "'"
            #print(sql)
            try:
                cursor.execute(sql)
                rows = cursor.fetchall()
                items = len(rows)
                total_amount = 0
                details = []
                for row in rows:
                    transactions = row[4]
                    detail = MonthDetail(amount = row[2], month = row[0], store=row[1], idkind=kind, id=row[3], name = '', transactions=transactions)
                    if (kind == 'Department' or kind == 'SubDepartment') and row[3].isdigit():
                        detail.name = getDepartmentName(int(row[3]))
                    total_amount += row[2]
                    details.append(detail)
                end = datetime.datetime.now()
                print(f"month data run time: {end-start} param: {param}")
                return MonthData(summary = MonthSummary(items=items, totalamount=total_amount), details=details, topproduct=products)
            except Exception as e:
                print(e)
            return MonthData()