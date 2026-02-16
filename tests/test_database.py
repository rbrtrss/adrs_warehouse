import pandas as pd

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
