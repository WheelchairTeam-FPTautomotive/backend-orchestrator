"""
Logging subsystem for the backend orchestrator.

Configures a single stdout stream handler so that application logs are captured
natively by AWS CloudWatch Logs without requiring any local filesystem access.
"""

import logging
import os
import sys


def get_log_level(level_name: str | None) -> int:
    """Resolve a log-level name to a logging level integer."""
    if level_name is None:
        return logging.INFO
    return getattr(logging, level_name.upper(), logging.INFO)


def setup_logging(name: str = "kms_orchestrator") -> logging.Logger:
    """
    Configure the application logger.

    Returns a logger that writes exclusively to stdout. This avoids any
    dependency on a writable local filesystem, which is essential for
    Fargate tasks with read-only root filesystems.
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

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger.info("Logging initialised: stdout only")
    return logger
