from unittest.mock import patch, MagicMock

import pandas as pd

from adrs_warehouse.data.fetch import build_ticker_dimension, download_adr_data


class TestDownloadAdrData:
    @patch("adrs_warehouse.data.fetch.yf")
    def test_calls_yf_download_with_defaults(self, mock_yf):
        mock_yf.download.return_value = pd.DataFrame()

        download_adr_data()

        mock_yf.download.assert_called_once()
        call_kwargs = mock_yf.download.call_args
        # Default tickers from config
        assert len(call_kwargs[0][0]) == 13
        assert call_kwargs[1]["start"] == "2018-01-01"
        assert call_kwargs[1]["group_by"] == "ticker"

    @patch("adrs_warehouse.data.fetch.yf")
    def test_passes_custom_tickers_and_start_date(self, mock_yf):
        mock_yf.download.return_value = pd.DataFrame()

        download_adr_data(tickers=["YPF", "GGAL"], start_date="2020-06-01")

        call_kwargs = mock_yf.download.call_args
        assert call_kwargs[0][0] == ["YPF", "GGAL"]
        assert call_kwargs[1]["start"] == "2020-06-01"

    @patch("adrs_warehouse.data.fetch.yf")
    def test_returns_mock_dataframe(self, mock_yf):
        expected = pd.DataFrame({"a": [1, 2, 3]})
        mock_yf.download.return_value = expected

        result = download_adr_data()
        pd.testing.assert_frame_equal(result, expected)


class TestBuildTickerDimensionFetch:
    def test_correct_columns(self, sample_multiindex_df):
        result = build_ticker_dimension(sample_multiindex_df)
        assert set(result.columns) == {"ticker", "has_data", "first_date", "last_date"}

    def test_has_data_true_for_valid_tickers(self, sample_multiindex_df):
        result = build_ticker_dimension(sample_multiindex_df)
        assert all(result["has_data"])

    def test_handles_ticker_with_no_data(self, sample_multiindex_df):
        import numpy as np

        df = sample_multiindex_df.copy()
        # Set all YPF data to NaN
        for field in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
            df[("YPF", field)] = np.nan

        result = build_ticker_dimension(df)
        ypf_row = result[result["ticker"] == "YPF"].iloc[0]
        assert ypf_row["has_data"] == False
