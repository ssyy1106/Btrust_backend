import datetime
from itertools import product
from helper import getDB, getDepartmentName, getStoreStr
from graphqlschema.schema import TopProductSearchParameter, Products, Product

def check_product(param: TopProductSearchParameter) -> bool:
    years, months = param.Years, param.Months
    stores, topProduct = param.Store, param.TopProduct
    if not years or not months:
        return False
    if not all(year >= 1900 and year <= 2200 for year in years) and not all( month >= 1 and month <= 12 for month in months):
        return False
    if len(stores) == 1 and stores[0] == "ALL":
        return True
    if any(store not in ['NY', 'MS', 'MT', 'TE'] for store in stores):
        return False
    return True

def get_months(years, months) -> list[str]:
    def helper(month) -> str:
        if month >= 1 and month < 10:
            return '0' + str(month)
        return str(month)
    return "('" + "','".join(str(y) + '-' + helper(m) for y, m in product(years, months)) + "')"

def getTopProduct(param: TopProductSearchParameter) -> list[Product]:
    start = datetime.datetime.now()
    months = get_months(param.Years, param.Months)
    stores, top_product = getStoreStr(param.Store), param.TopProduct
    table = 'month_upc_aggregate'

    with getDB() as conn:
        with conn.cursor() as cursor:
            products = []
            sql = f"select sum(total_amount) as total_amount, upc from {table} where month in {months} and store in {stores} group by upc order by sum(total_amount) desc limit {top_product}"
            cursor.execute(sql)
            rows = cursor.fetchall()
            for row in rows:
                product = Product(totalamount = row[0], upc = row[1])
                products.append(product)
            end = datetime.datetime.now()
            print(f"top product data run time: {end-start}")
            return Products(product=products)