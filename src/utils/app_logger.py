"""
Application-wide logging configuration.

Provides centralized logging with:
- File output (error.log) for production traceability
- Console output for development
- Company context injection for multi-company debugging
- Consistent format across all modules

Usage:
    from src.utils.app_logger import get_logger
    logger = get_logger(__name__)

    logger.info("Something happened")
    logger.error("Something failed", exc_info=True)

Logs go to:
- error.log file (DEBUG+) — includes module name and company context
- Console (INFO+) in development mode
"""

import logging
import sys
import os

_company_context = ""
_initialized = False


class _CompanyFilter(logging.Filter):
    """Injects the active company name into every log record."""
    def filter(self, record):
        record.company = f"[{_company_context}] " if _company_context else ""
        return True


def set_company_context(company_name: str):
    """Set the active company name for all future log messages.
    Call this once after successful login."""
    global _company_context
    _company_context = company_name


def setup_file_logging(log_path: str) -> str:
    """Initialize file + console logging on the root logger.

    Called once from main.py at startup. All named loggers created
    via get_logger() automatically route here via propagation.

    Returns:
        The actual log file path used (may differ if original was not writable).
    """
    global _initialized
    if _initialized:
        return log_path

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # ── File handler (captures DEBUG and above) ──────────────────────
    try:
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
    except (PermissionError, OSError):
        import tempfile
        log_path = os.path.join(tempfile.gettempdir(), "jk_catalog_error.log")
        file_handler = logging.FileHandler(log_path, encoding='utf-8')

    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(company)s%(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_fmt)
    file_handler.addFilter(_CompanyFilter())
    root.addHandler(file_handler)

    # ── Console handler (INFO and above — less noise) ────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(company)s%(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_fmt)
    console_handler.addFilter(_CompanyFilter())
    root.addHandler(console_handler)

    _initialized = True
    return log_path


def get_logger(name: str = None) -> logging.Logger:
    """Get a named logger.

    All output routes to the root logger's handlers (file + console)
    via Python's built-in propagation. No per-logger handlers needed.

    Args:
        name: Module name (use __name__ for automatic naming).

    Returns:
        Configured Logger instance.
    """
    return logging.getLogger(name or "jk_catalog")
