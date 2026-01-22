import duckdb
import pandas as pd
from pathlib import Path


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
    
    def close(self) -> None:
        """Close database connection."""
        self.conn.close()