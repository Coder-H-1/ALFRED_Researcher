"""
Researcher/logger.py — Independent Logger for Researcher Repository
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "researcher.log")

_FORMATTER = logging.Formatter(
    fmt="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class FlushingRotatingFileHandler(RotatingFileHandler):
    """Ensures log file writes are immediately flushed to disk."""
    def emit(self, record):
        super().emit(record)
        self.flush()


def get_logger(name: str = "Researcher") -> logging.Logger:
    """Returns a configured logger with console and auto-flushing rotating file handlers."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False

        # Console handler (directed to stderr to protect MCP stdio JSON-RPC stream)
        c_handler = logging.StreamHandler(sys.stderr)
        c_handler.setFormatter(_FORMATTER)
        logger.addHandler(c_handler)

        # File handler with instant flush
        f_handler = FlushingRotatingFileHandler(
            _LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        f_handler.setFormatter(_FORMATTER)
        logger.addHandler(f_handler)

    return logger
