import datetime
from unittest.mock import patch

import pandas as pd

from adrs_warehouse.data.fetch import update_warehouse
from adrs_warehouse.data.transform import (
    build_date_dimension,
    build_fact_table,
    build_ticker_dimension,
)
from adrs_warehouse.database.operations import ADRDatabase


class TestCreateStarSchema:
    def test_all_tables_exist(self, db):
        tables = db.query("SHOW TABLES")
        table_names = set(tables["name"])
        assert {"dim_date", "dim_ticker", "fact_stock_prices"}.issubset(table_names)


class TestLoadDimension:
    def test_returns_correct_row_count(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        count = db.load_dimension(dim_date, "dim_date")
        assert count == 3

    def test_data_is_queryable_after_load(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        db.load_dimension(dim_date, "dim_date")

        result = db.query("SELECT * FROM dim_date WHERE year = 2024")
        assert len(result) == 3


class TestLoadFact:
    def test_returns_correct_row_count(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        fact = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)

        db.load_dimension(dim_date, "dim_date")
        db.load_dimension(dim_ticker, "dim_ticker")
        count = db.load_fact(fact)
        assert count == 6  # 3 dates x 2 tickers

    def test_fk_integrity(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        fact = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)

        db.load_dimension(dim_date, "dim_date")
        db.load_dimension(dim_ticker, "dim_ticker")
        db.load_fact(fact)

        # All fact date_ids exist in dim_date
        orphans = db.query("""
            SELECT f.date_id FROM fact_stock_prices f
            LEFT JOIN dim_date d ON f.date_id = d.date_id
            WHERE d.date_id IS NULL
        """)
        assert len(orphans) == 0


class TestQuery:
    def test_returns_expected_dataframe(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        db.load_dimension(dim_date, "dim_date")

        result = db.query("SELECT date_id, year FROM dim_date ORDER BY date_id LIMIT 1")
        assert result.iloc[0]["date_id"] == 20240102
        assert result.iloc[0]["year"] == 2024


class TestGetSchemaInfo:
    def test_returns_correct_structure(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        db.load_dimension(dim_date, "dim_date")

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
        db.load_dimension(dim_date, "dim_date")

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

        db.load_dimension(dim_date, "dim_date")
        db.load_dimension(dim_ticker, "dim_ticker")
        count = db.append_fact(fact)
        assert count == 6

    def test_skips_existing_rows(self, db, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        fact = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)

        db.load_dimension(dim_date, "dim_date")
        db.load_dimension(dim_ticker, "dim_ticker")
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
        db.load_dimension(dim_date, "dim_date")
        db.load_dimension(dim_ticker, "dim_ticker")
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
