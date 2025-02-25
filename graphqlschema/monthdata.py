import datetime
from helper import getDB, getDepartmentName
from graphqlschema.schema import MonthData, MonthSummary, MonthDetail, MonthSearchParameter

def check_month(param: MonthSearchParameter) -> bool:
    from_month, to_month = param.FromMonth, param.ToMonth
    store, kind, id = param.Store, param.SearchKind, param.SearchID
    if from_month > to_month:
        return False
    if store not in ['NY', 'MS', 'MT', 'ALL', 'TE']:
        return False
    if kind not in ['Department', 'SubDepartment', 'UPC', 'Store']:
        return False
    return True

def getMonthData(param: MonthSearchParameter) -> MonthData:
    from_month, to_month = param.FromMonth, param.ToMonth
    store, kind, id = param.Store, param.SearchKind, param.SearchID
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
        cursor = conn.cursor()
        if kind == 'Store':
            sql = f"select month, store, sum(total_amount) as total_amount, store from {table} where month between '{from_month}' and '{to_month}'"
            if store != 'ALL':
                sql += " and store = '" + store + "'"
            sql += " group by store, month"
        else:
            sql = f"select month, store, total_amount, {column} from {table} where month between '{from_month}' and '{to_month}'"
            if UseID:
                sql += " and " + column + " = '" + id + "'"
            if store != 'ALL':
                sql += " and store = '" + store + "'"
        print(sql)
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            items = len(rows)
            total_amount = 0
            details = []
            for row in rows:
                detail = MonthDetail(amount = row[2], month = row[0], store=row[1], idkind=kind, id=row[3], name = '')
                if (kind == 'Department' or kind == 'SubDepartment') and row[3].isdigit():
                    detail.name = getDepartmentName(int(row[3]))
                total_amount += row[2]
                details.append(detail)
            return MonthData(summary = MonthSummary(items=items, totalamount=total_amount), details=details)
        except Exception as e:
            print(e)
        return MonthData()