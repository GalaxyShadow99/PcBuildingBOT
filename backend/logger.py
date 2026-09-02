import logging
import os
from dotenv import load_dotenv

load_dotenv()

ENVIRONEMENT_TYPE = os.environ.get("ENVIRONEMENT_TYPE", "development")

class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

logger = logging.getLogger("LBCBot")

if ENVIRONEMENT_TYPE == "production":
    logger.setLevel(logging.ERROR)
else:
    logger.setLevel(logging.DEBUG)


if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(CustomFormatter())
    logger.addHandler(ch)
logger.propagate = False

# Désactiver les logs HTTP verbeux de httpx
if ENVIRONEMENT_TYPE == "production":
    logging.getLogger("httpx").setLevel(logging.ERROR)
else:
    logging.getLogger("httpx").setLevel(logging.WARNING)
