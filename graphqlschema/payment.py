
import datetime
from helper import getDB, getPaymentTypes, getStoreStr, getPaymentTypeStr
from graphqlschema.schema import DatePaymentData, DatePaymentSummary, DatePaymentDetail, DatePaymentSearchParameter, MonthPaymentSearchParameter, MonthPaymentData, MonthPaymentSummary, MonthPaymentDetail

def check_store_payment(stores, paymentType) -> bool:
    if len(stores) == 1 and stores[0] not in ['NY', 'MS', 'MT', 'TE', 'ALL']:
        return False
    if len(stores) > 1 and not all(store in ['NY', 'MS', 'MT', 'TE'] for store in stores):
        return False
    if len(paymentType) == 1 and paymentType[0] not in ['ALL'] + getPaymentTypes():
        return False
    if len(paymentType) > 1 and not all(pm in getPaymentTypes() for pm in paymentType):
        return False
    return True

def check_payment_date(param: DatePaymentSearchParameter) -> bool:
    from_date, to_date = param.FromDate, param.ToDate
    stores, paymentType = param.Store, param.PaymentType
    if from_date > to_date:
        return False
    return check_store_payment(stores, paymentType)

def getPaymentDateData(param: DatePaymentSearchParameter) -> DatePaymentData:
    from_date, to_date = param.FromDate, param.ToDate
    stores = getStoreStr(param.Store)
    all_type_flag, paymentType = getPaymentTypeStr(param.PaymentType)
    table = 'day_payment_aggregate'
    with getDB() as conn:
        with conn.cursor() as cursor:
            try:
                details = []
                # get all sale then sub below sales to get other sale
                if all_type_flag:
                    sql = f"select day, store, sum(amount_before_tax) as amount_before_tax, sum(amount_after_tax) as amount_after_tax, sum(transactions) as transactions from {table} where day between '{from_date}' and '{to_date}'"
                    sql += " and store in " + stores
                    sql += " group by store, day"
                    cursor.execute(sql)
                    store_total = cursor.fetchall()
                    dic = {}
                    for r in store_total:
                        dic[(r[0], r[1])] = DatePaymentDetail(amountbeforetax = r[2], amountaftertax = r[3], transactions=r[4], paymenttype='other', store=r[1], date = datetime.datetime.strptime(r[0], '%Y-%m-%d'))

                for payment in paymentType:
                    sql = f"select '{payment}' as payment_type, day, store, sum(amount_before_tax) as amount_before_tax, sum(amount_after_tax) as amount_after_tax, sum(transactions) as transactions from {table} where day between '{from_date}' and '{to_date}' and starts_with(payment_type, '{payment}')"
                    sql += " and store in " + stores
                    sql += " group by store, day"
                    cursor.execute(sql)
                    rows = cursor.fetchall()
                    for row in rows:
                        detail = DatePaymentDetail(amountbeforetax = row[3], amountaftertax = row[4], date = datetime.datetime.strptime(row[1], '%Y-%m-%d'), store=row[2], paymenttype=row[0], transactions=row[5])
                        # total_amount_after_tax += row[4]
                        # total_amount_before_tax += row[3]
                        details.append(detail)
                        if all_type_flag and (row[1], row[2]) in dic:
                            dic[(row[1], row[2])].amountbeforetax -= detail.amountbeforetax
                            dic[(row[1], row[2])].amountaftertax -= detail.amountaftertax
                            dic[(row[1], row[2])].transactions -= detail.transactions
                if all_type_flag:
                    details.extend(dic.values())
                total_amount_before_tax = sum(d.amountbeforetax for d in details)
                total_amount_after_tax = sum(d.amountaftertax for d in details)
                
                return DatePaymentData(summary = DatePaymentSummary(items=len(details), totalamountbeforetax=total_amount_before_tax, totalamountaftertax=total_amount_after_tax), details=details)
            except Exception as e:
                print(e)
                return DatePaymentData()

def check_payment_month(param: MonthPaymentSearchParameter) -> bool:
    from_month, to_month = param.FromMonth, param.ToMonth
    stores, paymentType = param.Store, param.PaymentType
    if from_month > to_month:
        return False
    return check_store_payment(stores, paymentType)

def getPaymentMonthData(param: MonthPaymentSearchParameter) -> MonthPaymentData:
    from_month, to_month = param.FromMonth, param.ToMonth
    stores = getStoreStr(param.Store)
    all_type_flag, paymentType = getPaymentTypeStr(param.PaymentType)
    table = 'month_payment_aggregate'
    with getDB() as conn:
        with conn.cursor() as cursor:
            try:
                details = []
                dic = {}
                # get all sale then sub below sales to get other sale
                if all_type_flag:
                    sql = f"select month, store, sum(amount_before_tax) as amount_before_tax, sum(amount_after_tax) as amount_after_tax, sum(transactions) as transactions from {table} where month between '{from_month}' and '{to_month}'"
                    sql += " and store in " + stores
                    sql += " group by store, month"
                    cursor.execute(sql)
                    store_total = cursor.fetchall()
                    for r in store_total:
                        dic[(r[0], r[1])] = MonthPaymentDetail(amountbeforetax = r[2], amountaftertax = r[3], transactions=r[4], paymenttype='other', store=r[1], month = r[0])
                for payment in paymentType:
                    sql = f"select '{payment}' as payment_type, month, store, sum(amount_before_tax) as amount_before_tax, sum(amount_after_tax) as amount_after_tax, sum(transactions) as transactions from {table} where month between '{from_month}' and '{to_month}' and starts_with(payment_type, '{payment}')"
                    sql += " and store in " + stores
                    sql += " group by store, month"
                    cursor.execute(sql)
                    rows = cursor.fetchall()
                    for row in rows:
                        detail = MonthPaymentDetail(amountbeforetax = row[3], amountaftertax = row[4], month = row[1], store=row[2], paymenttype=row[0], transactions=row[5])
                        # total_amount_after_tax += row[4]
                        # total_amount_before_tax += row[3]
                        details.append(detail)
                        if all_type_flag and (row[1], row[2]) in dic:
                            dic[(row[1], row[2])].amountbeforetax -= detail.amountbeforetax
                            dic[(row[1], row[2])].amountaftertax -= detail.amountaftertax
                            dic[(row[1], row[2])].transactions -= detail.transactions
                if all_type_flag:
                    details.extend(dic.values())
                total_amount_before_tax = sum(d.amountbeforetax for d in details)
                total_amount_after_tax = sum(d.amountaftertax for d in details)
                return MonthPaymentData(summary = MonthPaymentSummary(items=len(details), totalamountbeforetax=total_amount_before_tax, totalamountaftertax=total_amount_after_tax), details=details)
            except Exception as e:
                print(e)
                return MonthPaymentData()