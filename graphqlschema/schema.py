import typing
import strawberry
import datetime
from typing import Optional

# 前端查询时需要传参，参数包括时间段，店，部门，统计方式(日，月，年)等信息
@strawberry.input
class DateSearchParameter:
    FromDate: datetime.date = strawberry.field(description="Search from date", default=(datetime.datetime.now() - datetime.timedelta(days=1)).date())
    ToDate: datetime.date = strawberry.field(description="Search to date", default=(datetime.datetime.now() - datetime.timedelta(days=1)).date())
    Store: str = strawberry.field(description="Store name, like MT, NY, TE, MS. ALL", default = "All")
    SearchKind: str = strawberry.field(description="Search Department kind include Department, SubDepartment, UPC, Store", default = "Store")
    SearchID: Optional[str] = strawberry.field(description="Search Department kind ID like departmentid, upcid", default = "")

@strawberry.input
class MonthSearchParameter:
    FromMonth: str = strawberry.field(description="Search from year-month", default=datetime.datetime.now().strftime('%Y-%m'))
    ToMonth: str = strawberry.field(description="Search to year-month", default=datetime.datetime.now().strftime('%Y-%m'))
    Store: str = strawberry.field(description="Store name, like MT, NY, TE, MS. ALL", default = "All")
    SearchKind: str = strawberry.field(description="Search Department kind include Department, SubDepartment, UPC, Store", default = "Store")
    SearchID: Optional[str] = strawberry.field(description="Search Department kind ID like departmentid, upcid", default = "")

@strawberry.input
class YearSearchParameter:
    FromYear: str = strawberry.field(description="Search from year", default=datetime.datetime.now().strftime('%Y'))
    ToYear: str = strawberry.field(description="Search to year", default=datetime.datetime.now().strftime('%Y'))
    Store: str = strawberry.field(description="Store name, like MT, NY, TE, MS. ALL", default = "All")
    SearchKind: str = strawberry.field(description="Search Department kind include Department, SubDepartment, UPC, Store", default = "Store")
    SearchID: Optional[str] = strawberry.field(description="Search Department kind ID like departmentid, upcid", default = "")

@strawberry.input
class DepartmentSearchParameter:
    ID: str = strawberry.field(description="Search Departments with ID", default = "")

@strawberry.input
class SubDepartmentSearchParameter:
    ID: str = strawberry.field(description="Search SubDepartments with ID", default = "")
    ParentID: str = strawberry.field(description="Search SubDepartments with ParentID", default = "")

@strawberry.input
class UPCSearchParameter:
    ID: str = strawberry.field(description="Search UPC with ID", default = "")

@strawberry.type
class DateSummary:
    totalamount: float
    items: int

@strawberry.type
class DateDetail:
    amount: float
    date: datetime.date
    store: str
    id: str
    idkind: str
    name: str

@strawberry.type
class DateData:
    details: typing.List[DateDetail]
    summary: DateSummary

@strawberry.type
class MonthSummary:
    totalamount: float
    items: int

@strawberry.type
class MonthDetail:
    amount: float
    month: str
    store: str
    id: str
    idkind: str
    name: str

@strawberry.type
class MonthData:
    details: typing.List[MonthDetail]
    summary: MonthSummary

@strawberry.type
class Department:
    name: str
    id: str

@strawberry.type
class DepartmentData:
    departments: typing.List[Department]
    items: int
    
@strawberry.type
class SubDepartment:
    name: str
    id: str
    parentid: str

@strawberry.type
class SubDepartmentData:
    subdepartments: typing.List[SubDepartment]
    items: int

@strawberry.type
class UPC:
    nameenglish: str = strawberry.field(description="English name", default = "")
    namechinese: str = strawberry.field(description="Chinese name", default = "")
    id: str

@strawberry.type
class UPCData:
    UPC: typing.List[UPC]
    items: int

# @strawberry.type
# class YearSummary:
#     totalamount: float
#     items: int

# @strawberry.type
# class YearDetail:
#     amount: float
#     year: str
#     store: str
#     id: str
#     idkind: str

# @strawberry.type
# class YearData:
#     details: typing.List[YearDetail]
#     summary: YearSummary