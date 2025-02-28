from helper import getHODB
from graphqlschema.schema import DepartmentSearchParameter, DepartmentData, Department, SubDepartmentSearchParameter, SubDepartmentData, SubDepartment

def getDepartments(param: DepartmentSearchParameter) -> DepartmentData:
    id = ""
    if param:
        id = param.ID
    with getHODB() as conn:
        with conn.cursor() as cursor:
            # search from [DEPT_TAB]
            try:
                items = 0
                sql = "select count(1) from DEPT_TAB"
                cursor.execute(sql)
                row = cursor.fetchone()
                if row:
                    items = row[0]
                sql = "select F03, F238 from DEPT_TAB"
                if id:
                    sql = f"select F03, F238 from DEPT_TAB where F03={id}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                if rows:
                    return DepartmentData(departments = [Department(name = row[1] if row[1] else "", id = row[0]) for row in rows], items=items)
                return DepartmentData(departments = [], items=items)
            except Exception as e:
                print(e)
                return DepartmentData(departments = [], items=0)
            
def getSubDepartments(param: SubDepartmentSearchParameter) -> SubDepartmentData:
    id = ""
    parent_id = ""
    if param:
        id = param.ID
        parent_id = param.ParentID
    with getHODB() as conn:
        with conn.cursor() as cursor:
            # search from [SDP_TAB]
            try:
                items = 0
                sql = "select count(1) from SDP_TAB"
                cursor.execute(sql)
                row = cursor.fetchone()
                if row:
                    items = row[0]
                sql = "select F04, F1022, F03 from SDP_TAB"
                if id:
                    sql = f"select F04, F1022, F03 from SDP_TAB where F04={id}"
                elif parent_id:
                    sql = f"select F04, F1022, F03 from SDP_TAB where F03={parent_id}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                if rows:
                    return SubDepartmentData(subdepartments = [SubDepartment(name = row[1] if row[1] else "", id = row[0], parentid = row[2] if row[2] else "") for row in rows], items=items)
                return SubDepartmentData(subdepartments = [], items=items)
            except Exception as e:
                print(e)
                return SubDepartmentData(subdepartments = [], items=0)
