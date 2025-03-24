import datetime
import numbers
from helper import getDB, getPaymentTypes, getStoreStr
from graphqlschema.schema import DateHourData, DateHourSummary, DateHourDetail, DateHourSearchParameter

def check_store_hour(stores, hours) -> bool:
    if len(stores) == 1 and stores[0] not in ['NY', 'MS', 'MT', 'TE', 'ALL']:
        return False
    if len(stores) > 1 and not all(store in ['NY', 'MS', 'MT', 'TE'] for store in stores):
        return False
    if not all(hour >= 0 and hour <=23 and isinstance(hour, numbers.Integral) for hour in hours):
        return False
    return True

def check_hour_date(param: DateHourSearchParameter) -> bool:
    from_date, to_date = param.FromDate, param.ToDate
    stores, hours = param.Store, param.Hour
    if from_date > to_date:
        return False
    return check_store_hour(stores, hours)

def getHourDateData(param: DateHourSearchParameter) -> DateHourData:
    from_date, to_date = param.FromDate, param.ToDate
    stores, hours = getStoreStr(param.Store), param.Hour
    table = 'day_hour_aggregate'
    with getDB() as conn:
        with conn.cursor() as cursor:
            try:
                total_amount_after_tax = 0
                total_amount_before_tax=0

                details = []
                items = 0
                for hour in hours:
                    sql = f"select {hour} as hour, day, store, sum(amount_before_tax) as amount_before_tax, sum(amount_after_tax) as amount_after_tax, sum(transactions) as transactions from {table} where day between '{from_date}' and '{to_date}' and hour = {hour}"
                    sql += " and store in " + stores
                    sql += " group by store, day"
                    cursor.execute(sql)
                    rows = cursor.fetchall()
                    items += len(rows)
                    for row in rows:
                        detail = DateHourDetail(amountbeforetax = row[3], amountaftertax = row[4], date = datetime.datetime.strptime(row[1], '%Y-%m-%d'), store=row[2], hour=row[0], transactions=row[5])
                        total_amount_after_tax += row[4]
                        total_amount_before_tax += row[3]
                        details.append(detail)
                return DateHourData(summary = DateHourSummary(items=items, totalamountbeforetax=total_amount_before_tax, totalamountaftertax=total_amount_after_tax), details=details)
            except Exception as e:
                print(e)
                return DateHourData()
