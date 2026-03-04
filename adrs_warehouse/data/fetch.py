import logging
from datetime import timedelta
from typing import Optional, TypedDict

import pandas as pd
import yfinance as yf

from ..config import AR_ADRS, START_DATE, TICKER_METADATA
from ..database.base import DatabaseBackend
from ..database.operations import create_database
from ..utils.logging import setup_logging
from . import transform

logger = logging.getLogger(__name__)


class WarehouseUpdateResult(TypedDict):
    dim_date: int
    dim_ticker: int
    fact_stock_prices: int
    violations: dict[str, int]


def download_adr_data(
    tickers: Optional[list[str]] = None,
    start_date: Optional[str] = None,
    group_by: str = "ticker",
) -> pd.DataFrame:
    """
    Download historical stock data for Argentine ADRs.

    Args:
        tickers: List of ticker symbols. Defaults to AR_ADRS from config.
        start_date: Start date for data download. Defaults to START_DATE.
        group_by: How to group the data ('ticker' or 'column').

    Returns:
        DataFrame with stock data grouped by ticker.
    """
    if tickers is None:
        tickers = AR_ADRS

    if start_date is None:
        start_date = START_DATE

    logger.info("Downloading data for %d tickers from %s", len(tickers), start_date)
    data = yf.download(tickers, start=start_date, group_by=group_by)
    logger.info("Download complete. Shape: %s", data.shape)

    return data


