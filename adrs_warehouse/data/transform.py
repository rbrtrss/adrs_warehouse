import pandas as pd


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove columns with all null values.
    
    Args:
        df: DataFrame with MultiIndex columns.
    
    Returns:
        Cleaned DataFrame.
    """
    return df.T.dropna(how='all').T


def normalize_prices_long(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert MultiIndex columns (ticker, field) to long tidy format.
    
    Args:
        df: DataFrame with MultiIndex columns (ticker, field).
    
    Returns:
        Long-format DataFrame with columns:
        date, ticker, open, high, low, close, volume
    """
    out = (
        df.copy()
        .rename(columns={"Adj Close": "Adj_Close"}, level=1)
        .stack(level=0, future_stack=True)
        .reset_index()
        .rename(columns={"level_0": "date", "level_1": "ticker"})
    )
    
    # Standardize column names
    out.columns = [c.lower().replace(" ", "_") for c in out.columns]
    
    return out