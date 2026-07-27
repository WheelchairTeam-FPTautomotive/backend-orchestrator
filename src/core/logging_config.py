"""
Logging subsystem for the backend orchestrator.

Initialises a rotating file handler plus a stdout stream handler so that
application logs are both human-readable in the console and durably persisted
on disk with automatic size-based rotation.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILE = "orchestrator.log"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
DEFAULT_BACKUP_COUNT = 5


def get_log_level(level_name: str | None) -> int:
    """Resolve a log-level name to a logging level integer."""
    if level_name is None:
        return logging.INFO
    return getattr(logging, level_name.upper(), logging.INFO)


def setup_logging(
    name: str = "kms_orchestrator",
    log_dir: str | None = None,
    log_file: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> logging.Logger:
    """
    Configure the application logger.

    Returns a logger with two handlers:
      1. A console handler writing to stdout.
      2. A rotating file handler that splits files at `max_bytes` and keeps
         `backup_count` historical files to prevent unbounded disk growth.
    """
    logger = logging.getLogger(name)
    logger.setLevel(get_log_level(os.getenv("LOG_LEVEL")))

    # Avoid attaching duplicate handlers if setup_logging is called multiple times.
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # stdout / stderr capture
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # Rotating file handler
    target_dir = log_dir or os.getenv("LOG_DIR", DEFAULT_LOG_DIR)
    os.makedirs(target_dir, exist_ok=True)

    target_file = log_file or DEFAULT_LOG_FILE
    file_path = os.path.join(target_dir, target_file)

    file_handler = RotatingFileHandler(
        filename=file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info("Logging initialised: console + rotating file (%s)", file_path)
    return logger
