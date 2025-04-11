import datetime
from collections import defaultdict
from helper import getDB, getDepartmentName, getStoreStr, log_and_save
from graphqlschema.schema import TodaySummary, TodaySearchParameter, TodayDetail, TodayData, TodayDepartmentDetail, TodaySubDepartmentDetail, TodayCashierDetail, Product

def check_today(param: TodaySearchParameter) -> bool:
    stores = param.Store
    if len(stores) == 1 and stores[0] == "ALL":
        return True
    for store in stores:
        if store not in ['NY', 'MS', 'MT', 'TE']:
            return False
    return True

def get_department_details(cursor) -> dict:
    sql = f"select store, sum(total_amount) as total_amount, department, sub_department from sale_item where date = '{datetime.datetime.today().strftime('%Y-%m-%d')}'"
    sql += " group by store, department, sub_department"
    cursor.execute(sql)
    rows = cursor.fetchall()
    res = {}
    for row in rows:
        res[(row[0], row[2], row[3])] = row[1]
    return res

def get_cashier_details(cursor, store) -> dict:
    sql = f"select store, cashier_name, cashier_id, count(1) as transactions, sum(transaction_end_time - transaction_begin_time) as time, sum(transaction_end_time - transaction_begin_time) / count(1) as perTransaction, sum(amount_before_tax) as amount_before_tax, sum(amount_after_tax) as amount_after_tax from transaction where date = '{datetime.datetime.today().strftime('%Y-%m-%d')}'"
    sql += " and store in " + store
    sql += " group by store, cashier_name, cashier_id"
    cursor.execute(sql)
    rows = cursor.fetchall()
    res = {}
    for row in rows:
        res[(row[0], row[2], row[1])] = (row[3], row[4], row[5], row[6], row[7])
    return res

def getTodayData(param: TodaySearchParameter) -> TodayData:
    start = datetime.datetime.now()
    store = getStoreStr(param.Store)
    top_product = param.TopProduct
    with getDB() as conn:
        with conn.cursor() as cursor:
            dic = get_department_details(cursor)
            dic_cashier = get_cashier_details(cursor, store)
            totalamountbeforetax, totalamountaftertax, totalTransactions = 0, 0, 0
            sql = f"select store, count(1) as transactions, sum(amount_before_tax) as amount_before_tax, sum(amount_after_tax) as amount_after_tax from transaction where date = '{datetime.datetime.today().strftime('%Y-%m-%d')}'"
            sql += " and store in " + store
            sql += " group by store"
            try:
                cursor.execute(sql)
                rows = cursor.fetchall()
                details = []
                for row in rows:
                    transactions, store = row[1], row[0]
                    amount_before_tax, amount_after_tax = row[2], row[3]
                    totalamountbeforetax += amount_before_tax
                    totalamountaftertax += amount_after_tax
                    totalTransactions += transactions
                    department = defaultdict(list)
                    cashier = {}
                    for k, v in dic_cashier.items():
                        stor, id, name = k
                        if stor == store:
                            cashier[id] = (name, v)
                    for k, v in dic.items():
                        stor, de, subde = k
                        if stor == store:
                            department[de].append((subde, v))
                    departments = []
                    for k, v in department.items():
                        totalamount = 0
                        subs = []
                        for (subde, subtotalamount) in v:
                            totalamount += subtotalamount
                            subs.append(TodaySubDepartmentDetail(name=getDepartmentName(subde),id=subde,totalamount=subtotalamount))
                        departments.append(TodayDepartmentDetail(name=getDepartmentName(k), id=k,totalamount=totalamount, subdepartments=subs))
                    cashiers = []
                    for id, v in cashier.items():
                        name, item = v[0], v[1]
                        (transactions, time, perTransaction, amount_before_tax, amount_after_tax) = item
                        cashiers.append(TodayCashierDetail(name=name, id=id,transactions=transactions, workingtime=time, timepertransaction=perTransaction, amountbeforetax=amount_before_tax, amountaftertax=amount_after_tax))
                    detail = TodayDetail(amountbeforetax=amount_before_tax, amountaftertax=amount_after_tax, date = datetime.datetime.today(), store=store, transactions=transactions, cashiers=cashiers, departments=departments)
                    details.append(detail)
                # get today best upc sales
                sql = f"select sum(total_amount) as total_amount, upc from sale_item where date = '{datetime.datetime.today().strftime('%Y-%m-%d')}' and store in {store} group by upc order by total_amount desc limit {top_product}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                products = [Product(totalamount = row[0], upc = row[1]) for row in rows]
                end = datetime.datetime.now()
                print(f"today data run time: {end-start} param: {param}")
                log_and_save('INFO', f"get_today_data end time: {end-start}")
                return TodayData(summary = TodaySummary(totalamountbeforetax=totalamountbeforetax, totalamountaftertax=totalamountaftertax, transactions=totalTransactions), details=details, topproduct = products)
            except Exception as e:
                print(e)
            return TodayData()