import datetime
from unittest.mock import patch

import pandas as pd
import pytest

from adrs_warehouse.data.fetch import update_warehouse
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

        # Second call — same data, should add 0
        result2 = update_warehouse(db_path=db_path)
        assert result2["dim_date"] == 0
        assert result2["dim_ticker"] == 0
        assert result2["fact_stock_prices"] == 0

    @patch("adrs_warehouse.data.fetch.download_adr_data")
    def test_empty_api_response(self, mock_download, tmp_path):
        mock_download.return_value = pd.DataFrame()
        db_path = str(tmp_path / "test.duckdb")

        result = update_warehouse(db_path=db_path)

        assert result["dim_date"] == 0
        assert result["dim_ticker"] == 0
        assert result["fact_stock_prices"] == 0
