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
from enum import Enum

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

def getPaymentTypeStr(paymentType) -> str:
    if len(paymentType) == 1 and paymentType[0] == "ALL":
        return getPaymentTypes()
    return paymentType

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

def LoginShift(btrustId: str, password: str) -> bool:
    with getShiftDB() as conn:
        with conn.cursor() as cursor:
            try:
                sql = f"select password, salt from sysuser where btrustid='{btrustId}'"
                cursor.execute(sql)
                row = cursor.fetchone()
                if not row:
                    return False
                return row[0] == EncryptUserPassword(password, row[1])
            except Exception as e:
                print(e)
                return False

def EncryptUserPassword(password: str, salt: str) -> str:
    md = hashlib.md5(password.encode()).hexdigest()
    return hashlib.md5((md + salt).encode()).hexdigest()
