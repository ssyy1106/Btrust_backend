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
    log_type = 'dat'
    file_name_part = log_type + datetime.datetime.now(datetime.timezone.utc).isoformat()[:10]
    directory = '.\\'
    if 'logdirectory' in config and (log_type + 'directory') in config['logdirectory']:
        directory = config['logdirectory'][log_type + 'directory']

    if not os.path.exists(directory):
        os.makedirs(directory)

    log_filepath = os.path.join(directory, file_name_part + '.log')

    # 获取根日志记录器
    logger = logging.getLogger()
    logger.setLevel(level)

    # 移除任何现有的处理器，以防止日志重复。
    # 这在使用 uvicorn 等会自动添加自己处理器的服务器时很重要。
    if logger.hasHandlers():
        logger.handlers.clear()

    # 创建一个文件处理器
    fh = logging.FileHandler(log_filepath, encoding='utf-8')
    fh.setLevel(level)

    # 创建一个控制台处理器，方便在终端查看日志
    ch = logging.StreamHandler()
    ch.setLevel(level)

    # 创建格式化器并将其添加到处理器中
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    # 将处理器添加到日志记录器
    logger.addHandler(fh)
    logger.addHandler(ch)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
