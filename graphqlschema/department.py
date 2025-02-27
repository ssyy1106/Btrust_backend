import functools
from helper import getHODB
from graphqlschema.schema import DepartmentSearchParameter, DepartmentData, Department

#@functools.cache
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
                    return DepartmentData(departments = [Department(name = row[1], id = row[0]) for row in rows], items=items)
                return DepartmentData(departments = [], items=items)
            except Exception as e:
                print(e)
                return DepartmentData(departments = [], items=0)