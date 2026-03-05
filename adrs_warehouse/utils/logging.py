import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the ``adrs_warehouse`` root logger with file and console handlers.

    - **RotatingFileHandler** writes to ``logs/adrs_warehouse.log``
      (5 MB max, 3 backups).
    - **StreamHandler** writes to stderr.

    The function is idempotent — calling it multiple times will not duplicate handlers.

    Args:
        level: Logging level for the console handler.  The file handler always
            captures DEBUG and above.
    """
    logger = logging.getLogger("adrs_warehouse")

    # Avoid adding duplicate handlers on repeated calls (ignore the NullHandler
    # added by the package __init__ for library-safe defaults).
    if any(not isinstance(h, logging.NullHandler) for h in logger.handlers):
        return

    logger.setLevel(logging.DEBUG)

    # --- File handler ---
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    log_dir = os.path.abspath(log_dir)
    os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "adrs_warehouse.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
