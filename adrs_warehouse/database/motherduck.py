import logging
from typing import Optional

import duckdb

from .operations import DuckDBDatabase

logger = logging.getLogger(__name__)


class MotherDuckDatabase(DuckDBDatabase):
    def __init__(self, database: str = "adrs_warehouse", token: Optional[str] = None):
        connection_string = f"md:{database}"
        if token:
            connection_string = f"md:{database}?motherduck_token={token}"
        self.conn = duckdb.connect(connection_string)
        logger.info("Connected to MotherDuck: %s", database)
