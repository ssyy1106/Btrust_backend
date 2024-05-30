from classes import SaleItem, Summary, SalesOrder

def getStoreOrder(cursor, table: str) -> SalesOrder:
    strSql = f"select order_no, count(1) as items from {table} where (status='submitted' or status='processing') and updated_at >= Convert(datetime, Convert(char(10), dateadd(DD,-1,getdate()), 126) +' 16:00:00')  group by order_no "
    cursor.execute(strSql)
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate="", CardCode="", CardName="", Address="")
        details.append(sale)
    output = SalesOrder(Details=details, Summary=Summary(Total=count, Current=count, Warning=0, Danger=0))
    return output 

def getPOStoreOrder(cursor):
    return getStoreOrder(cursor, "t_store_po") 

def getPOWareOrder(cursor):
    return getStoreOrder(cursor, "t_warehouse_po") 