import numpy as np
import pandas as pd

from adrs_warehouse.data.transform import (
    build_date_dimension,
    build_fact_table,
    build_ticker_dimension,
    clean_data,
    normalize_prices_long,
)


class TestCleanData:
    def test_removes_all_null_columns(self, sample_multiindex_df):
        df = sample_multiindex_df.copy()
        # Set one entire ticker's data to NaN
        df[("YPF", "Open")] = np.nan
        df[("YPF", "High")] = np.nan
        df[("YPF", "Low")] = np.nan
        df[("YPF", "Close")] = np.nan
        df[("YPF", "Adj Close")] = np.nan
        df[("YPF", "Volume")] = np.nan

        result = clean_data(df)
        # All YPF columns should be removed
        remaining_tickers = result.columns.get_level_values(0).unique()
        assert "YPF" not in remaining_tickers
        assert "GGAL" in remaining_tickers

    def test_keeps_columns_with_partial_data(self, sample_multiindex_df):
        df = sample_multiindex_df.copy()
        # Set only some values to NaN — column should survive
        df.iloc[0, df.columns.get_loc(("YPF", "Open"))] = np.nan

        result = clean_data(df)
        assert ("YPF", "Open") in result.columns


class TestNormalizePricesLong:
    def test_output_columns(self, sample_multiindex_df):
        result = normalize_prices_long(sample_multiindex_df)
        expected_cols = {
            "date",
            "ticker",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
        }
        assert set(result.columns) == expected_cols

    def test_correct_row_count(self, sample_multiindex_df):
        result = normalize_prices_long(sample_multiindex_df)
        n_dates = len(sample_multiindex_df.index)
        n_tickers = len(sample_multiindex_df.columns.get_level_values(0).unique())
        assert len(result) == n_dates * n_tickers

    def test_column_names_are_lowercase_underscored(self, sample_multiindex_df):
        result = normalize_prices_long(sample_multiindex_df)
        for col in result.columns:
            assert col == col.lower()
            assert " " not in col


class TestBuildDateDimension:
    def test_derived_fields_for_known_date(self, sample_multiindex_df):
        result = build_date_dimension(sample_multiindex_df)
        # 2024-01-02 is a Tuesday
        row = result[result["date_id"] == 20240102].iloc[0]
        assert row["year"] == 2024
        assert row["quarter"] == 1
        assert row["month"] == 1
        assert row["month_name"] == "January"
        assert row["day"] == 2
        assert row["day_of_week"] == 1  # Tuesday
        assert row["day_name"] == "Tuesday"
        assert row["is_weekend"] is False or not row["is_weekend"]

    def test_correct_number_of_rows(self, sample_multiindex_df):
        result = build_date_dimension(sample_multiindex_df)
        assert len(result) == 3

    def test_week_of_year(self, sample_multiindex_df):
        result = build_date_dimension(sample_multiindex_df)
        row = result[result["date_id"] == 20240102].iloc[0]
        assert row["week_of_year"] == 1


class TestBuildTickerDimension:
    def test_correct_ticker_id_sequence(self, sample_multiindex_df):
        result = build_ticker_dimension(sample_multiindex_df)
        assert list(result["ticker_id"]) == [1, 2]

    def test_fills_metadata_from_ticker_metadata(self, sample_multiindex_df):
        result = build_ticker_dimension(sample_multiindex_df)
        ggal_row = result[result["ticker_symbol"] == "GGAL"].iloc[0]
        assert ggal_row["company_name"] == "Grupo Financiero Galicia S.A."
        assert ggal_row["exchange"] == "NASDAQ"
        assert ggal_row["sector"] == "Financial Services"
        assert ggal_row["country"] == "Argentina"

    def test_unknown_ticker_gets_defaults(self, sample_multiindex_df):
        # Add a fake ticker not in TICKER_METADATA
        df = sample_multiindex_df.copy()
        for field in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
            df[("FAKE", field)] = 1.0

        result = build_ticker_dimension(df, metadata={})
        fake_row = result[result["ticker_symbol"] == "FAKE"].iloc[0]
        assert fake_row["company_name"] == "FAKE"
        assert fake_row["exchange"] == "Unknown"
        assert fake_row["sector"] == "Unknown"
        assert fake_row["country"] == "Unknown"


class TestBuildFactTable:
    def test_foreign_keys_map_correctly(self, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        result = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)

        # All date_ids should exist in dim_date
        assert set(result["date_id"]).issubset(set(dim_date["date_id"]))
        # All ticker_ids should exist in dim_ticker
        assert set(result["ticker_id"]).issubset(set(dim_ticker["ticker_id"]))

    def test_volume_is_int64(self, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)
        result = build_fact_table(sample_multiindex_df, dim_date, dim_ticker)
        assert result["volume"].dtype == pd.Int64Dtype()

    def test_rows_with_missing_fks_are_dropped(self, sample_multiindex_df):
        dim_date = build_date_dimension(sample_multiindex_df)
        dim_ticker = build_ticker_dimension(sample_multiindex_df)

        # Only keep one date in dim_date so the other dates' FKs become NaN
        dim_date_partial = dim_date.head(1)
        result = build_fact_table(sample_multiindex_df, dim_date_partial, dim_ticker)

        # Should only have rows matching the single date
        assert len(result) == 2  # 1 date x 2 tickers
