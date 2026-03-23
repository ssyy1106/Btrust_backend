import typing
import strawberry
import datetime
from typing import Optional, Union, NewType

JSON = strawberry.scalar(
    NewType("JSON", object),
    description="The `JSON` scalar type represents JSON values as specified by ECMA-404",
    serialize=lambda v: v,
    parse_value=lambda v: v,
)

# 前端查询时需要传参，参数包括时间段，店，部门，统计方式(日，月，年)等信息
def get_default_month():
    return [datetime.datetime.now().month]

def get_all():
    return ['ALL']

def get_hours():
    return [hour for hour in range(8, 23)]

@strawberry.input
class TopProductSearchParameter:
    Years: typing.List[int] = strawberry.field(description="Search years", default=datetime.datetime.now().year)
    Months: typing.List[int] = strawberry.field(description="Search months", default_factory=get_default_month)
    Store: Optional[typing.List[str]] = strawberry.field(description="Store name, like MT, NY, TE, MS, RH, ALL", default_factory=get_all)
    TopProduct: Optional[int] = strawberry.field(description="Search how many top products", default = 10)

@strawberry.input
class DateHourSearchParameter:
    FromDate: datetime.date = strawberry.field(description="Search from date", default=(datetime.datetime.now() - datetime.timedelta(days=1)).date())
    ToDate: datetime.date = strawberry.field(description="Search to date", default=(datetime.datetime.now() - datetime.timedelta(days=1)).date())
    Store: Optional[typing.List[str]] = strawberry.field(description="Store name, like MT, NY, TE, MS, RH, ALL", default_factory=get_all)
    Hour: Optional[typing.List[int]] = strawberry.field(description="Search payment type", default_factory=get_hours)

@strawberry.input
class DatePaymentSearchParameter:
    FromDate: datetime.date = strawberry.field(description="Search from date", default=(datetime.datetime.now() - datetime.timedelta(days=1)).date())
    ToDate: datetime.date = strawberry.field(description="Search to date", default=(datetime.datetime.now() - datetime.timedelta(days=1)).date())
    Store: Optional[typing.List[str]] = strawberry.field(description="Store name, like MT, NY, TE, MS, RH, ALL", default_factory=get_all)
    PaymentType: Optional[typing.List[str]] = strawberry.field(description="Search payment type", default_factory=get_all)

@strawberry.input
class DateSearchParameter:
    FromDate: datetime.date = strawberry.field(description="Search from date", default=(datetime.datetime.now() - datetime.timedelta(days=1)).date())
    ToDate: datetime.date = strawberry.field(description="Search to date", default=(datetime.datetime.now() - datetime.timedelta(days=1)).date())
    Store: typing.List[str] = strawberry.field(description="Store name, like MT, NY, TE, MS, RH, ALL")
    SearchKind: str = strawberry.field(description="Search Department kind include Department, SubDepartment, UPC, Store", default = "Store")
    SearchID: Optional[str] = strawberry.field(description="Search Department kind ID like departmentid, upcid", default = "")
    TopProduct: int = strawberry.field(description="Search how many top products when search kind is Store", default = 10)

@strawberry.input
class MonthPaymentSearchParameter:
    FromMonth: str = strawberry.field(description="Search from year-month", default=datetime.datetime.now().strftime('%Y-%m'))
    ToMonth: str = strawberry.field(description="Search to year-month", default=datetime.datetime.now().strftime('%Y-%m'))
    Store: Optional[typing.List[str]] = strawberry.field(description="Store name, like MT, NY, TE, MS, RH, ALL", default_factory=get_all)
    PaymentType: Optional[typing.List[str]] = strawberry.field(description="Search payment type", default_factory=get_all)

@strawberry.input
class MonthSearchParameter:
    FromMonth: str = strawberry.field(description="Search from year-month", default=datetime.datetime.now().strftime('%Y-%m'))
    ToMonth: str = strawberry.field(description="Search to year-month", default=datetime.datetime.now().strftime('%Y-%m'))
    Store: typing.List[str] = strawberry.field(description="Store name, like MT, NY, TE, MS, RH, ALL")
    SearchKind: str = strawberry.field(description="Search Department kind include Department, SubDepartment, UPC, Store", default = "Store")
    SearchID: Optional[str] = strawberry.field(description="Search Department kind ID like departmentid, upcid", default = "")
    TopProduct: int = strawberry.field(description="Search how many top products when search kind is Store", default = 10)

@strawberry.input
class TransactionSearchParameter:
    Date: str = strawberry.field(description="Search date", default=datetime.datetime.now().strftime('%Y-%m-%d'))
    Store: str = strawberry.field(description="Store name, like MT, NY, TE, MS, RH, ALL", default = "All")
    ID: Optional[str] = strawberry.field(description="Search Transaction using Transaction ID", default="")
    SearchDetail: Optional[str] = strawberry.field(description="Search Transaction detials Yes or No default No", default="No")

@strawberry.input
class TodaySearchParameter:
    Store: Optional[typing.List[str]] = strawberry.field(description="Store name, like MT, NY, TE, MS, RH, ALL", default_factory=get_all)
    TopProduct: int = strawberry.field(description="Search how many top products", default = 10)

@strawberry.input
class DepartmentSearchParameter:
    ID: str = strawberry.field(description="Search Departments with ID", default = "")
    Invoice: Optional[bool] = strawberry.field(description="Search invoice departments", default = False)
    HR: Optional[bool] = strawberry.field(description="Search HR departments", default = False)
    Store: Optional[str] = strawberry.field(description="Search Store departments", default = "")

