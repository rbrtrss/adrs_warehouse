import logging

import pandas as pd

from ..config import TICKER_METADATA

logger = logging.getLogger(__name__)


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove columns with all null values.

    Args:
        df: DataFrame with MultiIndex columns.

    Returns:
        Cleaned DataFrame.
    """
    before = len(df.columns)
    result = df.T.dropna(how="all").T
    after = len(result.columns)
    logger.info("Cleaned columns: %d → %d (removed %d)", before, after, before - after)
    return result


def normalize_prices_long(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert MultiIndex columns (ticker, field) to long tidy format.

    Args:
        df: DataFrame with MultiIndex columns (ticker, field).

    Returns:
        Long-format DataFrame with columns:
        date, ticker, open, high, low, close, volume
    """
    if df.empty:
        return df

    out = (
        df.copy()
        .rename(columns={"Adj Close": "Adj_Close"}, level=1)
        .stack(level=0, future_stack=True)
        .reset_index()
        .rename(columns={"level_0": "date", "level_1": "ticker"})
    )

    # Standardize column names
    out.columns = [c.lower().replace(" ", "_") for c in out.columns]

    logger.debug("Normalized to long format: %d rows", len(out))
    return out


def build_date_dimension(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a date dimension table from the DataFrame index.

    Args:
        df: DataFrame with DatetimeIndex.

    Returns:
        DataFrame with date dimension attributes.
    """
    dates = pd.DataFrame({"date": df.index.unique()})
    dates["date"] = pd.to_datetime(dates["date"])

    dates["date_id"] = dates["date"].dt.strftime("%Y%m%d").astype(int)
    dates["year"] = dates["date"].dt.year
    dates["quarter"] = dates["date"].dt.quarter
    dates["month"] = dates["date"].dt.month
    dates["month_name"] = dates["date"].dt.month_name()
    dates["day"] = dates["date"].dt.day
    dates["day_of_week"] = dates["date"].dt.dayofweek
    dates["day_name"] = dates["date"].dt.day_name()
    dates["week_of_year"] = dates["date"].dt.isocalendar().week.astype(int)
    dates["is_weekend"] = dates["day_of_week"].isin([5, 6])
    dates["is_month_start"] = dates["date"].dt.is_month_start
    dates["is_month_end"] = dates["date"].dt.is_month_end

    result = dates.sort_values("date_id").reset_index(drop=True)
    logger.info(
        "Date dimension: %d dates from %s to %s",
        len(result),
        result["date"].min().date(),
        result["date"].max().date(),
    )
    return result


def build_ticker_dimension(
    df: pd.DataFrame,
    metadata: dict[str, dict] = None,
    existing_id_map: dict[str, int] = None,
) -> pd.DataFrame:
    """
    Build a ticker dimension table with metadata.

    Args:
        df: DataFrame with MultiIndex columns (ticker, field).
        metadata: Dictionary with ticker metadata. Defaults to TICKER_METADATA.
        existing_id_map: {ticker_symbol: ticker_id} from DB; pins known symbols
            to their stored IDs and assigns fresh IDs above the current max for
            new symbols. Pass {} or omit on first run.

    Returns:
        DataFrame with ticker dimension attributes.
    """
    if metadata is None:
        metadata = TICKER_METADATA

    if existing_id_map is None:
        existing_id_map = {}

    tickers = df.columns.get_level_values(0).unique()

    next_id = max(existing_id_map.values(), default=0) + 1

    rows = []
    for ticker in sorted(tickers):
        ticker_id = existing_id_map.get(ticker)
        if ticker_id is None:
            ticker_id = next_id
            next_id += 1
        sub = df[ticker]
        valid_dates = sub.dropna(how="all").index
        first_date = valid_dates.min() if len(valid_dates) > 0 else None
        last_date = valid_dates.max() if len(valid_dates) > 0 else None

        meta = metadata.get(ticker, {})
        rows.append(
            {
                "ticker_id": ticker_id,
                "ticker_symbol": ticker,
                "company_name": meta.get("company_name", ticker),
                "exchange": meta.get("exchange", "Unknown"),
                "sector": meta.get("sector", "Unknown"),
                "country": meta.get("country", "Unknown"),
                "first_trade_date": first_date,
                "last_trade_date": last_date,
            }
        )

    result = pd.DataFrame(rows)
    with_data = result[result["first_trade_date"].notna()]
    logger.info(
        "Ticker dimension: %d tickers (%d with data, %d without)",
        len(result),
        len(with_data),
        len(result) - len(with_data),
    )
    return result


def clean_fact_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply row-level data quality checks and drop invalid rows.

    Checks (in order):
    1. Null required OHLC fields
    2. OHLC logical consistency
    3. Negative / zero prices; negative volume
    4. Duplicate (date_id, ticker_id) pairs

    Args:
        df: Fact DataFrame with renamed price columns.

    Returns:
        Cleaned DataFrame.
    """
    # 1. Null required fields
    price_cols = ["open_price", "high_price", "low_price", "close_price"]
    null_mask = df[price_cols].isnull().any(axis=1)
    if null_mask.sum():
        logger.warning(
            "Dropping %d rows with null required OHLC fields", null_mask.sum()
        )
    df = df[~null_mask]

    # 2. OHLC logical consistency
    ohlc_mask = (
        (df["high_price"] < df["low_price"])
        | (df["high_price"] < df["open_price"])
        | (df["high_price"] < df["close_price"])
        | (df["low_price"] > df["open_price"])
        | (df["low_price"] > df["close_price"])
    )
    if ohlc_mask.sum():
        logger.warning("Dropping %d rows with OHLC logical violations", ohlc_mask.sum())
    df = df[~ohlc_mask]

    # 3. Negative / zero prices and negative volume
    all_price_cols = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "adj_close_price",
    ]
    existing_price_cols = [c for c in all_price_cols if c in df.columns]
    neg_price_mask = (df[existing_price_cols] <= 0).any(axis=1)
    if "volume" in df.columns:
        neg_vol_mask = df["volume"] < 0
    else:
        neg_vol_mask = pd.Series(False, index=df.index)
    invalid_mask = neg_price_mask | neg_vol_mask
    if invalid_mask.sum():
        logger.warning(
            "Dropping %d rows with negative/zero prices or negative volume",
            invalid_mask.sum(),
        )
    df = df[~invalid_mask]

    # 4. Duplicates
    dup_mask = df.duplicated(subset=["date_id", "ticker_id"], keep="first")
    if dup_mask.sum():
        logger.warning(
            "Dropping %d duplicate (date_id, ticker_id) rows", dup_mask.sum()
        )
    df = df[~dup_mask]

    return df


