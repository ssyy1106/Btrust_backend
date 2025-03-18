from helper import getStore, getStoreDB
from graphqlschema.schema import UPC, UPCData, UPCSearchParameter

def getUPCs(param: UPCSearchParameter) -> UPCData:
    store = param.Store
    if store not in getStore():
        return UPCData(UPC = [], items=0)
    id = ""
    if param:
        id = param.ID
    with getStoreDB(store) as conn:
        with conn.cursor() as cursor:
            # search from [OBJ_TAB]
            Table, id_col, name_en, name_ch = 'OBJ_TAB', 'F01', 'F29', 'F255'
            try:
                items = 0
                sql = f"select count(1) from {Table}"
                cursor.execute(sql)
                row = cursor.fetchone()
                if row:
                    items = row[0]
                sql = f"select SUBSTRING({id_col}, PATINDEX('%[^0]%', {id_col}+'.'), LEN({id_col})), {name_ch}, {name_en} from OBJ_TAB"
                if id:
                    sql = f"select SUBSTRING({id_col}, PATINDEX('%[^0]%', {id_col}+'.'), LEN({id_col})), {name_ch}, {name_en} from {Table} where SUBSTRING({id_col}, PATINDEX('%[^0]%', {id_col}+'.'), LEN({id_col}))='{id}'"
                #print(sql)
                cursor.execute(sql)
                rows = cursor.fetchall()
                if rows:
                    return UPCData(UPC = [UPC(namechinese = row[1] if row[1] else "", nameenglish = row[2] if row[2] else "",  id = row[0]) for row in rows], items=items)
                return UPCData(UPC = [], items=items)
            except Exception as e:
                print(e)
                return UPCData(UPC = [], items=0)
            