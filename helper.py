import getopt
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
from fastapi import HTTPException, status, Header
from typing import Optional, List
from graphqlschema.schema import (
    UserInformation
)

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

CONFIG = None
def _init(config):
    global CONFIG
    CONFIG = config
        
def log_and_save(level, message):
    log_level = getattr(logging, level)
    logging.log(log_level, message)

def getConfig(type: str = 'dat'):
    configFile = getConfigFile()
    if not configFile:
        return None
    config = configparser.ConfigParser()
    config.read(configFile, encoding="utf-8")
    _init(config)
    setLogging(type)
    return config

@functools.cache
def getPaymentTypes():
    if 'Payment' in CONFIG:
        paymenttypes = CONFIG['Payment']['type'].split(",")
        return paymenttypes
    raise Exception("Sorry, no payment type config")

def getConfigFile():
    configFile = 'config.ini'
    # try:
    #     opts, args = getopt.getopt(sys.argv[1:], "i")
    #     print(f"opts: {opts} args: {args}")
    #     if args:
    #         configFile = args[0]
    #         print(f"config file: {configFile}")
    #     else:
    #         print(f"no config file input, using default ini file")
    # except getopt.GetoptError:
    #     print('reading ini file error')
    #     log_and_save('ERROR', f"Reading ini file error")
    #     return ""
    return configFile

@functools.cache
def getPostgresConfig():
    if 'postgresql' in CONFIG:
        USERNAME = CONFIG['postgresql']['username']
        PASSWORD = CONFIG['postgresql']['password']
        HOST = CONFIG['postgresql']['host']
        DATABASE = CONFIG['postgresql']['database']
        PORT = CONFIG['postgresql']['port']
        return (USERNAME, PASSWORD, HOST, DATABASE, PORT)
    raise Exception("Sorry, no postgresql DB config")

@functools.cache
def getInvoiceConfig():
    if 'postgresqlinvoice' in CONFIG:
        USERNAME = CONFIG['postgresqlinvoice']['username']
        PASSWORD = CONFIG['postgresqlinvoice']['password']
        HOST = CONFIG['postgresqlinvoice']['host']
        DATABASE = CONFIG['postgresqlinvoice']['database']
        PORT = CONFIG['postgresqlinvoice']['port']
        return (USERNAME, PASSWORD, HOST, DATABASE, PORT)
    raise Exception("Sorry, no invoice DB config")

@functools.cache
def getStore():
    if 'stores' in CONFIG:
        stores = CONFIG['stores']['store'].split(",")
        return stores
    raise Exception("Sorry, no stores config")

@functools.cache
def getStoreDescription():
    if 'stores' in CONFIG:
        desc = CONFIG['stores']['description'].split(",")
        return desc
    
    raise Exception("Sorry, no store description config")


@functools.cache
def getHOConfig():
    if 'HOsqlserver' in CONFIG:
        USERNAME = CONFIG['HOsqlserver']['name']
        PASSWORD = CONFIG['HOsqlserver']['password']
        HOST = CONFIG['HOsqlserver']['host']
        DATABASE = CONFIG['HOsqlserver']['database']
        return (USERNAME, PASSWORD, HOST, DATABASE)
    raise Exception("Sorry, no HO DB config")

@functools.cache
def getShiftDBConfig():
    if 'Shiftsqlserver' in CONFIG:
        USERNAME = CONFIG['Shiftsqlserver']['name']
        PASSWORD = CONFIG['Shiftsqlserver']['password']
        HOST = CONFIG['Shiftsqlserver']['host']
        DATABASE = CONFIG['Shiftsqlserver']['database']
        return (USERNAME, PASSWORD, HOST, DATABASE)
    raise Exception("Sorry, no Shift DB config")

def getStoreStr(stores) -> str:
    if len(stores) == 1 and stores[0] == "ALL":
        return "('NY', 'MS', 'MT', 'TE')"
    res = "("
    for store in stores:
        res += "'" + store + "',"
    res = res[: len(res) - 1] + ")"
    return res

def getPaymentTypeStr(paymentType) -> tuple:
    if len(paymentType) == 1 and paymentType[0] == "ALL":
        return (True, getPaymentTypes())
    return (False, paymentType)

