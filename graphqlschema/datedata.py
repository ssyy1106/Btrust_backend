import datetime
from helper import getDB, getDepartmentName
from graphqlschema.schema import DateData, DateSummary, DateDetail, DateSearchParameter

def check_date(param: DateSearchParameter) -> bool:
    from_date, to_date = param.FromDate, param.ToDate
    store, kind, id = param.Store, param.SearchKind, param.SearchID
    if from_date > to_date:
        return False
    if store not in ['NY', 'MS', 'MT', 'ALL', 'TE']:
        return False
    if kind not in ['Department', 'SubDepartment', 'UPC', 'Store']:
        return False
    return True

def getDateData(param: DateSearchParameter) -> DateData:
    from_date, to_date = str(param.FromDate), str(param.ToDate)
    store, kind, id = param.Store, param.SearchKind, param.SearchID
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
        cursor = conn.cursor()
        if kind == 'Store':
            sql = f"select day, store, sum(total_amount) as total_amount, store from {table} where day between '{from_date}' and '{to_date}'"
            if store != 'ALL':
                sql += " and store = '" + store + "'"
            sql += " group by store, day"
        else:
            sql = f"select day, store, total_amount, {column} from {table} where day between '{from_date}' and '{to_date}'"
            if UseID:
                sql += " and " + column + " = '" + id + "'"
            if store != 'ALL':
                sql += " and store = '" + store + "'"
        
        #print(sql)
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            items = len(rows)
            total_amount = 0
            details = []
            for row in rows:
                detail = DateDetail(amount = row[2], date = datetime.datetime.strptime(row[0], '%Y-%m-%d'), store=row[1], idkind=kind, id=row[3], name = '')
                if (kind == 'Department' or kind == 'SubDepartment') and row[3].isdigit():
                    detail.name = getDepartmentName(int(row[3]))
                total_amount += row[2]
                details.append(detail)
            return DateData(summary = DateSummary(items=items, totalamount=total_amount), details=details)
        except Exception as e:
            print(e)
        return DateData()