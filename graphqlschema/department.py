import json
import os
from collections import defaultdict
from helper import getHODB
from graphqlschema.schema import DepartmentSearchParameter, DepartmentData, Department, SubDepartmentSearchParameter, SubDepartmentData, SubDepartment

def get_hr_departments(param: DepartmentSearchParameter) -> DepartmentData:
    try:
        # 获取当前文件 (department.py) 的目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 构建 json 文件的绝对路径: ../routers/report/hr_departments_mapping.json
        json_path = os.path.join(current_dir, '..', 'routers', 'report', 'hr_departments_mapping.json')
        
        # 规范化路径
        json_path = os.path.abspath(json_path)

        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                mappings = json.load(f)
            
            # 查找匹配的 store
            if getattr(param, 'Store', None):
                store_info = next((item for item in mappings if item['name'] == param.Store), None)
            else:
                store_info = None
            dic_departments = defaultdict(bool)
            # 定义递归函数来构建全名 (Fullname)
            def collect_departments(depts, parent_name=""):
                for dept in depts:
                    # 拼接名称，如果存在父级名称则为 "Parent/Child"，否则为 "Child"
                    full_name = f"{parent_name}/{dept['name']}" if parent_name else dept['name']
                    # 创建 Department 对象
                    dept_entry = Department(id=dept["id"], name={
                            "en_us": full_name
                        })
                    if full_name not in dic_departments:
                        department_list.append(dept_entry)
                    dic_departments[full_name] = True
                    
                    # 递归处理子部门
                    if dept.get("departments"):
                        collect_departments(dept["departments"], full_name)
            department_list = []
            if store_info:
                # 开始遍历该门店的顶层部门
                collect_departments(store_info.get("departments", []))
                return DepartmentData(departments=department_list, items=len(department_list))
            for store in mappings:
                collect_departments(store.get("departments", []))
            return DepartmentData(departments=department_list, items=len(department_list))

    except Exception as e:
        print(f"Error reading HR departments mapping: {e}")
        # 发生错误时，可以选择返回空数据或继续执行原有逻辑
        pass

def getDepartments(param: DepartmentSearchParameter) -> DepartmentData:
    id = ""
    if param:
        id = param.ID
        if getattr(param, 'HR', None):
            return get_hr_departments(param)
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
