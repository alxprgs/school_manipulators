from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
import sys

try:
    import colorlog
    _HAS_COLORLOG = True
except Exception:
    _HAS_COLORLOG = False

from logging.handlers import RotatingFileHandler

from server.core.paths import LOG_DIR

Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

LOG_FORMAT_CONSOLE = "%(log_color)s%(levelname)-8s:%(reset)s %(message)s"
LOG_FORMAT_CONSOLE_FALLBACK = "%(levelname)-8s: %(message)s"
LOG_FORMAT_FILE = "%(asctime)s | %(levelname)s | %(name)s | %(filename)s:%(lineno)d | %(message)s"

COLOR_CONFIG = {
    "DEBUG":    "cyan",
    "INFO":     "green",
    "WARNING":  "yellow",
    "ERROR":    "red",
    "CRITICAL": "bold_red",
}

log_path = LOG_DIR / f"{datetime.now():%Y-%m-%d}_{os.getpid()}.log"

def _already_has_filehandler(logger: logging.Logger, file_path: Path) -> bool:
    target = str(file_path)
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == target:
            return True
    return False

def _already_has_streamhandler(logger: logging.Logger) -> bool:
    return any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in logger.handlers)

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("server")
    if logger.handlers:  # чтобы не плодить хэндлеры при повторных импортах в тестах
        return logger
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger


logger = _setup_logger()
logger.debug("Логгер инициализирован, файл: %s", log_path)
