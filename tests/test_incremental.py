from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from adrs_warehouse.data.fetch import update_warehouse
from adrs_warehouse.database.operations import create_database


def _make_multiindex_df(dates, tickers, data):
    """Build a yfinance-like MultiIndex DataFrame for use in incremental tests."""
    fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    columns = pd.MultiIndex.from_product([tickers, fields], names=["Ticker", "Price"])
    df = pd.DataFrame(data, index=pd.to_datetime(dates), columns=columns)
    df.index.name = "Date"
    return df


class TestIncrementalRuns:
    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_incremental_run_appends_new_rows(
        self, mock_download, sample_multiindex_df, extended_multiindex_df, tmp_path
    ):
        """Full load then incremental: new rows appended, duplicates skipped."""
        db_path = str(tmp_path / "test.duckdb")
        mock_download.side_effect = [sample_multiindex_df, extended_multiindex_df]

        # Full load: Jan 2-4, 2 tickers → 3 dates, 2 tickers, 6 facts
        result1 = update_warehouse(db_path=db_path)
        assert result1["dim_date"] == 3
        assert result1["dim_ticker"] == 2
        assert result1["fact_stock_prices"] == 6

        # Incremental: Jan 4-5; Jan 4 already loaded, Jan 5 is new
        result2 = update_warehouse(db_path=db_path)
        assert result2["dim_date"] == 1
        assert result2["dim_ticker"] == 0
        assert result2["fact_stock_prices"] == 2

        # Verify cumulative totals
        db = create_database("duckdb", db_path=db_path)
        total_facts = db.query("SELECT COUNT(*) AS n FROM fact_stock_prices").iloc[0][
            "n"
        ]
        db.close()
        assert total_facts == 8

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_new_ticker_gets_non_colliding_id(
        self, mock_download, sample_multiindex_df, tmp_path
    ):
        """Ticker added in incremental run receives an ID above the current max."""
        db_path = str(tmp_path / "test.duckdb")

        # Jan 5 data for three tickers (GGAL and YPF already exist, BMA is new)
        new_ticker_df = _make_multiindex_df(
            dates=["2024-01-05"],
            tickers=["GGAL", "YPF", "BMA"],
            data=np.array(
                [
                    [
                        11.5,
                        12.0,
                        11.0,
                        11.8,
                        11.7,
                        1300,  # GGAL
                        21.5,
                        22.5,
                        21.0,
                        22.0,
                        21.8,
                        2400,  # YPF
                        5.0,
                        5.5,
                        4.8,
                        5.2,
                        5.1,
                        800,  # BMA
                    ]
                ]
            ),
        )
        mock_download.side_effect = [sample_multiindex_df, new_ticker_df]

        # First load: GGAL → id 1, YPF → id 2
        update_warehouse(db_path=db_path)

        # Incremental: BMA must receive id 3, not collide with existing ids
        update_warehouse(db_path=db_path)

        db = create_database("duckdb", db_path=db_path)
        id_map = db.get_ticker_id_map()
        db.close()

        assert id_map["GGAL"] == 1
        assert id_map["YPF"] == 2
        assert id_map["BMA"] == 3
        assert len(id_map) == 3

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_same_date_range_is_idempotent(
        self, mock_download, sample_multiindex_df, tmp_path
    ):
        """Re-running with identical data adds zero rows to every table."""
        db_path = str(tmp_path / "test.duckdb")
        mock_download.return_value = sample_multiindex_df

        update_warehouse(db_path=db_path)

        result2 = update_warehouse(db_path=db_path)
        assert result2["dim_date"] == 0
        assert result2["dim_ticker"] == 0
        assert result2["fact_stock_prices"] == 0

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_incremental_failure_triggers_rollback(
        self, mock_download, sample_multiindex_df, extended_multiindex_df, tmp_path
    ):
        """A mid-ETL failure rolls back all writes in that transaction run."""
        db_path = str(tmp_path / "test.duckdb")

        # First call: full load commits successfully (Jan 2-4, 6 facts)
        mock_download.return_value = sample_multiindex_df
        update_warehouse(db_path=db_path)

        # Second call: fails at append_fact — dim_date write for Jan 5 must be reverted
        mock_download.return_value = extended_multiindex_df
        db2 = create_database("duckdb", db_path=db_path)
        with (
            patch.object(
                db2, "append_fact", side_effect=RuntimeError("simulated failure")
            ),
            pytest.raises(RuntimeError, match="simulated failure"),
        ):
            update_warehouse(db=db2)

        # Reconnect and verify the failed run left no trace
        db3 = create_database("duckdb", db_path=db_path)
        fact_count = db3.query("SELECT COUNT(*) AS n FROM fact_stock_prices").iloc[0][
            "n"
        ]
        date_count = db3.query("SELECT COUNT(*) AS n FROM dim_date").iloc[0]["n"]
        db3.close()

        assert fact_count == 6  # unchanged from first run
        assert date_count == 3  # Jan 5 write was rolled back
