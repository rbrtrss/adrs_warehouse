import numpy as np
import pandas as pd

from adrs_warehouse.data.transform import (
    build_date_dimension,
    build_fact_table,
    build_ticker_dimension,
    clean_data,
    clean_fact_rows,
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

    def test_empty_dataframe_returns_empty(self):
        result = clean_data(pd.DataFrame())
        assert result.empty


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

    def test_empty_dataframe_returns_empty(self):
        result = normalize_prices_long(pd.DataFrame())
        assert result.empty


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

    def test_stable_ids_for_existing_tickers(self, sample_multiindex_df):
        # GGAL=5, YPF=9 in existing map — both must keep their IDs
        existing_id_map = {"GGAL": 5, "YPF": 9}
        result = build_ticker_dimension(
            sample_multiindex_df, existing_id_map=existing_id_map
        )
        assert result.set_index("ticker_symbol").loc["GGAL", "ticker_id"] == 5
        assert result.set_index("ticker_symbol").loc["YPF", "ticker_id"] == 9

    def test_new_ticker_gets_id_above_existing_max(self, sample_multiindex_df):
        # Add TEO which sorts between GGAL and YPF alphabetically
        df = sample_multiindex_df.copy()
        for field in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
            df[("TEO", field)] = 1.0
        # GGAL=1, YPF=2 already exist; TEO is new → should get 3
        existing_id_map = {"GGAL": 1, "YPF": 2}
        result = build_ticker_dimension(df, existing_id_map=existing_id_map)
        assert result.set_index("ticker_symbol").loc["GGAL", "ticker_id"] == 1
        assert result.set_index("ticker_symbol").loc["YPF", "ticker_id"] == 2
        assert result.set_index("ticker_symbol").loc["TEO", "ticker_id"] == 3

    def test_new_ticker_does_not_collide_with_sparse_ids(self, sample_multiindex_df):
        # Existing IDs are non-contiguous: GGAL=1, YPF=10
        # New ticker BMA should get 11 (max+1), not 2
        df = sample_multiindex_df.copy()
        for field in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
            df[("BMA", field)] = 1.0
        existing_id_map = {"GGAL": 1, "YPF": 10}
        result = build_ticker_dimension(df, existing_id_map=existing_id_map)
        assert result.set_index("ticker_symbol").loc["BMA", "ticker_id"] == 11

    def test_first_run_with_empty_id_map_equals_no_arg(self, sample_multiindex_df):
        result_no_arg = build_ticker_dimension(sample_multiindex_df)
        result_empty = build_ticker_dimension(sample_multiindex_df, existing_id_map={})
        assert list(result_no_arg["ticker_id"]) == list(result_empty["ticker_id"])
        assert list(result_no_arg["ticker_symbol"]) == list(
            result_empty["ticker_symbol"]
        )


class TestCleanFactRows:
    def _row(self, **kwargs):
        defaults = {
            "date_id": 20240102,
            "ticker_id": 1,
            "open_price": 10.0,
            "high_price": 11.0,
            "low_price": 9.5,
            "close_price": 10.5,
            "adj_close_price": 10.4,
            "volume": 1000,
        }
        defaults.update(kwargs)
        return defaults

    def test_drops_rows_with_null_ohlc_fields(self):
        df = pd.DataFrame([self._row(), self._row(open_price=None)])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_drops_rows_where_high_less_than_low(self):
        df = pd.DataFrame([self._row(), self._row(high_price=8.0, low_price=9.5)])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_drops_rows_where_high_less_than_close(self):
        df = pd.DataFrame([self._row(), self._row(high_price=10.0, close_price=11.0)])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_drops_rows_where_low_greater_than_open(self):
        df = pd.DataFrame([self._row(), self._row(low_price=11.0, open_price=9.0)])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_drops_rows_with_negative_price(self):
        df = pd.DataFrame([self._row(), self._row(open_price=-1.0)])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_drops_rows_with_zero_price(self):
        df = pd.DataFrame([self._row(), self._row(close_price=0.0)])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_drops_rows_with_negative_volume(self):
        df = pd.DataFrame([self._row(), self._row(volume=-1)])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_allows_zero_volume(self):
        df = pd.DataFrame([self._row(volume=0)])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_drops_duplicate_date_ticker(self):
        df = pd.DataFrame([self._row(), self._row()])
        result = clean_fact_rows(df)
        assert len(result) == 1

    def test_valid_rows_pass_through_unchanged(self):
        rows = [
            self._row(date_id=20240102, ticker_id=1),
            self._row(date_id=20240103, ticker_id=1),
        ]
        df = pd.DataFrame(rows)
        result = clean_fact_rows(df)
        assert len(result) == 2


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

    def test_adj_close_falls_back_to_close_when_missing(self, sample_multiindex_df):
        df = sample_multiindex_df.drop(columns=["Adj Close"], level=1)
        dim_date = build_date_dimension(df)
        dim_ticker = build_ticker_dimension(df)
        result = build_fact_table(df, dim_date, dim_ticker)

        assert "adj_close_price" in result.columns
        assert (result["adj_close_price"] == result["close_price"]).all()
