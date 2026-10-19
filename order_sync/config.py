
import os
from configparser import ConfigParser
from functools import lru_cache
from pathlib import Path

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Use APP_CONFIG_FILE if provided; otherwise use config.ini
config_file = os.getenv("APP_CONFIG_FILE", "config.ini")

CONFIG_PATH = Path(config_file)

# Resolve relative paths from project root
if not CONFIG_PATH.is_absolute():
    CONFIG_PATH = PROJECT_ROOT / CONFIG_PATH


@lru_cache(maxsize=1)
def get_config():
    # Keep the project's existing %% password escaping convention.
    config = ConfigParser()

    if not config.read(CONFIG_PATH, encoding="utf-8-sig"):
        raise RuntimeError(
            f"Configuration file not found: {CONFIG_PATH}"
        )

    return config
