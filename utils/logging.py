

import logging
import os
import psutil
from datetime import datetime

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler()]
)

def log_structured(level, message, *args, **kwargs):
    # Sanitize sensitive data in logs
    SENSITIVE_KEYS = {'phone', 'email', 'name', 'token', 'password'}
    safe_kwargs = {k: (v if k not in SENSITIVE_KEYS else '***') for k, v in kwargs.items()}
    extra = ' '.join(f'{k}={v}' for k, v in safe_kwargs.items())
    log_msg = f"{message} {extra}" if extra else message
    if level == 'DEBUG':
        logging.debug(log_msg)
    elif level == 'INFO':
        logging.info(log_msg)
    elif level == 'WARN':
        logging.warning(log_msg)
    elif level == 'ERROR':
        logging.error(log_msg)
    elif level == 'CRITICAL':
        logging.critical(log_msg)
    else:
        logging.info(log_msg)
    # Add memory usage to all logs
    mem = psutil.virtual_memory()
    logging.info(f"MEMORY_USAGE_MB={mem.used // 1024 // 1024} MEMORY_PERCENT={mem.percent}")
