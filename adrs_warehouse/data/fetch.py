import pandas as pd
import yfinance as yf
from typing import List, Optional
from ..config import AR_ADRS, START_DATE


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