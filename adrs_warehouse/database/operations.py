import duckdb
import pandas as pd
from pathlib import Path
from typing import Dict, List

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

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()