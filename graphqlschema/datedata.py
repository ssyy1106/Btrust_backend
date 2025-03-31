import datetime
from helper import getDB, getDepartmentName, getStoreStr, log_and_save
from graphqlschema.schema import DateData, DateSummary, DateDetail, DateSearchParameter, Product

def check_date(param: DateSearchParameter) -> bool:
    from_date, to_date = param.FromDate, param.ToDate
    stores, kind, id = param.Store, param.SearchKind, param.SearchID
    if from_date > to_date:
        return False
    if kind not in ['Department', 'SubDepartment', 'UPC', 'Store']:
        return False
    if len(stores) == 1 and stores[0] == "ALL":
        return True
    for store in stores:
        if store not in ['NY', 'MS', 'MT', 'TE']:
            return False
    return True

def getDateData(param: DateSearchParameter) -> DateData:
    start = datetime.datetime.now()
    from_date, to_date = str(param.FromDate), str(param.ToDate)
    store, kind, id = getStoreStr(param.Store), param.SearchKind, param.SearchID
    top_product = param.TopProduct
    table = 'day_department_aggregate'
    column = 'department'
    UseID = True if id else False
    if kind == 'SubDepartment':
        table = 'day_subdepartment_aggregate'
        column = 'sub_department'
    elif kind == 'UPC':
        table = 'day_upc_aggregate'
        column = 'upc'
    with getDB() as conn:
        with conn.cursor() as cursor:
            products = []
            if kind == 'Store':
                # get top product info
                sql = f"select sum(total_amount) as total_amount, upc from day_upc_max_aggregate where day between '{from_date}' and '{to_date}' and store in {store} group by upc order by sum(total_amount) desc limit {top_product}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                for row in rows:
                    product = Product(totalamount = row[0], upc = row[1])
                    products.append(product)
                sql = f"select day, store, sum(total_amount) as total_amount, store, sum(transactions) from {table} where day between '{from_date}' and '{to_date}'"
                # if store != 'ALL':
                sql += " and store in " + store
                sql += " group by store, day"
            else:
                sql = f"select day, store, total_amount, {column}, transactions from {table} where day between '{from_date}' and '{to_date}'"
                if UseID:
                    sql += " and " + column + " = '" + id + "'"
                #if store != 'ALL':
                sql += " and store in " + store
            
            #print(sql)
            try:
                cursor.execute(sql)
                rows = cursor.fetchall()
                items = len(rows)
                total_amount = 0
                details = []
                for row in rows:
                    transactions = row[4]
                    # if kind == 'Store':
                    #     sql = f"select count(1) as transactions from transaction where date = '{row[0]}'"
                    #     sql += f" and store = '{row[1]}'"
                    #     cursor.execute(sql)
                    #     res = cursor.fetchone()
                    #     if res:
                    #         transactions = res[0]
                    detail = DateDetail(amount = row[2], date = datetime.datetime.strptime(row[0], '%Y-%m-%d'), store=row[1], idkind=kind, id=row[3], name = '', transactions=transactions)
                    if (kind == 'Department' or kind == 'SubDepartment') and row[3].isdigit():
                        detail.name = getDepartmentName(int(row[3]))
                    total_amount += row[2]
                    details.append(detail)
                end = datetime.datetime.now()
                print(f"date data run time: {end-start} param: {param}")
                log_and_save('INFO', f"get_date_data end time: {end-start}")
                return DateData(summary = DateSummary(items=items, totalamount=total_amount), details=details, topproduct=products)
            except Exception as e:
                print(e)
            return DateData()