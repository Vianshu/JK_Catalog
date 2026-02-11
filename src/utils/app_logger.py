"""
Application-wide logging configuration.

Provides a centralized logger factory. All modules should use:

    from src.utils.app_logger import get_logger
    logger = get_logger(__name__)
    
    logger.info("Something happened")
    logger.error("Something failed", exc_info=True)

Logs go to:
- Console (stdout) in development mode
- error.log file in all modes (set up by main.py's setup_crash_logger)
"""

import logging
import sys


def get_logger(name: str = None, level: int = logging.DEBUG) -> logging.Logger:
    """
    Get a named logger with consistent formatting.
    
    Args:
        name: Module name (use __name__ for automatic naming).
        level: Logging level (default: DEBUG for development).
    
    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name or "jk_catalog")
    
    # Avoid adding duplicate handlers
    if not logger.handlers:
        logger.setLevel(level)
        
        # Console handler (for development)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger
