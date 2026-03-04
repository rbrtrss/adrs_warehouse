import datetime
import logging
from unittest.mock import patch

import pandas as pd
import pytest

from adrs_warehouse.data.fetch import add_tickers, update_warehouse
from adrs_warehouse.data.transform import (
    build_date_dimension,
    build_fact_table,
    build_ticker_dimension,
)
from adrs_warehouse.database.operations import ADRDatabase, create_database


class TestCreateStarSchema:
    def test_all_tables_exist(self, db):
        tables = db.query("SHOW TABLES")
        table_names = set(tables["name"])
        assert {"dim_date", "dim_ticker", "fact_stock_prices"}.issubset(table_names)


class TestQuery:
    def test_returns_expected_dataframe(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        db.append_dimension(dim_date, "dim_date")

        result = db.query("SELECT date_id, year FROM dim_date ORDER BY date_id LIMIT 1")
        assert result.iloc[0]["date_id"] == 20240102
        assert result.iloc[0]["year"] == 2024


class TestGetSchemaInfo:
    def test_returns_correct_structure(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        db.append_dimension(dim_date, "dim_date")

        info = db.get_schema_info()
        assert "dim_date" in info
        assert "columns" in info["dim_date"]
        assert "row_count" in info["dim_date"]
        assert info["dim_date"]["row_count"] == 3

    def test_returns_none_for_missing_tables(self):
        # Fresh database without star schema
        fresh_db = ADRDatabase(":memory:")
        info = fresh_db.get_schema_info()
        for table_info in info.values():
            assert table_info is None
        fresh_db.close()


class TestCreateTableFromDataframe:
    def test_table_exists_and_contains_correct_data(self, db):
        df = pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]})
        db.create_table_from_dataframe(df, "test_table")

        result = db.query("SELECT * FROM test_table ORDER BY x")
        assert len(result) == 3
        assert list(result["x"]) == [1, 2, 3]
        assert list(result["y"]) == ["a", "b", "c"]


