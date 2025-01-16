import getopt
import logging
import sys
import datetime
import functools
import psycopg2
import os
import configparser
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
    raise Exception("Sorry, no DB config")

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
