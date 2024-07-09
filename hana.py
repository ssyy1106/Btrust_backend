import datetime
from classes import ExpirationItem, ExpirationItemSummary, ExpirationItemDetail, SaleItem, Summary, WeekOrderSummary, PickItem, PickDetails, PickListStatus, SalesOrderWeek, WeeklyDataSummary, PickItemDetail, FrozenPickItem, GroceryPickItem

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

def getStartChar(string):
    res = ""
    for char in string:
        if not char.isalpha():
            return res
        res += char
    return res


def getPickRangeCountByDepartment(begin: str, end: str, schema, cursor, department: str, isDanger):

    GroceryCondition = """Detail."ItemCode" LIKE 'SUP%' OR Detail."ItemCode" LIKE 'NFD%' OR Detail."ItemCode" LIKE 'G%'"""
    FrozenCondition = """Detail."ItemCode" LIKE 'FRZ%'"""


    if (not isDanger):
        cursor.execute(f"""
            SELECT
            COUNT(DISTINCT Header."DocEntry")   
            
            FROM
                    
            {schema}.PMX_PLHE AS Header
            JOIN {schema}.PMX_PLLI AS Detail on Header."DocEntry" = Detail."DocEntry"

            where ({FrozenCondition if department == "Frozen" else GroceryCondition}) and  "DocStatus"='C' and "CreateDate" >= '{begin}' and "CreateDate" <= '{end}'""")
    
        closedRes = cursor.fetchone()
    else:
        closedRes = [0]

    cursor.execute(f"""
        SELECT
        COUNT(DISTINCT Header."DocEntry")   
        
        FROM
                   
        {schema}.PMX_PLHE AS Header
        JOIN {schema}.PMX_PLLI AS Detail on Header."DocEntry" = Detail."DocEntry"

        where ({FrozenCondition if department == "Frozen" else GroceryCondition}) and  "DocStatus"='O' and "CreateDate" >= '{begin}' and "CreateDate" <= '{end}'""")
    
    openRes = cursor.fetchone()

    res = {"Open": openRes[0] if openRes else 0, "Close": closedRes[0] if closedRes else 0}
    return res

def getConfigExpiredIntervals(config) -> list:
    res = []
    if 'ExpiredInterval' in config :
        intervals = config['ExpiredInterval']['intervals']
        for interval in intervals.split(','):
            res.append(interval)
    return res

def getConfigExpiredKinds(config) -> list:
    res = []
    if 'ExpiredKinds' in config :
        kinds = config['ExpiredKinds']['kinds']
        for kind in kinds.split(','):
            res.append(kind)
    return res

def getConfigExpiredKindCode(config, kind: str) -> list:
    res = []
    if 'ExpiredKind' in config :
        groups = config['ExpiredKind'][kind]
        for group in groups.split(','):
            res.append(group)
    return res

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
    _,_,_,_,DangerBeginStr, DangerEndStr, weekList = getConfigDays(config)
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.ODLN where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []

    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
    
    deliveryOpenList = [getRangeCount(DangerBeginStr, DangerEndStr, schema + '.ODLN', cursor)]
    deliveryCloseList = [0]

    for weekday in weekList: 
        deliveryOpenList.append(getRangeCount(weekday[0], weekday[1], schema + '.ODLN', cursor))
        deliveryCloseList.append(getRangeCountClosed(weekday[0], weekday[1], schema + '.ODLN', cursor))
    
    output = SalesOrderWeek(Details=details, Summary=WeeklyDataSummary(OpenData=deliveryOpenList, CloseData=deliveryCloseList))
    return output 

def getPurchaseOrder(cursor, schema, config):
    _,_,_,_,DangerBeginStr, DangerEndStr, weekList = getConfigDays(config)
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.OPOR where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []

    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
    
    purchaseOpenList = [getRangeCount(DangerBeginStr, DangerEndStr, schema + '.OPOR', cursor)]
    purchaseCloseList = [0]

    for weekday in weekList: 
        purchaseOpenList.append(getRangeCount(weekday[0], weekday[1], schema + '.OPOR', cursor))
        purchaseCloseList.append(getRangeCountClosed(weekday[0], weekday[1], schema + '.OPOR', cursor))
    
    output = SalesOrderWeek(Details=details, Summary=WeeklyDataSummary(OpenData=purchaseOpenList, CloseData=purchaseCloseList))
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

