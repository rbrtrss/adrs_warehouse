import datetime
from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class DatabaseBackend(ABC):
    """Abstract base class for database backends."""

    @abstractmethod
    def create_star_schema(self) -> None:
        """Create the star schema tables (dimensions and fact)."""

    @abstractmethod
    def append_dimension(self, df: pd.DataFrame, table_name: str) -> int:
        """Append only new rows to a dimension table, returning rows inserted."""

    @abstractmethod
    def append_fact(self, df: pd.DataFrame) -> int:
        """Append only new rows to fact_stock_prices, returning rows inserted."""

    @abstractmethod
    def update_ticker_dimension(self, df: pd.DataFrame) -> None:
        """Update last_trade_date on existing ticker rows."""

    @abstractmethod
    def query(self, sql: str) -> pd.DataFrame:
        """Execute a SQL query and return results as DataFrame."""

    @abstractmethod
    def get_schema_info(self) -> dict[str, list[dict]]:
        """Get information about the star schema tables."""

    @abstractmethod
    def get_last_loaded_date(self) -> Optional[datetime.date]:
        """Get the maximum date currently loaded in dim_date."""

    @abstractmethod
    def get_ticker_id_map(self) -> dict[str, int]:
        """Return {ticker_symbol: ticker_id} for all rows in dim_ticker.
        Returns {} if the table is empty or does not exist yet."""

    @abstractmethod
    def create_table_from_dataframe(self, df: pd.DataFrame, table_name: str) -> None:
        """Create a table from a pandas DataFrame."""

    @abstractmethod
    def close(self) -> None:
        """Close the database connection."""
