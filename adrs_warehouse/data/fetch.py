import pandas as pd
import yfinance as yf
from pathlib import Path
from typing import Dict, List, Optional

from ..config import AR_ADRS, START_DATE
from ..database.operations import ADRDatabase
from . import transform


def download_adr_data(
    tickers: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    group_by: str = "ticker"
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
    
    print(f"Downloading data for {len(tickers)} tickers from {start_date}...")
    data = yf.download(tickers, start=start_date, group_by=group_by)
    print(f"Download complete. Shape: {data.shape}")
    
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
        
        rows.append({
            "ticker": ticker,
            "has_data": bool(has_data),
            "first_date": first_date,
            "last_date": last_date,
        })
    
    return pd.DataFrame(rows).sort_values(
        ["has_data", "ticker"],
        ascending=[False, True]
    )


def update_warehouse(db_path: str = "data/processed/db.duckdb") -> Dict[str, int]:
    """
    Incrementally update the ADR data warehouse.

    Fetches only new data since the last loaded date and appends it.
    Falls back to a full load if the database is empty.

    Args:
        db_path: Path to the DuckDB database file.

    Returns:
        Dictionary with the number of rows added per table.
    """
    db = ADRDatabase(db_path)
    db.create_star_schema()

    last_date = db.get_last_loaded_date()

    if last_date is None:
        print("No existing data found. Performing full load...")
        start = START_DATE
    else:
        start = str(last_date)
        print(f"Last loaded date: {last_date}. Fetching from {start}...")

    raw = download_adr_data(start_date=start)

    dim_date = transform.build_date_dimension(raw)
    dim_ticker = transform.build_ticker_dimension(raw)
    fact = transform.build_fact_table(raw, dim_date, dim_ticker)

    date_count = db.append_dimension(dim_date, "dim_date")
    ticker_count = db.append_dimension(dim_ticker, "dim_ticker")
    fact_count = db.append_fact(fact)
    db.update_ticker_dimension(dim_ticker)

    summary = {
        "dim_date": date_count,
        "dim_ticker": ticker_count,
        "fact_stock_prices": fact_count,
    }

    print(
        f"Rows added: dim_date={date_count}, "
        f"dim_ticker={ticker_count}, "
        f"fact_stock_prices={fact_count}"
    )

    db.close()
    return summary