class TestGetLastLoadedDate:
    def test_returns_none_when_empty(self, db):
        assert db.get_last_loaded_date() is None

    def test_returns_max_date(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        db.append_dimension(dim_date, "dim_date")

        result = db.get_last_loaded_date()
        assert result == datetime.date(2024, 1, 4)


class TestAppendDimension:
    def test_inserts_new_rows(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        count = db.append_dimension(dim_date, "dim_date")
        assert count == 3

    def test_skips_existing_rows(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        db.append_dimension(dim_date, "dim_date")

        count = db.append_dimension(dim_date, "dim_date")
        assert count == 0

    def test_appends_only_new_rows(
        self, db, sample_multiindex_df, extended_multiindex_df
    ):
        initial = build_date_dimension(sample_multiindex_df)
        db.append_dimension(initial, "dim_date")

        incremental = build_date_dimension(extended_multiindex_df)
        count = db.append_dimension(incremental, "dim_date")
        assert count == 1  # only Jan 5 is new

        total = db.query("SELECT COUNT(*) AS n FROM dim_date").iloc[0]["n"]
        assert total == 4


class TestAppendFact:
    def test_inserts_new_rows(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        fact = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)

        db.append_dimension(dim_date, "dim_date")
        db.append_dimension(dim_ticker, "dim_ticker")
        count = db.append_fact(fact)
        assert count == 6

    def test_skips_existing_rows(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        fact = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)

        db.append_dimension(dim_date, "dim_date")
        db.append_dimension(dim_ticker, "dim_ticker")
        db.append_fact(fact)

        count = db.append_fact(fact)
        assert count == 0

    def test_appends_only_new_rows(
        self, db, sample_multiindex_df, extended_multiindex_df
    ):
        # Initial load (Jan 2-4, 2 tickers = 6 rows)
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        fact = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)
        db.append_dimension(dim_date, "dim_date")
        db.append_dimension(dim_ticker, "dim_ticker")
        db.append_fact(fact)

        # Incremental (Jan 4-5): append new date dim first, then facts
        inc_date = build_date_dimension(extended_multiindex_df)
        inc_ticker = build_ticker_dimension(extended_multiindex_df)
        inc_fact = build_fact_table(extended_multiindex_df, inc_date, inc_ticker)
        db.append_dimension(inc_date, "dim_date")

        count = db.append_fact(inc_fact)
        assert count == 2  # only Jan 5 x 2 tickers

        total = db.query("SELECT COUNT(*) AS n FROM fact_stock_prices").iloc[0]["n"]
        assert total == 8


class TestUpdateTickerDimension:
    def test_updates_last_trade_date(self, db, sample_multiindex_df):
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        db.append_dimension(dim_ticker, "dim_ticker")

        # Build a fresh dim with a later last_trade_date
        updated = dim_ticker.copy()
        updated["last_trade_date"] = datetime.date(2099, 12, 31)
        db.update_ticker_dimension(updated)

        result = db.query("SELECT last_trade_date FROM dim_ticker LIMIT 1")
        assert result.iloc[0]["last_trade_date"] == pd.Timestamp("2099-12-31")

    def test_does_not_downgrade_date(self, db, sample_multiindex_df):
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        db.append_dimension(dim_ticker, "dim_ticker")

        # Try to set an older date — should not overwrite
        original_date = db.query("SELECT last_trade_date FROM dim_ticker LIMIT 1").iloc[
            0
        ]["last_trade_date"]

        older = dim_ticker.copy()
        older["last_trade_date"] = datetime.date(2000, 1, 1)
        db.update_ticker_dimension(older)

        result = db.query("SELECT last_trade_date FROM dim_ticker LIMIT 1")
        assert result.iloc[0]["last_trade_date"] == original_date


class TestValidateFactTable:
    def _seed_dimensions(self, db):
        """Insert one dim_date and one dim_ticker row for FK references."""
        db.conn.execute("""
            INSERT INTO dim_date VALUES
            (20240102, '2024-01-02', 2024, 1, 1, 'January',
             2, 1, 'Tuesday', 1, false, true, false)
        """)
        db.conn.execute("""
            INSERT INTO dim_ticker VALUES
            (1, 'TEST', 'Test Co', 'NASDAQ', 'Tech', 'USA', NULL, NULL)
        """)

    def test_returns_zero_violations_for_clean_data(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        fact = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)
        db.append_dimension(dim_date, "dim_date")
        db.append_dimension(dim_ticker, "dim_ticker")
        db.append_fact(fact)

        violations = db.validate_fact_table()
        assert violations["null_required_fields"] == 0
        assert violations["ohlc_violations"] == 0
        assert violations["negative_prices"] == 0
        assert violations["negative_volume"] == 0

    def test_detects_null_required_fields(self, db):
        self._seed_dimensions(db)
        db.conn.execute("""
            INSERT INTO fact_stock_prices
            VALUES (20240102, 1, NULL, 11.0, 9.5, 10.5, 10.4, 1000)
        """)
        violations = db.validate_fact_table()
        assert violations["null_required_fields"] == 1

    def test_detects_ohlc_violation(self, db):
        self._seed_dimensions(db)
        db.conn.execute("""
            INSERT INTO fact_stock_prices
            VALUES (20240102, 1, 10.0, 8.0, 9.5, 10.5, 10.4, 1000)
        """)
        violations = db.validate_fact_table()
        assert violations["ohlc_violations"] == 1

    def test_detects_negative_price(self, db):
        self._seed_dimensions(db)
        db.conn.execute("""
            INSERT INTO fact_stock_prices
            VALUES (20240102, 1, -1.0, 11.0, 9.5, 10.5, 10.4, 1000)
        """)
        violations = db.validate_fact_table()
        assert violations["negative_prices"] == 1

    def test_detects_negative_volume(self, db):
        self._seed_dimensions(db)
        db.conn.execute("""
            INSERT INTO fact_stock_prices
            VALUES (20240102, 1, 10.0, 11.0, 9.5, 10.5, 10.4, -5)
        """)
        violations = db.validate_fact_table()
        assert violations["negative_volume"] == 1


class TestGetTickerIdMap:
    def test_returns_empty_dict_when_dim_ticker_is_empty(self, db):
        result = db.get_ticker_id_map()
        assert result == {}

    def test_returns_correct_mapping_after_insert(self, db, sample_multiindex_df):
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        db.append_dimension(dim_ticker, "dim_ticker")

        result = db.get_ticker_id_map()
        assert result == {"GGAL": 1, "YPF": 2}

    def test_returns_empty_dict_before_schema_creation(self):
        bare_db = ADRDatabase(":memory:")
        result = bare_db.get_ticker_id_map()
        assert result == {}
        bare_db.close()


class TestDuckDBTransaction:
    def test_commit_persists_data(self, db):
        db.begin()
        db.conn.execute(
            "INSERT INTO dim_date VALUES "
            "(20240102,'2024-01-02',2024,1,1,'January',2,1,'Tuesday',1,false,true,false)"
        )
        db.commit()
        assert db.query("SELECT COUNT(*) AS n FROM dim_date").iloc[0]["n"] == 1

    def test_rollback_reverts_data(self, db):
        db.begin()
        db.conn.execute(
            "INSERT INTO dim_date VALUES "
            "(20240102,'2024-01-02',2024,1,1,'January',2,1,'Tuesday',1,false,true,false)"
        )
        db.rollback()
        assert db.query("SELECT COUNT(*) AS n FROM dim_date").iloc[0]["n"] == 0


class TestCreateDatabase:
    def test_returns_duckdb_instance(self):
        db = create_database("duckdb", db_path=":memory:")
        assert isinstance(db, ADRDatabase)
        db.close()

    def test_raises_for_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown database provider"):
            create_database("sqlite")


class TestUpdateWarehouse:
    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_full_then_incremental(self, mock_download, sample_multiindex_df, tmp_path):
        mock_download.return_value = sample_multiindex_df
        db_path = str(tmp_path / "test.duckdb")

        # First call — full load
        result1 = update_warehouse(db_path=db_path)
        assert result1["dim_date"] == 3
        assert result1["dim_ticker"] == 2
        assert result1["fact_stock_prices"] == 6
        assert isinstance(result1["violations"], dict)

        # Second call — same data, should add 0
        result2 = update_warehouse(db_path=db_path)
        assert result2["dim_date"] == 0
        assert result2["dim_ticker"] == 0
        assert result2["fact_stock_prices"] == 0
        assert isinstance(result2["violations"], dict)

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_empty_api_response(self, mock_download, tmp_path):
        mock_download.return_value = pd.DataFrame()
        db_path = str(tmp_path / "test.duckdb")

        result = update_warehouse(db_path=db_path)

        assert result["dim_date"] == 0
        assert result["dim_ticker"] == 0
        assert result["fact_stock_prices"] == 0
        assert result["violations"] == {
            "null_required_fields": 0,
            "ohlc_violations": 0,
            "negative_prices": 0,
            "negative_volume": 0,
        }

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_incremental_start_date_advances_by_one_day(
        self, mock_download, sample_multiindex_df, tmp_path
    ):
        mock_download.return_value = sample_multiindex_df
        db_path = str(tmp_path / "test.duckdb")

        # Full load — last date in sample is 2024-01-04
        update_warehouse(db_path=db_path)

        # Incremental call should request data starting from 2024-01-05
        update_warehouse(db_path=db_path)
        _, kwargs = mock_download.call_args
        assert kwargs["start_date"] == "2024-01-05"

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_rollback_on_partial_failure(
        self, mock_download, sample_multiindex_df, tmp_path
    ):
        mock_download.return_value = sample_multiindex_df
        db_path = str(tmp_path / "test.duckdb")

        db = create_database("duckdb", db_path=db_path)
        with (
            patch.object(
                db, "append_fact", side_effect=RuntimeError("simulated failure")
            ),
            pytest.raises(RuntimeError, match="simulated failure"),
        ):
            update_warehouse(db=db)

        # Reconnect and verify dim writes were rolled back
        db2 = create_database("duckdb", db_path=db_path)
        db2.create_star_schema()
        assert db2.query("SELECT COUNT(*) AS n FROM dim_date").iloc[0]["n"] == 0
        assert db2.query("SELECT COUNT(*) AS n FROM dim_ticker").iloc[0]["n"] == 0
        db2.close()


class TestAddTickers:
    """Tests for add_tickers() — full historical load for new symbols."""

    def _new_ticker_df(self, dates, ticker="NEW"):
        """Build a single-ticker yfinance-like MultiIndex DataFrame."""
        import numpy as np

        fields = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
        columns = pd.MultiIndex.from_product(
            [[ticker], fields], names=["Ticker", "Price"]
        )
        n = len(dates)
        data = np.tile([10.0, 11.0, 9.5, 10.5, 10.4, 1000], (n, 1))
        df = pd.DataFrame(data, index=pd.to_datetime(dates), columns=columns)
        df.index.name = "Date"
        return df

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_new_tickers_perform_full_load(self, mock_download, tmp_path):
        new_df = self._new_ticker_df(["2024-01-02", "2024-01-03", "2024-01-04"])
        mock_download.return_value = new_df
        db_path = str(tmp_path / "test.duckdb")

        result = add_tickers(["NEW"], db_path=db_path)

        assert result["dim_date"] == 3
        assert result["dim_ticker"] == 1
        assert result["fact_stock_prices"] == 3
        assert isinstance(result["violations"], dict)

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_already_tracked_ticker_skips(
        self, mock_download, sample_multiindex_df, tmp_path
    ):
        mock_download.return_value = sample_multiindex_df
        db_path = str(tmp_path / "test.duckdb")

        # Seed the DB with GGAL and YPF
        update_warehouse(db_path=db_path)

        # Reset mock so we can detect if it's called again
        mock_download.reset_mock()
        mock_download.return_value = sample_multiindex_df

        result = add_tickers(["GGAL"], db_path=db_path)

        assert result["dim_date"] == 0
        assert result["dim_ticker"] == 0
        assert result["fact_stock_prices"] == 0
        # download should not have been called for an already-tracked ticker
        mock_download.assert_not_called()

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_new_ticker_id_assigned_above_max(
        self, mock_download, sample_multiindex_df, tmp_path
    ):
        mock_download.return_value = sample_multiindex_df
        db_path = str(tmp_path / "test.duckdb")

        # Seed GGAL (id=1) and YPF (id=2)
        update_warehouse(db_path=db_path)

        new_df = self._new_ticker_df(["2024-01-02", "2024-01-03"])
        mock_download.return_value = new_df

        add_tickers(["NEW"], db_path=db_path)

        db = create_database("duckdb", db_path=db_path)
        db.create_star_schema()
        row = db.query("SELECT ticker_id FROM dim_ticker WHERE ticker_symbol = 'NEW'")
        db.close()
        assert row.iloc[0]["ticker_id"] == 3  # max(1,2) + 1

    @patch("adrs_warehouse.data.fetch.yf")
    def test_invalid_ticker_returns_zero_and_warns(self, mock_yf, tmp_path, caplog):
        mock_yf.download.return_value = pd.DataFrame()
        db_path = str(tmp_path / "test.duckdb")

        with caplog.at_level(logging.WARNING, logger="adrs_warehouse.data.fetch"):
            result = add_tickers(["BADTICKER"], db_path=db_path)

        assert result == {
            "dim_date": 0,
            "dim_ticker": 0,
            "fact_stock_prices": 0,
            "violations": {
                "null_required_fields": 0,
                "ohlc_violations": 0,
                "negative_prices": 0,
                "negative_volume": 0,
            },
        }
        assert "BADTICKER" in caplog.text

    @patch("adrs_warehouse.data.fetch.yf")
    def test_mixed_valid_invalid_tickers(
        self, mock_yf, tmp_path, caplog, sample_multiindex_df
    ):
        # sample_multiindex_df has GGAL and YPF; NaN-out YPF to simulate invalid
        df = sample_multiindex_df.copy()
        for field in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
            df[("YPF", field)] = float("nan")
        mock_yf.download.return_value = df
        db_path = str(tmp_path / "test.duckdb")

        with caplog.at_level(logging.WARNING, logger="adrs_warehouse.data.fetch"):
            result = add_tickers(["GGAL", "YPF"], db_path=db_path)

        # Valid ticker was loaded
        assert result["dim_ticker"] == 1
        assert result["fact_stock_prices"] > 0
        # Invalid ticker warned about
        assert "YPF" in caplog.text
        # Invalid ticker NOT inserted into dim_ticker
        db = create_database("duckdb", db_path=db_path)
        db.create_star_schema()
        id_map = db.get_ticker_id_map()
        db.close()
        assert "YPF" not in id_map
        assert "GGAL" in id_map

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_update_warehouse_includes_added_ticker(
        self, mock_download, sample_multiindex_df, tmp_path
    ):
        from adrs_warehouse.config import AR_ADRS

        mock_download.return_value = sample_multiindex_df
        db_path = str(tmp_path / "test.duckdb")

        # Seed AR_ADRS tickers
        update_warehouse(db_path=db_path)

        # Add NEW ticker
        new_df = self._new_ticker_df(["2024-01-02", "2024-01-03"])
        mock_download.return_value = new_df
        add_tickers(["NEW"], db_path=db_path)

        # Subsequent update_warehouse should include NEW + all AR_ADRS
        mock_download.return_value = sample_multiindex_df
        update_warehouse(db_path=db_path)

        _, kwargs = mock_download.call_args
        fetched_tickers = kwargs["tickers"]
        assert "NEW" in fetched_tickers
        assert all(t in fetched_tickers for t in AR_ADRS)
