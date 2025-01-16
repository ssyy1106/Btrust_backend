import strawberry
import typing
import datetime
from typing import Optional
from strawberry.fastapi import GraphQLRouter
from helper import getDB, getConfig

# 前端查询时需要传参，参数包括时间段，店，部门，统计方式(日，月，年)等信息
@strawberry.input
class DateSearchParameter:
    FromDate: datetime.date = strawberry.field(description="Search from date")
    ToDate: datetime.date = strawberry.field(description="Search to date")
    Store: str = strawberry.field(description="Store name, like MT, NY, TE, MS. ALL", default = "All")
    SearchDepartmentKind: str = strawberry.field(description="Search Department kind include Department, SubDepartment, UPC, Store", default = "Store")
    ID: Optional[str] = strawberry.field(description="Search Department kind ID like departmentid, upcid", default = "")

@strawberry.type
class Summary:
    totalamount: float
    items: int

@strawberry.type
class Detail:
    amount: float
    date: datetime.date

@strawberry.type
class DateData:
    details: typing.List[Detail]
    summary: Summary

def get_data(param: DateSearchParameter) -> DateData:
    from_date, to_date = str(param.FromDate), str(param.ToDate)
    store, kind, id = param.Store, param.SearchDepartmentKind, param.ID
    table = 'day_department_aggregate'
    column = 'department'
    if kind == 'SubDepartment':
        table = 'day_subdepartment_aggregate'
        column = 'subdepartment'
    elif kind == 'UPC':
        table = 'day_upc_aggregate'
        column = 'upc'
    with getDB() as conn:
        cursor = conn.cursor()
        sql = f"select day, store, {column}, total_amount from {table} where day between '{from_date}' and '{to_date}'"
        if store != 'ALL':
            sql += " and store = '" + store + "'"
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            items = len(rows)
            total_amount = 0
            details = []
            for row in rows:
                detail = Detail(amount = row[3], date = datetime.datetime.strptime(row[0], '%Y-%m-%d') )
                total_amount += row[3]
                details.append(detail)
            return DateData(summary = Summary(items=items, totalamount=total_amount), details=details)
        except Exception as e:
            print(e)
        return DateData()

def check(param: DateSearchParameter) -> bool:
    from_date, to_date = param.FromDate, param.ToDate
    store, kind, id = param.Store, param.SearchDepartmentKind, param.ID
    if from_date > to_date:
        return False
    if store not in ['NY', 'MS', 'MT', 'ALL', 'NY']:
        return False
    if kind not in ['Department', 'SubDepartment', 'UPC', 'Store']:
        return False
    return True
    
    
def get_date_data(self, param: DateSearchParameter) -> DateData:
    if not check(param):
        raise Exception("Parameters wrong")
    return get_data(param)
    #return DateData(summary= Summary(totalamount=0.0, items=1), details=[])

@strawberry.type
class Query:
    datedata: DateData = strawberry.field(resolver=get_date_data)

config = getConfig()
schema = strawberry.Schema(query=Query)

graphql_app = GraphQLRouter(schema)
