import json
import os
from helper import getHODB
from graphqlschema.schema import DepartmentSearchParameter, DepartmentData, Department, SubDepartmentSearchParameter, SubDepartmentData, SubDepartment

def getDepartments(param: DepartmentSearchParameter) -> DepartmentData:
    id = ""
    if param:
        id = param.ID
        # 如果是 invoice 模式，则读取静态文件返回结果
        if getattr(param, "Invoice", False):
            try:
                with open(os.path.join(os.path.dirname(__file__), "invoice_departments.json"), "r", encoding="utf-8") as f:
                    data = json.load(f)
                if id:
                    departments = [
                        Department(id=item["id"], name=item["name"])
                        for item in data if item["id"] == id
                    ]
                else:
                    departments = [
                        Department(id=item["id"], name=item["name"])
                        for item in data
                    ]
                return DepartmentData(departments=departments, items=len(data))
            except Exception as e:
                print(f"Error loading invoice departments: {e}")
                return DepartmentData(departments=[], items=0)

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
                sql = "select F03, F238, F1894 from DEPT_TAB"
                if id:
                    sql = f"select F03, F238, F1894 from DEPT_TAB where F03={id}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                if rows:
                    return DepartmentData(departments = [Department(name = {"en_us": row[1] if row[1] else "", "zh_cn": row[2] if row[2] else ""}, id = row[0]) for row in rows], items=items)
                return DepartmentData(departments = [], items=items)
            except Exception as e:
                print(f"getDepartments err: {e}")
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
                sql = "select F04, F1022, F03, F1120 from SDP_TAB"
                if id:
                    sql = f"select F04, F1022, F03, F1120 from SDP_TAB where F04={id}"
                elif parent_id:
                    sql = f"select F04, F1022, F03, F1120 from SDP_TAB where F03={parent_id}"
                cursor.execute(sql)
                rows = cursor.fetchall()
                if rows:
                    return SubDepartmentData(subdepartments = [SubDepartment(name = {"en_us": row[1] if row[1] else "", "zh_cn": row[3] if row[3] else ""}, id = row[0], parentid = row[2] if row[2] else "") for row in rows], items=items)
                return SubDepartmentData(subdepartments = [], items=items)
            except Exception as e:
                print(f"getSubDepartments err: {e}")
                return SubDepartmentData(subdepartments = [], items=0)
