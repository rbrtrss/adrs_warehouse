import datetime
import duckdb
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional

from .schema import ALL_DDL


class ADRDatabase:
    """Handle database operations for ADR data."""

    def __init__(self, db_path: str = ":memory:"):
        """
        Initialize database connection.

        Args:
            db_path: Path to database file. Use ':memory:' for in-memory DB.
        """
        self.conn = duckdb.connect(db_path)

    def create_table_from_dataframe(
        self,
        df: pd.DataFrame,
        table_name: str
    ) -> None:
        """
        Create a table from a pandas DataFrame.

        Args:
            df: Source DataFrame.
            table_name: Name for the new table.
        """
        self.conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM df")

    def query(self, sql: str) -> pd.DataFrame:
        """
        Execute a SQL query and return results as DataFrame.

        Args:
            sql: SQL query string.

        Returns:
            Query results as DataFrame.
        """
        return self.conn.execute(sql).df()

    def create_star_schema(self) -> None:
        """Create the star schema tables (dimensions and fact)."""
        for ddl in ALL_DDL:
            self.conn.execute(ddl)

    def load_dimension(self, df: pd.DataFrame, table_name: str) -> int:
        """
        Load data into a dimension table.

        Args:
            df: DataFrame with dimension data.
            table_name: Target dimension table name.

        Returns:
            Number of rows inserted.
        """
        # Get column order from table schema
        schema = self.conn.execute(f"DESCRIBE {table_name}").df()
        columns = schema["column_name"].tolist()

        # Reorder DataFrame columns to match table schema
        df_ordered = df[columns].copy()

        self.conn.execute(f"DELETE FROM {table_name}")
        self.conn.execute(f"INSERT INTO {table_name} SELECT * FROM df_ordered")
        result = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        return result[0]

    def load_fact(self, df: pd.DataFrame) -> int:
        """
        Load data into the fact table.

        Args:
            df: DataFrame with fact data.

        Returns:
            Number of rows inserted.
        """
        self.conn.execute("DELETE FROM fact_stock_prices")
        self.conn.execute("INSERT INTO fact_stock_prices SELECT * FROM df")
        result = self.conn.execute("SELECT COUNT(*) FROM fact_stock_prices").fetchone()
        return result[0]

    def get_schema_info(self) -> Dict[str, List[Dict]]:
        """
        Get information about the star schema tables.

        Returns:
            Dictionary with table names and their column info.
        """
        tables = ["dim_date", "dim_ticker", "fact_stock_prices"]
        info = {}

        for table in tables:
            try:
                columns = self.conn.execute(
                    f"DESCRIBE {table}"
                ).df().to_dict("records")
                row_count = self.conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                info[table] = {
                    "columns": columns,
                    "row_count": row_count
                }
            except duckdb.CatalogException:
                info[table] = None

        return info

    def get_last_loaded_date(self) -> Optional[datetime.date]:
        """
        Get the maximum date currently loaded in dim_date.

        Returns:
            The latest date, or None if dim_date is empty.
        """
        result = self.conn.execute("SELECT MAX(date) FROM dim_date").fetchone()
        return result[0] if result[0] is not None else None

    def append_dimension(self, df: pd.DataFrame, table_name: str) -> int:
        """
        Append only new rows to a dimension table, skipping duplicates.

        Args:
            df: DataFrame with dimension data.
            table_name: Target dimension table name.

        Returns:
            Number of new rows inserted.
        """
        schema = self.conn.execute(f"DESCRIBE {table_name}").df()
        columns = schema["column_name"].tolist()
        df_ordered = df[columns].copy()

        before = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        self.conn.execute(
            f"INSERT OR IGNORE INTO {table_name} SELECT * FROM df_ordered"
        )
        after = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        return after - before

    def append_fact(self, df: pd.DataFrame) -> int:
        """
        Append only new rows to fact_stock_prices, skipping duplicates.

        Args:
            df: DataFrame with fact data.

        Returns:
            Number of new rows inserted.
        """
        before = self.conn.execute(
            "SELECT COUNT(*) FROM fact_stock_prices"
        ).fetchone()[0]
        self.conn.execute(
            "INSERT OR IGNORE INTO fact_stock_prices SELECT * FROM df"
        )
        after = self.conn.execute(
            "SELECT COUNT(*) FROM fact_stock_prices"
        ).fetchone()[0]
        return after - before

    def update_ticker_dimension(self, df: pd.DataFrame) -> None:
        """
        Update last_trade_date on existing ticker rows.

        Args:
            df: Ticker dimension DataFrame with updated last_trade_date values.
        """
        self.conn.execute("""
            UPDATE dim_ticker
            SET last_trade_date = new_data.last_trade_date
            FROM df AS new_data
            WHERE dim_ticker.ticker_symbol = new_data.ticker_symbol
            AND (
                dim_ticker.last_trade_date IS NULL
                OR new_data.last_trade_date > dim_ticker.last_trade_date
            )
        """)

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()