import datetime
from classes import SaleItem, Summary, SalesOrder, MonitorData, Response, WeekOrderSummary, PickItem, PickDetails, PickListStatus, SalesOrderWeek, WeeklyDataSummary

def getRangeCount(begin: str, end: str, table: str, cursor) -> int:
    cursor.execute(f"SELECT Count(1) FROM {table} where \"DocStatus\"='O' and \"DocDate\" >= '{begin}' and \"DocDate\" <= '{end}'")
    res = cursor.fetchone()
    if res:
        return res[0]
    return 0

def getRangeCountClosed(begin: str, end: str, table: str, cursor) -> int:
    cursor.execute(f"SELECT Count(1) FROM {table} where \"DocStatus\"='C' and \"DocDate\" >= '{begin}' and \"DocDate\" <= '{end}'")
    res = cursor.fetchone()
    if res:
        return res[0]
    return 0

def getRangeCountAll(begin: str, end: str, table: str, cursor) -> int:
    cursor.execute(f"SELECT Count(1) FROM {table} where \"DocDate\" >= '{begin}' and \"DocDate\" <= '{end}'")
    res = cursor.fetchone()
    if res:
        return res[0]
    return 0

def getPickRangeCount(begin: str, end: str, table: str, cursor) -> int:
    cursor.execute(f"SELECT Count(1) FROM {table} where \"DocStatus\"='O' and \"CreateDate\" >= '{begin}' and \"CreateDate\" <= '{end}'")
    res = cursor.fetchone()
    if res:
        return res[0]
    return 0


def getConfigDays(config) -> tuple:
    today = datetime.datetime.now()
    currentBegin, currentEnd = config['Current']['begin'], config['Current']['end']
    warningBegin, warningEnd = config['Warning']['begin'], config['Warning']['end']
    DangerBegin, DangerEnd = config['Danger']['begin'], config['Danger']['end']
    weekBegin, weekEnd = config['Week']['weekBegin'], config['Week']['weekEnd']
    currentBeginStr, currentEndStr = (today + datetime.timedelta(days=int(currentBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(currentEnd))).strftime('%Y-%m-%d')
    warningBeginStr, warningEndStr = (today + datetime.timedelta(days=int(warningBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(warningEnd))).strftime('%Y-%m-%d')
    DangerBeginStr, DangerEndStr = (today + datetime.timedelta(days=int(DangerBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(DangerEnd))).strftime('%Y-%m-%d')
    weekList = []
    for weekday in range(int(weekBegin), int(weekEnd) + 1, 1):
        weekList.append([(today + datetime.timedelta(days=int(weekday))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(weekday))).strftime('%Y-%m-%d')])
    return (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr, weekList)

def getSalesOrder(cursor, schema, config):
    _,_,_,_,DangerBeginStr, DangerEndStr, weekList = getConfigDays(config)
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.ORDR where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []

    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
    
    salesOpenList = [getRangeCount(DangerBeginStr, DangerEndStr, schema + '.ORDR', cursor)]
    salesCloseList = [0]

    for weekday in weekList: 
        salesOpenList.append(getRangeCount(weekday[0], weekday[1], schema + '.ORDR', cursor))
        salesCloseList.append(getRangeCountClosed(weekday[0], weekday[1], schema + '.ORDR', cursor))
    
    output = SalesOrderWeek(Details=details, Summary=WeeklyDataSummary(OpenData=salesOpenList, CloseData=salesCloseList))
    return output 

def getDeliveryOrder(cursor, schema, config):
    (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr,_) = getConfigDays(config)
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.ODLN where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
    
    current = getRangeCount(currentBeginStr, currentEndStr, schema + '.ODLN', cursor)
    warning = getRangeCount(warningBeginStr, warningEndStr, schema + '.ODLN', cursor)
    danger = getRangeCount(DangerBeginStr, DangerEndStr, schema + '.ODLN', cursor)
    output = SalesOrder(Details=details, Summary=Summary(Total=count, Current=current, Warning=warning, Danger=danger))
    return output 

def getPurchaseOrder(cursor, schema, config):
    (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr,_) = getConfigDays(config)
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.OPOR where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
    
    current = getRangeCount(currentBeginStr, currentEndStr, schema + '.OPOR', cursor)
    warning = getRangeCount(warningBeginStr, warningEndStr, schema + '.OPOR', cursor)
    danger = getRangeCount(DangerBeginStr, DangerEndStr, schema + '.OPOR', cursor)
    output = SalesOrder(Details=details, Summary=Summary(Total=count, Current=current, Warning=warning, Danger=danger))
    return output 

def getWeekOrderOverview(cursor, schema, config):
    _,_,_,_,_,_, weekList = getConfigDays(config)
    weekPurchase = []
    weekSales = []
    weekDelivery = []    
    # getting purchase, Sales, Delivery weekday orders total
    for weekday in weekList:
        weekPurchase.append(getRangeCountAll(weekday[0], weekday[1], schema + '.OPOR', cursor))
        weekSales.append(getRangeCountAll(weekday[0], weekday[1], schema + '.ORDR', cursor))
        weekDelivery.append(getRangeCountAll(weekday[0], weekday[1], schema + '.ODLN', cursor))

    output = WeekOrderSummary(WeekPurchase=weekPurchase, WeekSales=weekSales, WeekDelivery=weekDelivery)
    return output 

def getPickListStatus(cursor, schema, config):
    (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr,_) = getConfigDays(config)
    cursor.execute(f"SELECT \"DocEntry\", \"CreateDate\", \"CardCode\", \"ShipToCode\", \"ShipToAddress\", \"DestStorLocCode\" FROM {schema}.PMX_PLHE where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        pickList = PickItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4], DockLocation=row[5], NumberOfItems=0,PickDetails=[])
        cursor.execute(f"SELECT \"Dscription\", \"ItemCode\", \"OpenQty\", \"QtyPicked\", \"Quantity\" FROM {schema}.PMX_PLLI where \"DocEntry\"={pickList.DocNum}")
        pickItems = cursor.fetchall()
        itemCount = 0
        for item in pickItems:
            itemCount += 1
            pickList.PickDetails.append(PickDetails(ItemName=str(item[0]), ItemCode=str(item[1]), Open=int(item[2]), Picked=int(item[3]), Total=int(item[4])))
        pickList.NumberOfItems = itemCount
        details.append(pickList)
    
    current = getPickRangeCount(currentBeginStr, currentEndStr, schema + '.PMX_PLHE', cursor)
    warning = getPickRangeCount(warningBeginStr, warningEndStr, schema + '.PMX_PLHE', cursor)
    danger = getPickRangeCount(DangerBeginStr, DangerEndStr, schema + '.PMX_PLHE', cursor)
    output = PickListStatus(Details=details, Summary=Summary(Total=count, Current=current, Warning=warning, Danger=danger))
    return output 