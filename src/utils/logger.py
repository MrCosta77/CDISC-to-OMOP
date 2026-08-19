import logging
import os
from pathlib import Path

# Setup logs directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True) # Creates the 'logs' folder if it doesn't exist

LOG_FILE = LOG_DIR / "pipeline.log"

def get_logger(name):
    """
    Creates a standardized logger that writes to both the console and a log file.
    """
    logger = logging.getLogger(name)
    
    # Only configure if the logger doesn't already have handlers
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Format: [2026-08-19 19:20:30] [INFO] [setup_vocab] - Message
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 1. File Handler (writes to logs/pipeline.log)
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # 2. Console Handler (prints to terminal)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    return logger