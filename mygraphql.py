import strawberry
from helper import getConfig
from strawberry.fastapi import GraphQLRouter
from graphqlschema.datedata import getDateData, check_date
from graphqlschema.monthdata import getMonthData, check_month
from graphqlschema.department import getDepartments
#from graphqlschema.yeardata import getYearData, check_year
from graphqlschema.schema import DateSearchParameter, DateData, MonthSearchParameter, MonthData, DepartmentData, DepartmentSearchParameter
     
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

# def get_year_data(param: YearSearchParameter) -> YearData:
#     if not check_year(param):
#         raise Exception("Parameters wrong")
#     return getYearData(param)

@strawberry.type
class Query:
    datedata: DateData = strawberry.field(resolver=get_date_data)
    monthdata: MonthData = strawberry.field(resolver=get_month_data)
    departments: DepartmentData = strawberry.field(resolver=get_departments_data)
    #yeardata: YearData = strawberry.field(resolver=get_year_data)

config = getConfig()
schema = strawberry.Schema(query=Query)

graphql_app = GraphQLRouter(schema)
