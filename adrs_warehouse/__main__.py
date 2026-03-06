import argparse
import sys

from adrs_warehouse.data.fetch import add_tickers, update_warehouse


def main() -> None:
    db_path_parent = argparse.ArgumentParser(add_help=False)
    db_path_parent.add_argument(
        "--db-path",
        default="data/processed/db.duckdb",
        help="Path to the DuckDB database file (default: data/processed/db.duckdb)",
    )

    parser = argparse.ArgumentParser(
        prog="adrs-warehouse",
        description="Manage the ADR data warehouse.",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    # --- update subcommand ---
    subparsers.add_parser(
        "update",
        parents=[db_path_parent],
        help="Incrementally fetch and load new price data for all tracked tickers.",
    )

    # --- add-tickers subcommand ---
    p_add = subparsers.add_parser(
        "add-tickers",
        parents=[db_path_parent],
        help="Perform a full historical load for one or more new ticker symbols.",
    )
    p_add.add_argument(
        "tickers",
        nargs="+",
        metavar="TICKER",
        help="Ticker symbol(s) to add (e.g. GLOB MELI).",
    )

    args = parser.parse_args()

    try:
        if args.command == "update":
            stats = update_warehouse(db_path=args.db_path)
            print(
                f"Update complete — dim_date: {stats['dim_date']}, "
                f"dim_ticker: {stats['dim_ticker']}, "
                f"fact_stock_prices: {stats['fact_stock_prices']}"
            )
        else:  # add-tickers
            stats = add_tickers(args.tickers, db_path=args.db_path)
            print(
                f"Add complete — dim_date: {stats['dim_date']}, "
                f"dim_ticker: {stats['dim_ticker']}, "
                f"fact_stock_prices: {stats['fact_stock_prices']}"
            )
    except Exception as exc:
        print(f"Command failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
