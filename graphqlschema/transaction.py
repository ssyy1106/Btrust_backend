import datetime
from helper import getStore, getDB
from graphqlschema.schema import TransactionData, TransactionDetail, TransactionSearchParameter, ItemDetail

def validate(date_text):
    try:
        datetime.date.fromisoformat(date_text)
        return True
    except ValueError:
        return False

def getTransactions(param: TransactionSearchParameter) -> TransactionData:
    id = param.ID
    store = param.Store
    date = param.Date
    if not validate(date) or store not in getStore():
        return TransactionData(items=0,details=[])
    
    with getDB() as conn:
        with conn.cursor() as cursor:
            try:
                sql = f"select date, store, transaction_begin_time, amount_before_tax, amount_after_tax," \
                      f" cashier_name, payment_type, total_tax, transaction_end_time, transaction_id from transaction where " \
                      f" store='{store}' and date = '{date}'"
                if id:
                    sql += f" and transaction_id={id}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                items = len(rows)
                details = []
                #datetime.datetime.strptime(row[0], '%Y-%m-%d')
                for row in rows:
                    # search item details if flag set
                    detail_items = 0
                    itemdetail = []
                    if param.SearchDetail == "Yes":
                        transaction_id = row[9]
                        sql = f"select upc, weight, unit_price, total_amount, sub_department, department, total_discount from sale_item where " \
                        f" store='{store}' and date = '{date}' and transaction_id={transaction_id}"
                        cursor.execute(sql)
                        detail_rows = cursor.fetchall()
                        detail_items = len(detail_rows)
                        for item in detail_rows:
                            new_item = ItemDetail(upc=item[0], weight=item[1], unitprice=item[2], amount=item[3], subdepartment=item[4], department=item[5], discount=item[6])
                            itemdetail.append(new_item)
                    detail = TransactionDetail(date = row[0], store=row[1], 
                                            begintime=row[2], endtime=row[8], amountbeforetax=row[3],
                                            amountaftertax=row[4], cashier=row[5], paymenttype=row[6],
                                            tax=row[7],id=row[9],itemdetail=itemdetail, items=detail_items)
                    details.append(detail)
                return TransactionData(items=items, details=details)
            except Exception as e:
                print(e)
                return TransactionData(items=0,details=[])
    