from helper import getHODB
from graphqlschema.schema import UPC, UPCData, UPCSearchParameter

def getUPCs(param: UPCSearchParameter) -> UPCData:
    id = ""
    if param:
        id = param.ID
    with getHODB() as conn:
        with conn.cursor() as cursor:
            # search from [DEPT_TAB]
            try:
                items = 0
                sql = "select count(1) from OBJ_TAB"
                cursor.execute(sql)
                row = cursor.fetchone()
                if row:
                    items = row[0]
                sql = "select F01, F255, F29 from OBJ_TAB"
                if id:
                    sql = f"select F01, F255, F29 from OBJ_TAB where F01={id}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                if rows:
                    return UPCData(UPC = [UPC(namechinese = row[1] if row[1] else "", nameenglish = row[2] if row[2] else "",  id = row[0]) for row in rows], items=items)
                return UPCData(UPC = [], items=items)
            except Exception as e:
                print(e)
                return UPCData(UPC = [], items=0)
            