"""One-time script to migrate local DuckDB file to MotherDuck.

Usage:
    MOTHERDUCK_TOKEN=eyJ... python infra/scripts/migrate_to_motherduck.py
"""

import os
import sys

import duckdb

LOCAL_DB_PATH = "data/processed/db.duckdb"
MOTHERDUCK_DB = "adrs_warehouse"
TABLES = ["dim_date", "dim_ticker", "fact_stock_prices"]


def main() -> None:
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        print("ERROR: MOTHERDUCK_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    from adrs_warehouse.database.schema import ALL_DDL

    conn = duckdb.connect(f"md:{MOTHERDUCK_DB}?motherduck_token={token}")

    print("Creating schema on MotherDuck...")
    for ddl in ALL_DDL:
        conn.execute(ddl)

    print(f"Attaching local database: {LOCAL_DB_PATH}")
    conn.execute(f"ATTACH '{LOCAL_DB_PATH}' AS local_db (READ_ONLY)")

    for table in TABLES:
        conn.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM local_db.{table}")
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")

    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
