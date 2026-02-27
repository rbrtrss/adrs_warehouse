import datetime
import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .base import DatabaseBackend
from .schema import ALL_DDL

logger = logging.getLogger(__name__)


class DuckDBDatabase(DatabaseBackend):
    """Handle database operations for ADR data using DuckDB."""

    def __init__(self, db_path: str = ":memory:"):
        """
        Initialize database connection.

        Args:
            db_path: Path to database file. Use ':memory:' for in-memory DB.
        """
        import duckdb

        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(db_path)
        logger.info("Connected to database: %s", db_path)

    def create_table_from_dataframe(self, df: pd.DataFrame, table_name: str) -> None:
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
        logger.info("Star schema created/verified")

    def get_schema_info(self) -> dict[str, list[dict]]:
        """
        Get information about the star schema tables.

        Returns:
            Dictionary with table names and their column info.
        """
        import duckdb

        tables = ["dim_date", "dim_ticker", "fact_stock_prices"]
        info = {}

        for table in tables:
            try:
                columns = self.conn.execute(f"DESCRIBE {table}").df().to_dict("records")
                row_count = self.conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                info[table] = {"columns": columns, "row_count": row_count}
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
        last_date = result[0] if result[0] is not None else None
        logger.debug("Last loaded date: %s", last_date)
        return last_date

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
        df_ordered = df[columns].copy()  # noqa: F841 — used by DuckDB SQL

        before = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        self.conn.execute(
            f"INSERT OR IGNORE INTO {table_name} SELECT * FROM df_ordered"
        )
        after = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        new_rows = after - before
        logger.info(
            "Appended %d new rows to %s (total: %d)", new_rows, table_name, after
        )
        return new_rows

    def append_fact(self, df: pd.DataFrame) -> int:
        """
        Append only new rows to fact_stock_prices, skipping duplicates.

        Args:
            df: DataFrame with fact data.

        Returns:
            Number of new rows inserted.
        """
        before = self.conn.execute("SELECT COUNT(*) FROM fact_stock_prices").fetchone()[
            0
        ]
        self.conn.execute("INSERT OR IGNORE INTO fact_stock_prices SELECT * FROM df")
        after = self.conn.execute("SELECT COUNT(*) FROM fact_stock_prices").fetchone()[
            0
        ]
        new_rows = after - before
        logger.info(
            "Appended %d new rows to fact_stock_prices (total: %d)", new_rows, after
        )
        return new_rows

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
        logger.debug("Ticker dimension updated with latest trade dates")

    def validate_fact_table(self) -> dict[str, int]:
        """Run post-ingestion data quality checks on fact_stock_prices."""
        checks = {
            "null_required_fields": """
                SELECT COUNT(*) FROM fact_stock_prices
                WHERE open_price IS NULL OR high_price IS NULL
                OR low_price IS NULL OR close_price IS NULL
            """,
            "ohlc_violations": """
                SELECT COUNT(*) FROM fact_stock_prices
                WHERE high_price < low_price OR high_price < open_price
                OR high_price < close_price OR low_price > open_price
                OR low_price > close_price
            """,
            "negative_prices": """
                SELECT COUNT(*) FROM fact_stock_prices
                WHERE open_price <= 0 OR high_price <= 0 OR low_price <= 0
                OR close_price <= 0 OR adj_close_price <= 0
            """,
            "negative_volume": """
                SELECT COUNT(*) FROM fact_stock_prices
                WHERE volume < 0
            """,
        }

        violations = {}
        for name, sql in checks.items():
            count = self.conn.execute(sql).fetchone()[0]
            violations[name] = count
            if count > 0:
                logger.warning("Data quality violation — %s: %d row(s)", name, count)

        return violations

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
        logger.info("Database connection closed")


# Backward-compatibility alias
ADRDatabase = DuckDBDatabase


def create_database(provider: str = "duckdb", **kwargs) -> DatabaseBackend:
    """
    Factory function to create a database backend.

    Args:
        provider: Database provider name. Currently supports 'duckdb'.
        **kwargs: Provider-specific arguments (e.g., db_path for duckdb).

    Returns:
        A DatabaseBackend instance.
    """
    logger.info("Creating database backend: %s", provider)
    if provider == "duckdb":
        return DuckDBDatabase(**kwargs)
    raise ValueError(f"Unknown database provider: {provider!r}")
