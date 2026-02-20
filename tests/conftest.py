import numpy as np
import pandas as pd
import pytest

from adrs_warehouse.data.transform import normalize_prices_long
from adrs_warehouse.database.base import DatabaseBackend
from adrs_warehouse.database.operations import DuckDBDatabase


def _make_multiindex_df(dates, tickers, data):
    """Helper to build a yfinance-like MultiIndex DataFrame."""
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    columns = pd.MultiIndex.from_product([tickers, fields], names=["Ticker", "Price"])
    df = pd.DataFrame(data, index=pd.to_datetime(dates), columns=columns)
    df.index.name = "Date"
    return df


@pytest.fixture
def sample_multiindex_df():
    """A small 3-date x 2-ticker MultiIndex DataFrame mimicking yfinance output."""
    return _make_multiindex_df(
        dates=["2024-01-02", "2024-01-03", "2024-01-04"],
        tickers=["GGAL", "YPF"],
        data=np.array(
            [
                [10.0, 11.0, 9.5, 10.5, 10.4, 1000, 20.0, 21.0, 19.0, 20.5, 20.3, 2000],
                [
                    10.5,
                    12.0,
                    10.0,
                    11.0,
                    10.9,
                    1500,
                    20.5,
                    22.0,
                    20.0,
                    21.0,
                    20.8,
                    2500,
                ],
                [
                    11.0,
                    11.5,
                    10.5,
                    11.2,
                    11.1,
                    1200,
                    21.0,
                    21.5,
                    20.5,
                    21.2,
                    21.0,
                    2200,
                ],
            ]
        ),
    )


@pytest.fixture
def extended_multiindex_df():
    """Jan 4-5 data (overlaps one date with sample_multiindex_df)."""
    return _make_multiindex_df(
        dates=["2024-01-04", "2024-01-05"],
        tickers=["GGAL", "YPF"],
        data=np.array(
            [
                [
                    11.0,
                    11.5,
                    10.5,
                    11.2,
                    11.1,
                    1200,
                    21.0,
                    21.5,
                    20.5,
                    21.2,
                    21.0,
                    2200,
                ],
                [
                    11.5,
                    12.0,
                    11.0,
                    11.8,
                    11.7,
                    1300,
                    21.5,
                    22.5,
                    21.0,
                    22.0,
                    21.8,
                    2400,
                ],
            ]
        ),
    )


@pytest.fixture
def sample_long_df(sample_multiindex_df):
    """The long-format result of normalize_prices_long(sample_multiindex_df)."""
    return normalize_prices_long(sample_multiindex_df)


@pytest.fixture
def db() -> DatabaseBackend:
    """An in-memory DuckDBDatabase with star schema created."""
    database = DuckDBDatabase(":memory:")
    database.create_star_schema()
    yield database
    database.close()