@strawberry.input
class SubDepartmentSearchParameter:
    ID: str = strawberry.field(description="Search SubDepartments with ID", default = "")
    ParentID: str = strawberry.field(description="Search SubDepartments with ParentID", default = "")

@strawberry.input
class UPCSearchParameter:
    #Store: str = strawberry.field(description="Search UPC with Store MS NY TE MT RH")
    ID: str = strawberry.field(description="Search UPC with ID", default = "")

@strawberry.input
class StoreSearchParameter:
    HR: Optional[bool] = strawberry.field(description="Search HR stores", default = False)

@strawberry.type
class UPC:
    nameenglish: str = strawberry.field(description="English name", default = "")
    namechinese: str = strawberry.field(description="Chinese name", default = "")
    id: str
    
@strawberry.type
class DateSummary:
    totalamount: float
    items: int

@strawberry.type
class Product:
    totalamount: float
    upc: UPC

@strawberry.type
class Products:
    product: typing.List[Product]

@strawberry.type
class PaymentType:
    typename: typing.List[str]

@strawberry.type
class DateDetail:
    amount: float
    date: datetime.date
    store: str
    id: str
    idkind: str
    name: str
    transactions: int

@strawberry.type
class DateData:
    details: typing.List[DateDetail]
    summary: DateSummary
    topproduct: typing.List[Product]

@strawberry.type
class DatePaymentSummary:
    totalamountbeforetax: float
    totalamountaftertax: float
    items: int

@strawberry.type
class DatePaymentDetail:
    amountbeforetax: float
    amountaftertax: float
    date: datetime.date
    store: str
    paymenttype: str
    transactions: int

@strawberry.type
class DatePaymentData:
    details: typing.List[DatePaymentDetail]
    summary: DatePaymentSummary

@strawberry.type
class DateHourSummary:
    totalamountbeforetax: float
    totalamountaftertax: float
    items: int

@strawberry.type
class DateHourDetail:
    amountbeforetax: float
    amountaftertax: float
    date: datetime.date
    store: str
    hour: int
    transactions: int

@strawberry.type
class DateHourData:
    details: typing.List[DateHourDetail]
    summary: DateHourSummary

@strawberry.type
class TodaySummary:
    totalamountbeforetax: float
    totalamountaftertax: float
    transactions: int

@strawberry.type
class TodaySubDepartmentDetail:
    name: str
    id: str
    totalamount: float

@strawberry.type
class TodayCashierDetail:
    name: str
    id: str
    transactions: int
    workingtime: str
    timepertransaction: str
    amountbeforetax: float
    amountaftertax: float

@strawberry.type
class TodayDepartmentDetail:
    name: str
    id: str
    totalamount: float
    subdepartments: typing.List[TodaySubDepartmentDetail]

@strawberry.type
class TodayDetail:
    amountbeforetax: float
    amountaftertax: float
    date: datetime.date
    store: str
    transactions: int
    departments: typing.List[TodayDepartmentDetail]
    cashiers: typing.List[TodayCashierDetail]

@strawberry.type
class TodayData:
    details: typing.List[TodayDetail]
    summary: TodaySummary
    topproduct: typing.List[Product] 

@strawberry.type
class UserInformation:
    id: str
    realname: str
    username: str
    department: str
    store: typing.List[str]
    lastvisit: str
    authorize: typing.List[str] 

@strawberry.type
class MonthPaymentSummary:
    totalamountbeforetax: float
    totalamountaftertax: float
    items: int

@strawberry.type
class MonthPaymentDetail:
    amountbeforetax: float
    amountaftertax: float
    month: str
    store: str
    paymenttype: str
    transactions: int

@strawberry.type
class MonthPaymentData:
    details: typing.List[MonthPaymentDetail]
    summary: MonthPaymentSummary

@strawberry.type
class MonthSummary:
    totalamount: float
    items: int
    totalcost: float  # 新增
    grossprofit: float  # 新增

@strawberry.type
class MonthDetail:
    amount: float
    month: str
    store: str
    id: str
    idkind: str
    name: str
    transactions: int
    cost: float  # 新增
    grossprofit: float  # 新增

@strawberry.type
class MonthData:
    details: typing.List[MonthDetail]
    summary: MonthSummary
    topproduct: typing.List[Product] 

@strawberry.type
class ItemDetail:
    upc: str
    weight: str
    unitprice: str
    amount: str
    subdepartment: str
    department: str
    discount: str

@strawberry.type
class TransactionDetail:
    date: str
    begintime: str
    endtime: str
    id: str
    paymenttype: str
    cashier: str
    store: str
    amountbeforetax: float
    amountaftertax: float
    tax: float
    itemdetail: typing.List[ItemDetail]
    items: int

@strawberry.type
class StoreDetail:
    ID: str
    Description: str

@strawberry.type
class StoreData:
    stores: typing.List[StoreDetail]
    items: int

@strawberry.type
class TransactionData:
    details: typing.List[TransactionDetail]
    items: int

@strawberry.type
class Department:
    name: JSON
    id: str

@strawberry.type
class DepartmentData:
    departments: typing.List[Department]
    items: int
    
@strawberry.type
class SubDepartment:
    name: JSON
    id: str
    parentid: str

@strawberry.type
class SubDepartmentData:
    subdepartments: typing.List[SubDepartment]
    items: int

@strawberry.type
class UPCData:
    UPC: typing.List[UPC]
    items: int
