import strawberry
import typing
from helper import getConfig
from secure import verify_jwt_token
from strawberry.fastapi import GraphQLRouter
from strawberry.permission import BasePermission
from graphqlschema.datedata import getDateData, check_date
from graphqlschema.monthdata import getMonthData, check_month
from graphqlschema.department import getDepartments, getSubDepartments
from graphqlschema.upc import getUPCs
from graphqlschema.store import getStores
from graphqlschema.transaction import getTransactions
from graphqlschema.product import getTopProduct, check_product
from starlette.requests import Request
from starlette.websockets import WebSocket
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
    TopProductSearchParameter
)
     
def get_date_data(param: DateSearchParameter) -> DateData:
    if not check_date(param):
        raise Exception("Parameters wrong")
    return getDateData(param)

def get_month_data(param: MonthSearchParameter) -> MonthData:
    if not check_month(param):
        raise Exception("Parameters wrong")
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

class IsAuthenticated(BasePermission):
    message = "User is not authenticated"

    # This method can also be async!
    def has_permission(self, source: typing.Any, info: strawberry.Info, **kwargs) -> bool:
        request: typing.Union[Request, WebSocket] = info.context["request"]
        #print(request.headers)
        if "Authorization" in request.headers:
            #print(request.headers['Authorization'])
            if verify_jwt_token( request.headers['Authorization'][7:] ):
                return True
            return False
            # if result.get("status") == "error":
            #     print(result.get("msg"))
            #     return False
            # if result.get("sub"):
            #     print(result)
            #     return True
        return False
    
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
    #yeardata: YearData = strawberry.field(resolver=get_year_data)

config = getConfig()
schema = strawberry.Schema(query=Query)

graphql_app = GraphQLRouter(schema)
