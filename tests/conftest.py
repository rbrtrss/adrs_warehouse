import numpy as np
import pandas as pd
import pytest

from adrs_warehouse.data.transform import normalize_prices_long
from adrs_warehouse.database.operations import ADRDatabase


@pytest.fixture
def sample_multiindex_df():
    """A small 3-date x 2-ticker MultiIndex DataFrame mimicking yfinance output."""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    tickers = ["GGAL", "YPF"]
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]

    columns = pd.MultiIndex.from_product([tickers, fields], names=["Ticker", "Price"])
    data = np.array(
        [
            # date 1: GGAL(O,H,L,C,AC,V), YPF(O,H,L,C,AC,V)
            [10.0, 11.0, 9.5, 10.5, 10.4, 1000, 20.0, 21.0, 19.0, 20.5, 20.3, 2000],
            [10.5, 12.0, 10.0, 11.0, 10.9, 1500, 20.5, 22.0, 20.0, 21.0, 20.8, 2500],
            [11.0, 11.5, 10.5, 11.2, 11.1, 1200, 21.0, 21.5, 20.5, 21.2, 21.0, 2200],
        ]
    )

    df = pd.DataFrame(data, index=dates, columns=columns)
    df.index.name = "Date"
    return df


@pytest.fixture
def sample_long_df(sample_multiindex_df):
    """The long-format result of normalize_prices_long(sample_multiindex_df)."""
    return normalize_prices_long(sample_multiindex_df)


@pytest.fixture
def db():
    """An in-memory ADRDatabase with star schema created."""
    database = ADRDatabase(":memory:")
    database.create_star_schema()
    yield database
    database.close()
