from configparser import ConfigParser
from functools import lru_cache
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.ini"


@lru_cache(maxsize=1)
def get_config():
    # Keep the project's existing %% password escaping convention.
    config = ConfigParser()
    if not config.read(CONFIG_PATH, encoding="utf-8-sig"):
        raise RuntimeError(f"Configuration file not found: {CONFIG_PATH}")
    return config