def getPickListByDepartment(cursor, schema, config):
    _,_,_,_,DangerBeginStr, DangerEndStr, weekList = getConfigDays(config)
    cursor.execute(f"""
        SELECT
        Header."DocEntry",
        Header."CreateDate",
        Header."DestStorLocCode",
        Header."PickPackRemarks",
        Header."CardCode",
        Detail."ItemCode"
                   
        FROM
                   
        {schema}.PMX_PLHE AS Header
        JOIN {schema}.PMX_PLLI AS Detail on Header."DocEntry" = Detail."DocEntry"

        WhERE Header."DocStatus" = 'O'
            """)
    
    res = cursor.fetchall()
    count = 0

    FrozenDetails = []
    FrozenOpenList = [getPickRangeCountByDepartment(DangerBeginStr, DangerEndStr, schema, cursor, "Frozen", True)["Open"]]
    FrozenCloseList = [0]

    GroceryDetails = []
    GroceryOpenList = [getPickRangeCountByDepartment(DangerBeginStr, DangerEndStr, schema, cursor, "Grocery", True)["Open"]]
    GroceryCloseList = [0]

    OtherDetails = []

    FrozenSeenPickListNumber = set()
    GrocerySeenPickListNumber = set()
    OtherSeenPickListNumber = set()

    for row in res:

        PickListNumber = row[0]
        itemCode = row[5]
        count += 1

        pickListDepartment = PickItemDetail(PickListNumber=str(row[0]), CreateDate=str(row[1]), DockNumber=str(row[2]), PickPackRemarks=str(row[3]), CardCode=str(row[4]))

        if (getStartChar(itemCode) == "FRZ"):
            if (PickListNumber not in FrozenSeenPickListNumber):
                FrozenSeenPickListNumber.add(PickListNumber)
                FrozenDetails.append(pickListDepartment)

        elif (getStartChar(itemCode) in ["G", "SUP", "NFD"]):
            if (PickListNumber not in GrocerySeenPickListNumber):
                GrocerySeenPickListNumber.add(PickListNumber)
                GroceryDetails.append(pickListDepartment)
        
        else:
            if (PickListNumber not in OtherSeenPickListNumber):
                OtherSeenPickListNumber.add(PickListNumber)
                OtherDetails.append(pickListDepartment)

    for weekday in weekList: 
        res = getPickRangeCountByDepartment(weekday[0], weekday[1], schema, cursor, "Frozen", False)
        FrozenOpenList.append(res["Open"])
        FrozenCloseList.append(res["Close"])

        res = getPickRangeCountByDepartment(weekday[0], weekday[1], schema, cursor, "Grocery", False)
        GroceryOpenList.append(res["Open"])
        GroceryCloseList.append(res["Close"])

    output = {"Grocery": GroceryPickItem(Details=GroceryDetails, Summary=WeeklyDataSummary(OpenData=GroceryOpenList, CloseData=GroceryCloseList)), "Frozen": FrozenPickItem(Details=FrozenDetails, Summary=WeeklyDataSummary(OpenData=FrozenOpenList, CloseData=FrozenCloseList))}

    return output

def getExpiredSQL(groups: str, month: str, schema: str) -> str:
    group = "".join(groups)
    sql = f"""
            SELECT
            {schema}.OITM."ItemCode",
            {schema}.oitm."ItemName",
            {schema}.oitm."ItmsGrpCod",
            PMX_INVT."Quantity" / {schema}.oitm."NumInBuy" as "Quantity",
            {schema}.oitm."BuyUnitMsr",
            PMX_INVT."SSCC",
            PMX_INVT."StorLocCode",
            {schema}.PMX_OSEL."PmxWhsCode",
            {schema}.PMX_ITRI."BatchNumber",
            {schema}.PMX_ITRI."BestBeforeDate",
            DAYS_BETWEEN(CURRENT_TIMESTAMP ,{schema}.PMX_ITRI."BestBeforeDate" ) "Days Until Expired",
            DAYS_BETWEEN(CURRENT_TIMESTAMP,{schema}.PMX_ITRI."BestBeforeDate" )/30 "Months Until Expired",
            PMX_INVT."ActualFreeQuantity" / {schema}.oitm."NumInBuy" as "FreeQuantity",
            PMX_INVT."QualityStatusCode",
            {schema}.OITM."U_PMX_HSER",
            {schema}.oitm."FrgnName"
                    
            from {schema}.OITM
            inner join {schema}."PMX_FREE_STOCK" PMX_INVT on OITM."ItemCode" = PMX_INVT."ItemCode"
            inner join {schema}.PMX_ITRI on {schema}.PMX_ITRI."InternalKey" = PMX_INVT."ItemTransactionalInfoKey"
            inner join {schema}.PMX_OSEL on PMX_INVT."StorLocCode" = {schema}.PMX_OSEL."Code" 
            where  "BestBeforeDate" <= ADD_MONTHS(CURRENT_TIMESTAMP,{month}) and {schema}.oitm."ItmsGrpCod" in ({group})
            order by case when PMX_INVT."ActualFreeQuantity" = 0 then 1 else 0 end
            , DAYS_BETWEEN(CURRENT_TIMESTAMP,{schema}.PMX_ITRI."BestBeforeDate" ) 
            , "BestBeforeDate"
            """
    return sql

def getExpiredItems(cursor, schema, config):
    months = getConfigExpiredIntervals(config)
    kinds = getConfigExpiredKinds(config)
    res = []
    for kind in kinds:
        groups = getConfigExpiredKindCode(config, kind)
        for month in months:
            details = []
            sql = getExpiredSQL(groups, month, schema)
            cursor.execute(sql)
            items = cursor.fetchall()
            quantity = 0
            for row in items:
                #print(row)
                expirationItemDetail = ExpirationItemDetail(ItemCode=row[0], ItemName=row[1], ItemGrpCode=str(row[2]), Quantity=row[3], BuyUnitMsr=row[4],
                                                            SSCC=str(row[5]), StoreLocCode=row[6],PmxWhsCode=row[7],BatchNumber=row[8],BestBeforeDate=str(row[9]),
                                                            DaysUntilExpired=row[10],MonthsUntilExpired=row[11],FreeQuantity=row[12],FrgnName=row[15])
                details.append(expirationItemDetail)
                quantity += row[12]
            summary = ExpirationItemSummary(Interval = month, Kind = kind, Items = len(items), Quantity=quantity)
            expirationItem = ExpirationItem(Summary = summary, Details = details)
            res.append(expirationItem)
    return res