def build_ticker_dimension(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a dimension table with metadata for each ticker.

    Args:
        df: DataFrame with MultiIndex columns (ticker, field).

    Returns:
        DataFrame with ticker metadata (has_data, first_date, last_date).
    """
    tickers = df.columns.get_level_values(0).unique()

    rows = []
    for ticker in tickers:
        sub = df[ticker]
        first_date = sub.dropna(how="all").index.min()
        last_date = sub.dropna(how="all").index.max()
        has_data = pd.notna(first_date)

        rows.append(
            {
                "ticker": ticker,
                "has_data": bool(has_data),
                "first_date": first_date,
                "last_date": last_date,
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["has_data", "ticker"], ascending=[False, True]
    )


def add_tickers(
    tickers: list[str],
    db_path: str = "data/processed/db.duckdb",
    db: Optional[DatabaseBackend] = None,
    metadata: Optional[dict[str, dict]] = None,
    start_date: Optional[str] = None,
) -> WarehouseUpdateResult:
    """
    Perform a full historical load for new ticker symbols and insert them into the
    warehouse.

    Tickers already tracked in the database are skipped. Subsequent calls to
    update_warehouse() will automatically include any tickers added here.

    Args:
        tickers: Ticker symbols to add.
        db_path: Path to the DuckDB database file.
        db: Optional database backend instance. If None, a DuckDB backend is created.
        metadata: Optional metadata dict keyed by ticker. Merged with TICKER_METADATA
            (caller wins); falls back to "Unknown" for missing fields.
        start_date: Start date for the historical load. Defaults to START_DATE.

    Returns:
        Dictionary with the number of rows added per table.
    """
    setup_logging()

    if db is None:
        db = create_database("duckdb", db_path=db_path)
    db.create_star_schema()

    zero_result = WarehouseUpdateResult(
        dim_date=0,
        dim_ticker=0,
        fact_stock_prices=0,
        violations={
            "null_required_fields": 0,
            "ohlc_violations": 0,
            "negative_prices": 0,
            "negative_volume": 0,
        },
    )

    try:
        existing_id_map = db.get_ticker_id_map()
        new_tickers = [t for t in tickers if t not in existing_id_map]

        for ticker in tickers:
            if ticker not in new_tickers:
                logger.warning("Ticker %s is already tracked — skipping", ticker)

        if not new_tickers:
            return zero_result

        raw = download_adr_data(
            tickers=new_tickers, start_date=start_date or START_DATE
        )

        if raw.empty:
            logger.warning(
                "No data returned from API for ticker(s): %s — "
                "they may be invalid or have no history since %s",
                ", ".join(new_tickers),
                start_date or START_DATE,
            )
            return zero_result

        merged_metadata = {**TICKER_METADATA, **(metadata or {})}

        dim_date = transform.build_date_dimension(raw)
        dim_ticker = transform.build_ticker_dimension(
            raw, metadata=merged_metadata, existing_id_map=existing_id_map
        )

        no_data = dim_ticker[dim_ticker["first_trade_date"].isna()][
            "ticker_symbol"
        ].tolist()
        if no_data:
            logger.warning(
                "No data returned for ticker(s): %s — skipping",
                ", ".join(no_data),
            )
            dim_ticker = dim_ticker[dim_ticker["first_trade_date"].notna()]

        fact = transform.build_fact_table(raw, dim_date, dim_ticker)

        db.begin()
        try:
            date_count = db.append_dimension(dim_date, "dim_date")
            ticker_count = db.append_dimension(dim_ticker, "dim_ticker")
            fact_count = db.append_fact(fact)
            db.update_ticker_dimension(dim_ticker)
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()

        violations = db.validate_fact_table()

        summary = WarehouseUpdateResult(
            dim_date=date_count,
            dim_ticker=ticker_count,
            fact_stock_prices=fact_count,
            violations=violations,
        )

        logger.info(
            "Rows added: dim_date=%d, dim_ticker=%d, fact_stock_prices=%d",
            date_count,
            ticker_count,
            fact_count,
        )

        return summary
    finally:
        db.close()


def update_warehouse(
    db_path: str = "data/processed/db.duckdb",
    db: Optional[DatabaseBackend] = None,
) -> WarehouseUpdateResult:
    """
    Incrementally update the ADR data warehouse.

    Fetches only new data since the last loaded date and appends it.
    Falls back to a full load if the database is empty.

    Args:
        db_path: Path to the DuckDB database file.
        db: Optional database backend instance. If None, a DuckDB backend is created.

    Returns:
        Dictionary with the number of rows added per table.
    """
    setup_logging()

    if db is None:
        db = create_database("duckdb", db_path=db_path)
    db.create_star_schema()

    try:
        last_date = db.get_last_loaded_date()

        if last_date is None:
            logger.info("No existing data found. Performing full load")
            start = START_DATE
        else:
            # Advance by one day so the last loaded date is not re-fetched.
            # yfinance skips non-trading days, so a plain calendar +1 is sufficient.
            start = str(last_date + timedelta(days=1))
            logger.info("Last loaded date: %s. Fetching from %s", last_date, start)

        existing_tickers = set(db.get_ticker_id_map().keys())
        all_tickers = sorted(set(AR_ADRS) | existing_tickers)
        raw = download_adr_data(tickers=all_tickers, start_date=start)

        if raw.empty:
            logger.info("No data returned from API. Skipping load.")
            return WarehouseUpdateResult(
                dim_date=0,
                dim_ticker=0,
                fact_stock_prices=0,
                violations={
                    "null_required_fields": 0,
                    "ohlc_violations": 0,
                    "negative_prices": 0,
                    "negative_volume": 0,
                },
            )

        dim_date = transform.build_date_dimension(raw)
        existing_id_map = db.get_ticker_id_map()
        dim_ticker = transform.build_ticker_dimension(
            raw, existing_id_map=existing_id_map
        )
        fact = transform.build_fact_table(raw, dim_date, dim_ticker)

        db.begin()
        try:
            date_count = db.append_dimension(dim_date, "dim_date")
            ticker_count = db.append_dimension(dim_ticker, "dim_ticker")
            fact_count = db.append_fact(fact)
            db.update_ticker_dimension(dim_ticker)
        except Exception:
            db.rollback()
            raise
        else:
            db.commit()

        violations = db.validate_fact_table()

        summary = WarehouseUpdateResult(
            dim_date=date_count,
            dim_ticker=ticker_count,
            fact_stock_prices=fact_count,
            violations=violations,
        )

        logger.info(
            "Rows added: dim_date=%d, dim_ticker=%d, fact_stock_prices=%d",
            date_count,
            ticker_count,
            fact_count,
        )

        return summary
    finally:
        db.close()
