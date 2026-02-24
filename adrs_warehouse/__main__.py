import argparse
import sys

from adrs_warehouse.data.fetch import update_warehouse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="adrs-warehouse",
        description="Incrementally update the ADR data warehouse.",
    )
    parser.add_argument(
        "--db-path",
        default="data/processed/db.duckdb",
        help="Path to the DuckDB database file (default: data/processed/db.duckdb)",
    )
    args = parser.parse_args()

    try:
        stats = update_warehouse(db_path=args.db_path)
        print(
            f"Update complete — dim_date: {stats['dim_date']}, "
            f"dim_ticker: {stats['dim_ticker']}, "
            f"fact_stock_prices: {stats['fact_stock_prices']}"
        )
    except Exception as exc:
        print(f"Update failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
