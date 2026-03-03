import logging
import os
import datetime
from pathlib import Path
import configparser

CONFIG = None

def load_env(env_path: Path):
    """只在启动时显式调用"""
    if not env_path.exists():
        return
    with env_path.open("r", encoding="utf-8") as f:
        for line in f.read().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

def init_config(config_file: Path):
    global CONFIG
    config = configparser.ConfigParser()
    config.read(config_file, encoding="utf-8")
    CONFIG = config
    return config

def get_config() -> configparser.ConfigParser:
    if CONFIG is None:
        raise RuntimeError("Config not initialized. Call init_config first.")
    return CONFIG

def init_logging(level=logging.INFO):
    config = get_config()
    type = 'dat'
    file = type + datetime.datetime.now(datetime.timezone.utc).isoformat()[:10]
    directory = '.\\'
    if 'logdirectory' in config:
        directory = config['logdirectory'][type + 'directory']
    if not os.path.exists(directory):
        os.makedirs(directory)
    logging.basicConfig(
        filename=directory + file + '.log',
        encoding='utf-8',
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

