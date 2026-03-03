import getopt
from hdbcli import dbapi
import logging
import sys
import datetime
import functools
import psycopg2
import os
import configparser
import pyodbc
import hashlib
import jwt
#from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo
from fastapi import HTTPException, status, Header
from typing import Optional, List
from graphqlschema.schema import (
    UserInformation
)
from config_log_env import get_config


def getStores(user: UserInformation, store: List[str]) -> List[str]:
    if not store:
        return user.store
    if any(st not in user.store for st in store):
        raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You don't have permission to access these stores."
                )
    return store


# 定义一个依赖项：验证 token
def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing token",
        )
    user = get_user_information(authorization[7:])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="wrong token",
        )
    # 可以返回 user 信息或权限等级等
    return user

def log_and_save(level, message):
    log_level = getattr(logging, level)
    logging.log(log_level, message)


LOCAL_TZ = ZoneInfo("America/Montreal")
UTC = ZoneInfo("UTC")

def ensure_aware(dt: datetime.datetime, default_tz=LOCAL_TZ) -> datetime.datetime:
    """
    如果 dt 是 naive，就按 default_tz 解释（这里用本地时区）
    如果 dt 已经 aware，就原样返回
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=default_tz)
    return dt

def to_utc_naive(dt: datetime.datetime) -> datetime.datetime:
    dt = ensure_aware(dt, LOCAL_TZ)
    return dt.astimezone(UTC).replace(tzinfo=None)

@functools.cache
def getPaymentTypes():
    if 'Payment' in get_config():
        paymenttypes = get_config()['Payment']['type'].split(",")
        return paymenttypes
    raise Exception("Sorry, no payment type config")

@functools.cache
def getPostgresConfig():
    if 'postgresql' in get_config():
        USERNAME = get_config()['postgresql']['username']
        PASSWORD = get_config()['postgresql']['password']
        HOST = get_config()['postgresql']['host']
        DATABASE = get_config()['postgresql']['database']
        PORT = get_config()['postgresql']['port']
        return (USERNAME, PASSWORD, HOST, DATABASE, PORT)
    raise Exception("Sorry, no postgresql DB config")

@functools.cache
def getInvoiceConfig():
    if 'postgresqlinvoice' in get_config():
        USERNAME = get_config()['postgresqlinvoice']['username']
        PASSWORD = get_config()['postgresqlinvoice']['password']
        HOST = get_config()['postgresqlinvoice']['host']
        DATABASE = get_config()['postgresqlinvoice']['database']
        PORT = get_config()['postgresqlinvoice']['port']
        return (USERNAME, PASSWORD, HOST, DATABASE, PORT)
    raise Exception("Sorry, no invoice DB config")

@functools.cache
def getStockConfig():
    if 'postgresqlstock' in get_config():
        USERNAME = get_config()['postgresqlstock']['username']
        PASSWORD = get_config()['postgresqlstock']['password']
        HOST = get_config()['postgresqlstock']['host']
        DATABASE = get_config()['postgresqlstock']['database']
        PORT = get_config()['postgresqlstock']['port']
        return (USERNAME, PASSWORD, HOST, DATABASE, PORT)
    raise Exception("Sorry, no stock DB config")

@functools.cache
def getOdooConfig():
    if 'postgresqlodoo' in get_config():
        USERNAME = get_config()['postgresqlodoo']['username']
        PASSWORD = get_config()['postgresqlodoo']['password']
        HOST = get_config()['postgresqlodoo']['host']
        DATABASE = get_config()['postgresqlodoo']['database']
        PORT = get_config()['postgresqlodoo']['port']
        return (USERNAME, PASSWORD, HOST, DATABASE, PORT)
    raise Exception("Sorry, no odoo DB config")

@functools.cache
def getStoreStockConfig():
    if 'postgresqlstorestock' in get_config():
        USERNAME = get_config()['postgresqlstorestock']['username']
        PASSWORD = get_config()['postgresqlstorestock']['password']
        HOST = get_config()['postgresqlstorestock']['host']
        DATABASE = get_config()['postgresqlstorestock']['database']
        PORT = get_config()['postgresqlstorestock']['port']
        return (USERNAME, PASSWORD, HOST, DATABASE, PORT)
    raise Exception("Sorry, no storestock DB config")

@functools.cache
def getCostConfig():
    if 'postgresqlcost' in get_config():
        USERNAME = get_config()['postgresqlcost']['username']
        PASSWORD = get_config()['postgresqlcost']['password']
        HOST = get_config()['postgresqlcost']['host']
        DATABASE = get_config()['postgresqlcost']['database']
        PORT = get_config()['postgresqlcost']['port']
        return (USERNAME, PASSWORD, HOST, DATABASE, PORT)
    raise Exception("Sorry, no cost DB config")

@functools.cache
def getStore():
    if 'stores' in get_config():
        stores = get_config()['stores']['store'].split(",")
        return stores
    raise Exception("Sorry, no stores config")

@functools.cache
def getHRStore():
    if 'stores' in get_config():
        stores = get_config()['stores']['store_hr'].split(",")
        return stores
    raise Exception("Sorry, no stores config")

@functools.cache
def getStoreMapping():
    stores = getStore()
    hr_stores = getHRStore()
    if len(stores) != len(hr_stores):
        raise Exception("Sorry, stores and HR stores config length mismatch")
    mapping = {}
    for i in range(len(stores)):
        mapping[stores[i]] = hr_stores[i]
    return mapping

@functools.cache
def getStoreDescription():
    if 'stores' in get_config():
        desc = get_config()['stores']['description'].split(",")
        return desc
    
    raise Exception("Sorry, no store description config")


@functools.cache
def getHOConfig():
    if 'HOsqlserver' in get_config():
        USERNAME = get_config()['HOsqlserver']['name']
        PASSWORD = get_config()['HOsqlserver']['password']
        HOST = get_config()['HOsqlserver']['host']
        DATABASE = get_config()['HOsqlserver']['database']
        return (USERNAME, PASSWORD, HOST, DATABASE)
    raise Exception("Sorry, no HO DB config")

@functools.cache
def getShiftDBConfig():
    if 'Shiftsqlserver' in get_config():
        USERNAME = get_config()['Shiftsqlserver']['name']
        PASSWORD = get_config()['Shiftsqlserver']['password']
        HOST = get_config()['Shiftsqlserver']['host']
        DATABASE = get_config()['Shiftsqlserver']['database']
        return (USERNAME, PASSWORD, HOST, DATABASE)
    raise Exception("Sorry, no Shift DB config")

def getStoreStr(stores) -> str:
    if len(stores) == 1 and stores[0] == "ALL":
        return "('NY', 'MS', 'MT', 'TE', 'RH')"
    res = "("
    for store in stores:
        res += "'" + store + "',"
    res = res[: len(res) - 1] + ")"
    return res

def getPaymentTypeStr(paymentType) -> tuple:
    if len(paymentType) == 1 and paymentType[0] == "ALL":
        return (True, getPaymentTypes())
    return (False, paymentType)

def getDB():
    try:
        (USERNAME, PASSWORD, HOST, DATABASE, PORT) = getPostgresConfig()
        conn = psycopg2.connect(database=DATABASE,
                                host=HOST,
                                user=USERNAME,
                                password=PASSWORD,
                                port=PORT)
        return conn
    except Exception as e:
        return None

def getHODB():
    try:
        (USERNAME, PASSWORD, HOST, DATABASE) = getHOConfig()
        connectionString = f'DRIVER={{SQL Server}};SERVER={HOST};DATABASE={DATABASE};UID={USERNAME};PWD={PASSWORD}'
        conn = pyodbc.connect(connectionString)
        return conn
    except Exception as e:
        return None

def getShiftDB():
    try:
        (USERNAME, PASSWORD, HOST, DATABASE) = getShiftDBConfig()
        connectionString = f'DRIVER={{SQL Server}};SERVER={HOST};DATABASE={DATABASE};UID={USERNAME};PWD={PASSWORD}'
        conn = pyodbc.connect(connectionString)
        return conn
    except Exception as e:
        return None

def getHanaDB():
    try:
        conn = dbapi.connect(
            address=get_config()['Hana']['address'],
            port=get_config()['Hana']['port'],
            user=get_config()['Hana']['user'],
            password=get_config()['Hana']['password']
        )
        return conn, get_config()['Hana']['schema']
    except Exception as e:
        return None, None

@functools.cache
def getStoreDBConfig(store: str):
    stores = getStore()
    if store not in stores:
        raise Exception("Sorry, store is not right") 
    index = stores.index(store)
    if 'Storesqlserver' in get_config():
        USERNAME = get_config()['Storesqlserver']['name'].split(",")
        PASSWORD = get_config()['Storesqlserver']['password'].split(",")
        HOST = get_config()['Storesqlserver']['host'].split(",")
        DATABASE = get_config()['Storesqlserver']['database'].split(",")
        return (USERNAME[index], PASSWORD[index], HOST[index], DATABASE[index])
    raise Exception("Sorry, Store db config")

@functools.cache
def getLocalStore():
    if 'store' in get_config():
        return (get_config()['store']['store'], get_config()['store']['sqlserver'])
    raise Exception("Sorry, Local Store not config")

@functools.cache
def getOdooAccount():
    if 'odooaccount' in get_config():
        return (get_config()['odooaccount']['host'], get_config()['odooaccount']['username'], get_config()['odooaccount']['password'], get_config()['odooaccount']['db'])
    raise Exception("Sorry, Odoo account not config")

def getStoreDB(store: str):
    try:
        (USERNAME, PASSWORD, HOST, DATABASE) = getStoreDBConfig(store)
        connectionString = f'DRIVER={{SQL Server}};SERVER={HOST};DATABASE={DATABASE};UID={USERNAME};PWD={PASSWORD}'
        conn = pyodbc.connect(connectionString)
        return conn
    except Exception as e:
        print(e)
        return None

@functools.cache
def getDepartmentName(id: str) -> str:
    with getHODB() as conn:
        cursor = conn.cursor()
        # search from [DEPT_TAB] firstly then from [SDP_TAB]
        # 使用参数化查询防止SQL注入
        try:
            sql_dept = "select F238 from DEPT_TAB where F03=?"
            cursor.execute(sql_dept, id)
            row = cursor.fetchone()
            if not row:
                sql_sdp = "select F1022 from SDP_TAB where F04=?"
                cursor.execute(sql_sdp, id)
                row = cursor.fetchone()
            if row:
                return row[0]
            return ""
        except Exception as e:
            print(f"getDepartmentName err {e} id is {id}")
            return ""
        finally:
            cursor.close()

def LoginShift(btrustId: str, password: str) -> tuple:
    with getShiftDB() as conn:
        with conn.cursor() as cursor:
            try:
                # 使用参数化查询防止SQL注入
                sql = "select password, salt, id from sysuser where btrustid=? or email=? or personalemail=?"
                cursor.execute(sql, btrustId, btrustId, btrustId)
                row = cursor.fetchone()
                if not row:
                    return (False, 0)
                if row[0] == EncryptUserPassword(password, row[1]):
                    # 警告: MD5 是一个不安全的哈希算法，请考虑迁移到 bcrypt 或 Argon2。
                    return (True, row[2])
                return (False, 0)
            except Exception as e:
                print(e)
                return (False, 0)

def EncryptUserPassword(password: str, salt: str) -> str:
    md = hashlib.md5(password.encode()).hexdigest()
    return hashlib.md5((md + salt).encode()).hexdigest()

@functools.cache
def getAllDepartmentIds() -> dict:
    res = {}
    with getShiftDB() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"select id, parentid from sysdepartment")
            items = cursor.fetchall()
            for (id, parentId) in items:
                res[id] = parentId
            return res

@functools.cache
def getStoreName(id: str) -> str:
    stores = {"Terra": "TE", "B1": "MS", "B2": "NY", "Montreal": "MT", "BVW": "RH"}
    with getShiftDB() as conn:
        with conn.cursor() as cursor:
            # 使用参数化查询防止SQL注入
            cursor.execute("select departmentName from sysdepartment where id = ?", id)
            name = cursor.fetchone()
            if name:
                if name[0] == 'Btrust':
                    return ['MS', 'NY', 'TE', 'MT', 'RH']
                if name[0] in stores:
                    return [stores[name[0]]]
                return []
            return []

def getStoreNameOdoo(names: list) -> str:
    stores = {"terra": "TE", "mississauga": "MS", "north": "NY", "montreal": "MT", "-rh": "RH"}
    for k, v in stores.items():
        for name in names:
            if k in name.lower():
                return v
    return names[0] if names else ""

@functools.cache
def getStoreWithId(departmentId: int) -> str:
    try:
        deps = getAllDepartmentIds()
        son = departmentId
        store = deps[departmentId]
        father = deps[store]
        grandFather = deps[father]
        while grandFather != 0:
            son = store
            store = father
            father = grandFather
            grandFather = deps[father]
        return son
    except Exception as e:
        return son

SECRET_KEY = "1234567890abC"  # Use a secure key in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
# 警告: 上述 SECRET_KEY 是硬编码的，并且不够安全。在生产环境中，应从环境变量加载一个长而随机的字符串。

# Create JWT Token
def create_jwt_token(data: dict):
    to_encode = data.copy()
    expire = datetime.datetime.now() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire.timestamp()})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Verify JWT Token
def verify_jwt_token(token: str):
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded_token if decoded_token["exp"] >= datetime.datetime.now().timestamp() else None
    except Exception as err:
        print(f"error verify : {err}")
        return None
    # except jwt.PyJWTError:
    #     print('err')
    #     return None
    
def get_user_db(userid) -> UserInformation:
    with getShiftDB() as conn:
        with conn.cursor() as cursor:
            try:
                # 使用参数化查询防止SQL注入
                auth_sql = ("select Authorize from sysuser inner join SysUserBelong on SysUserBelong.userid=SysUser.id"
                            " inner join SysMenuAuthorize on SysMenuAuthorize.AuthorizeId=sysuserBelong.belongid"
                            " inner join SysMenu on sysmenu.id= SysMenuAuthorize.MenuId"
                            " where sysuser.id=? and belongtype=2 and Authorize is not null and Authorize<>''")
                cursor.execute(auth_sql, userid)
                rows = cursor.fetchall()
                authorize = [row[0] for row in rows]
                user_sql = "select username, realname, departmentname, lastvisit, departmentid from sysuser inner join sysdepartment on departmentid = sysdepartment.id where sysuser.id=?"
                cursor.execute(user_sql, userid)
                row = cursor.fetchone()
                if not row:
                    return None
                return UserInformation(id=userid, realname=row[1], username=row[0],lastvisit=row[3], department=row[2],store=getStoreName(getStoreWithId(row[4])), authorize=authorize)
            except Exception as e:
                print(e)
                return None
            
def get_user_information(token: str) -> UserInformation:
    try:
        decode_token = verify_jwt_token(token)
        if decode_token:
            userid = decode_token["sub"]
            return get_user_db(userid)
        return None
    except Exception as err:
        print(err)
        return None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ATTACHMENT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".", "uploads"))
THUMBNAIL_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".", "thumbnails"))

def resolve_attachment_path(attachment_path_from_db: str) -> str:
    path = attachment_path_from_db.replace("\\", "/")
    if path.startswith("uploads/"):
        path = path[len("uploads/"):]
        return os.path.join(ATTACHMENT_ROOT, path)
    elif path.startswith("thumbnails/"):
        path = path[len("thumbnails/"):]
        return os.path.join(THUMBNAIL_ROOT, path)
    return os.path.join(ATTACHMENT_ROOT, path)

