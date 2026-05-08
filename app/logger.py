
import logging
import sys
import os
from uvicorn.config import LOGGING_CONFIG

def setup_logging():
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    # Format: [Time] [Level] [Module] Message
    log_format = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Configure uvicorn loggers to match
    LOGGING_CONFIG["formatters"]["access"]["fmt"] = '%(asctime)s [%(levelname)s] [%(name)s] %(message)s'
    LOGGING_CONFIG["formatters"]["default"]["fmt"] = '%(asctime)s [%(levelname)s] [%(name)s] %(message)s'
    LOGGING_CONFIG["formatters"]["access"]["datefmt"] = date_format
    LOGGING_CONFIG["formatters"]["default"]["datefmt"] = date_format
    
    # Set levels for specific loggers if needed
    logging.getLogger("uvicorn.access").setLevel(numeric_level)
    logging.getLogger("uvicorn.error").setLevel(numeric_level)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING) # Too verbose on debug

    return logging.getLogger("dingwatch")

logger = setup_logging()