def build_fact_table(
    df: pd.DataFrame, dim_date: pd.DataFrame, dim_ticker: pd.DataFrame
) -> pd.DataFrame:
    """
    Build the fact table with foreign keys to dimensions.

    Args:
        df: DataFrame with MultiIndex columns (ticker, field).
        dim_date: Date dimension DataFrame.
        dim_ticker: Ticker dimension DataFrame.

    Returns:
        Fact table DataFrame with foreign keys and measures.
    """
    # Create date_id lookup
    date_lookup = dim_date.set_index("date")["date_id"]

    # Create ticker_id lookup
    ticker_lookup = dim_ticker.set_index("ticker_symbol")["ticker_id"]

    # Normalize to long format first
    long_df = normalize_prices_long(df)

    # Add foreign keys
    long_df["date_id"] = pd.to_datetime(long_df["date"]).map(date_lookup)
    long_df["ticker_id"] = long_df["ticker"].map(ticker_lookup)

    # Rename columns to match fact table schema
    fact_df = long_df.rename(
        columns={
            "open": "open_price",
            "high": "high_price",
            "low": "low_price",
            "close": "close_price",
            "adj_close": "adj_close_price",
        }
    )

    # Add adj_close_price column if not present (use close_price as fallback)
    if "adj_close_price" not in fact_df.columns:
        fact_df["adj_close_price"] = fact_df["close_price"]

    # Clean row-level data quality issues
    fact_df = clean_fact_rows(fact_df)

    # Select and order columns for fact table
    fact_columns = [
        "date_id",
        "ticker_id",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "adj_close_price",
        "volume",
    ]

    result = fact_df[fact_columns].dropna(subset=["date_id", "ticker_id"])
    result["volume"] = result["volume"].astype("Int64")
    logger.info("Fact table: %d rows", len(result))
    return result
