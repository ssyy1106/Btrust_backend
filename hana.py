import datetime
from classes import SaleItem, Summary, SalesOrder, MonitorData, Response

def getRangeCount(begin: str, end: str, table: str, cursor) -> int:
    cursor.execute(f"SELECT Count(1) FROM {table} where \"DocStatus\"='O' and \"DocDate\" >= '{begin}' and \"DocDate\" <= '{end}'")
    res = cursor.fetchone()
    if res:
        return res[0]
    return 0

def getConfigDays(config) -> tuple:
    today = datetime.datetime.now()
    currentBegin, currentEnd = config['Current']['begin'], config['Current']['end']
    warningBegin, warningEnd = config['Warning']['begin'], config['Warning']['end']
    DangerBegin, DangerEnd = config['Danger']['begin'], config['Danger']['end']
    currentBeginStr, currentEndStr = (today + datetime.timedelta(days=int(currentBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(currentEnd))).strftime('%Y-%m-%d')
    warningBeginStr, warningEndStr = (today + datetime.timedelta(days=int(warningBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(warningEnd))).strftime('%Y-%m-%d')
    DangerBeginStr, DangerEndStr = (today + datetime.timedelta(days=int(DangerBegin))).strftime('%Y-%m-%d'), (today + datetime.timedelta(days=int(DangerEnd))).strftime('%Y-%m-%d')
    return (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr)

def getSalesOrder(cursor, schema, config):
    (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr) = getConfigDays(config)
    cursor.execute(f"SELECT \"DocNum\", \"DocDate\", \"CardCode\", \"CardName\", \"Address\" FROM {schema}.ORDR where \"DocStatus\"='O'")
    res = cursor.fetchall()
    count = 0
    details = []
    for row in res:
        count += 1
        sale = SaleItem(DocNum=str(row[0]), DocDate=str(row[1]), CardCode=row[2], CardName=row[3], Address=row[4])
        details.append(sale)
    current = getRangeCount(currentBeginStr, currentEndStr, schema + '.ORDR', cursor)
    warning = getRangeCount(warningBeginStr, warningEndStr, schema + '.ORDR', cursor)
    danger = getRangeCount(DangerBeginStr, DangerEndStr, schema + '.ORDR', cursor)
    output = SalesOrder(Details=details, Summary=Summary(Total=count, Current=current, Warning=warning, Danger=danger))
    return output 

def getDeliveryOrder(cursor, schema, config):
    (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr) = getConfigDays(config)
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
    (currentBeginStr, currentEndStr, warningBeginStr, warningEndStr, DangerBeginStr, DangerEndStr) = getConfigDays(config)
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