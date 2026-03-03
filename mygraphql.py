import strawberry
import typing
import asyncio
from functools import cached_property
from helper import getPaymentTypes, log_and_save, verify_jwt_token, get_user_information
from strawberry.fastapi import GraphQLRouter, BaseContext
from strawberry.permission import BasePermission
from graphqlschema.datedata import getDateData, check_date
from graphqlschema.monthdata import getMonthData, check_month
from graphqlschema.department import getDepartments, getSubDepartments
from graphqlschema.upc import getUPCs
from graphqlschema.store import getStores
from graphqlschema.transaction import getTransactions
from graphqlschema.product import getTopProduct, check_product
from graphqlschema.payment import check_payment_date, getPaymentDateData, check_payment_month, getPaymentMonthData
from graphqlschema.hour import check_hour_date, getHourDateData
from graphqlschema.today import check_today, getTodayData
from starlette.requests import Request
from starlette.websockets import WebSocket
from typing import AsyncGenerator
from strawberry.subscriptions import GRAPHQL_TRANSPORT_WS_PROTOCOL, GRAPHQL_WS_PROTOCOL
#from graphqlschema.yeardata import getYearData, check_year
from graphqlschema.schema import (
    DateSearchParameter, 
    DateData, 
    MonthSearchParameter, 
    MonthData, 
    DepartmentData, 
    DepartmentSearchParameter, 
    SubDepartmentData, 
    SubDepartmentSearchParameter, 
    UPCSearchParameter, 
    UPCData, 
    StoreData,
    TransactionSearchParameter,
    TransactionDetail,
    TransactionData,
    Products,
    TopProductSearchParameter,
    PaymentType,
    DatePaymentData,
    MonthPaymentData,
    DatePaymentSearchParameter,
    MonthPaymentSearchParameter,
    DateHourSearchParameter,
    DateHourData,
    UserInformation,
    TodayData,
    TodaySearchParameter,
    Department
)
     
def get_date_data(param: DateSearchParameter) -> DateData:
    if not check_date(param):
        raise Exception("Parameters wrong")
    return getDateData(param)

def get_month_data(param: MonthSearchParameter, info) -> MonthData:
    if not check_month(param):
        raise Exception("Parameters wrong")
    # if info.context.user.store == "Btrust":
    #     print('ok')
    return getMonthData(param)

def get_departments_data(param: DepartmentSearchParameter = None) -> DepartmentData:
    return getDepartments(param)

def get_subdepartments_data(param: SubDepartmentSearchParameter = None) -> SubDepartmentData:
    return getSubDepartments(param)

def get_upc_data(param: UPCSearchParameter = None) -> UPCData:
    return getUPCs(param)

def get_store_data() -> StoreData:
    return getStores()

def get_transaction_data(param: TransactionSearchParameter) -> TransactionData:
    return getTransactions(param)

def get_top_product_data(param: TopProductSearchParameter) -> Products:
    if not check_product(param):
        raise Exception("Parameters wrong")
    return getTopProduct(param)

def get_payment_type_data() -> PaymentType:
    return PaymentType(typename = getPaymentTypes())

def get_date_payment_data(param: DatePaymentSearchParameter) -> DatePaymentData:
    if not check_payment_date(param):
        raise Exception("Parameters wrong")
    return getPaymentDateData(param)

def get_date_hour_data(param: DateHourSearchParameter) -> DateHourData:
    if not check_hour_date(param):
        raise Exception("Parameters wrong")
    return getHourDateData(param)

def get_month_payment_data(param: MonthPaymentSearchParameter) -> MonthPaymentData:
    if not check_payment_month(param):
        raise Exception("Parameters wrong")
    return getPaymentMonthData(param)

def get_today_data(param: TodaySearchParameter) -> TodayData:
    if not check_today(param):
        raise Exception("Parameters wrong")
    return getTodayData(param)

class IsAuthenticated(BasePermission):
    message = "User is not authenticated"

    # This method can also be async!
    def has_permission(self, source: typing.Any, info: strawberry.Info, **kwargs) -> bool:
        #request: typing.Union[Request, WebSocket] = info.context["request"]
        request: typing.Union[Request, WebSocket] = info.context.request
        if "Authorization" in request.headers:
            if verify_jwt_token( request.headers['Authorization'][7:] ):
                return True
            return False
        return False
    
# config = getConfig()

class Context(BaseContext):
    def __init__(self, request: Request | WebSocket | None, response=None):
        super().__init__()
        self.request = request
        self.response = response

    @cached_property
    def user(self) -> UserInformation | None:
        if not self.request:
            return None
        authorization = self.request.headers.get("Authorization", None)
        if authorization:
            return get_user_information(authorization[7:])
        return None

@strawberry.type
class Query:
    datedata: DateData = strawberry.field(resolver=get_date_data,permission_classes=[IsAuthenticated])
    monthdata: MonthData = strawberry.field(resolver=get_month_data,permission_classes=[IsAuthenticated])
    departments: DepartmentData = strawberry.field(resolver=get_departments_data,permission_classes=[IsAuthenticated])
    subdepartments: SubDepartmentData = strawberry.field(resolver=get_subdepartments_data,permission_classes=[IsAuthenticated])
    upc: UPCData = strawberry.field(resolver=get_upc_data,permission_classes=[IsAuthenticated])
    store: StoreData = strawberry.field(resolver=get_store_data,permission_classes=[IsAuthenticated])
    transaction: TransactionData = strawberry.field(resolver=get_transaction_data,permission_classes=[IsAuthenticated])
    topproduct: Products = strawberry.field(resolver=get_top_product_data,permission_classes=[IsAuthenticated])
    paymenttype: PaymentType = strawberry.field(resolver=get_payment_type_data,permission_classes=[IsAuthenticated])
    datepaymentdata: DatePaymentData = strawberry.field(resolver=get_date_payment_data,permission_classes=[IsAuthenticated])
    monthpaymentdata: MonthPaymentData = strawberry.field(resolver=get_month_payment_data,permission_classes=[IsAuthenticated])
    datehourdata: DateHourData = strawberry.field(resolver=get_date_hour_data,permission_classes=[IsAuthenticated])
    todaydata: TodayData = strawberry.field(resolver=get_today_data,permission_classes=[IsAuthenticated])
    @strawberry.field
    def me(self, info: strawberry.Info) -> UserInformation | None:
        #request: typing.Union[Request, WebSocket] = info.context["request"]
        return info.context.user

@strawberry.type
class Subscription:
    @strawberry.subscription
    async def Today(self, timer: int = 5, topproduct: int = 10) -> AsyncGenerator[TodayData, None]:
        try:
            while True:
                yield get_today_data(TodaySearchParameter(Store=['MS'], TopProduct=topproduct))
                #yield chr(ord('a') + i)
                await asyncio.sleep(timer * 60)
        except asyncio.CancelledError:
            print('unsubscription!')
            return


async def get_context(
    request: Request = None,
    websocket: WebSocket = None,
) -> Context:
    return Context(request=request or websocket)

schema = strawberry.Schema(query=Query, subscription=Subscription)

graphql_app = GraphQLRouter(schema, context_getter=get_context, subscription_protocols=[
        GRAPHQL_TRANSPORT_WS_PROTOCOL,
        GRAPHQL_WS_PROTOCOL,
    ],)
#graphql_app = GraphQLRouter(schema)