def setLogging(type: str):
    file = type + datetime.datetime.now(datetime.timezone.utc).isoformat()[:10]
    directory = '.\\'
    if 'logdirectory' in CONFIG:
        directory = CONFIG['logdirectory'][type + 'directory']
    if not os.path.exists(directory):
        os.makedirs(directory)
    logging.basicConfig(filename=directory + file + '.log', encoding='utf-8', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    print(f"log directory: {directory + file + '.log'}")
    log_and_save('INFO', f"Start......")

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

@functools.cache
def getStoreDBConfig(store: str):
    stores = getStore()
    if store not in stores:
        raise Exception("Sorry, store is not right") 
    index = stores.index(store)
    if 'Storesqlserver' in CONFIG:
        USERNAME = CONFIG['Storesqlserver']['name'].split(",")
        PASSWORD = CONFIG['Storesqlserver']['password'].split(",")
        HOST = CONFIG['Storesqlserver']['host'].split(",")
        DATABASE = CONFIG['Storesqlserver']['database'].split(",")
        return (USERNAME[index], PASSWORD[index], HOST[index], DATABASE[index])
    raise Exception("Sorry, Store db config")

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
        try:
            sql = f"select F238 from DEPT_TAB where F03={id}"
            cursor.execute(sql)
            row = cursor.fetchone()
            if not row:
                sql = f"select F1022 from SDP_TAB where F04={id}"
                cursor.execute(sql)
                row = cursor.fetchone()
            if row:
                return row[0]
            return ""
        except Exception as e:
            print(e)
            return ""
        finally:
            cursor.close()

def LoginShift(btrustId: str, password: str) -> tuple:
    with getShiftDB() as conn:
        with conn.cursor() as cursor:
            try:
                sql = f"select password, salt, id from sysuser where btrustid='{btrustId}'"
                cursor.execute(sql)
                row = cursor.fetchone()
                if not row:
                    return (False, 0)
                if row[0] == EncryptUserPassword(password, row[1]):
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
    stores = {"Terra": "TE", "B1": "MS", "B2": "NY", "Montreal": "MT"}
    with getShiftDB() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"select departmentName from sysdepartment where id = " + str(id))
            name = cursor.fetchone()
            if name:
                if name[0] == 'Btrust':
                    return ['MS', 'NY', 'TE', 'MT']
                if name[0] in stores:
                    return [stores[name[0]]]
                return []
            return []

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
                # get user authorize
                sql =(f"select Authorize from sysuser inner join SysUserBelong on SysUserBelong.userid=SysUser.id"
                    f" inner join SysMenuAuthorize on SysMenuAuthorize.AuthorizeId=sysuserBelong.belongid"
                    f" inner join SysMenu on sysmenu.id= SysMenuAuthorize.MenuId"
                    f" where sysuser.id={userid} and belongtype=2 and Authorize is not null and Authorize<>''")
                cursor.execute(sql)
                rows = cursor.fetchall()
                authorize = [row[0] for row in rows]
                sql = f"select username, realname, departmentname, lastvisit, departmentid from sysuser inner join sysdepartment on departmentid = sysdepartment.id where sysuser.id={userid}"
                cursor.execute(sql)
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

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ATTACHMENT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "uploads"))
# THUMBNAIL_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "thumbnails"))

# def resolve_attachment_path(attachment_path_from_db: str) -> str:
#     # 确保路径是正斜杠格式
#     path = attachment_path_from_db.replace("\\", "/")
    
#     # 判断路径是否包含uploads/或thumbnails/前缀
#     if path.startswith("uploads/"):
#         # 如果路径以uploads/开始，不要去掉uploads/部分，直接拼接
#         return os.path.join(ATTACHMENT_ROOT, path)
#     elif path.startswith("thumbnails/"):
#         # 如果路径以thumbnails/开始，同样直接拼接
#         return os.path.join(THUMBNAIL_ROOT, path)
    
#     # 如果路径没有uploads/或thumbnails/前缀，则默认拼接到uploads目录下
#     return os.path.join(ATTACHMENT_ROOT, path)