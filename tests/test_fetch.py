from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from adrs_warehouse.data.fetch import (
    build_ticker_dimension,
    download_adr_data,
    get_last_closed_date,
    update_warehouse,
)


class TestGetLastClosedDate:
    def _make_et(self, year, month, day, hour, minute=0):
        return datetime(
            year, month, day, hour, minute, tzinfo=ZoneInfo("America/New_York")
        )

    @patch("adrs_warehouse.data.fetch.datetime")
    def test_before_close_on_weekday_returns_yesterday(self, mock_dt):
        # Tuesday 2026-03-03 at 15:59 ET → returns Monday 2026-03-02
        mock_dt.now.return_value = self._make_et(2026, 3, 3, 15, 59)
        result = get_last_closed_date()
        assert result == date(2026, 3, 2)

    @patch("adrs_warehouse.data.fetch.datetime")
    def test_at_close_on_weekday_returns_today(self, mock_dt):
        # Tuesday 2026-03-03 at 16:00 ET → returns Tuesday 2026-03-03
        mock_dt.now.return_value = self._make_et(2026, 3, 3, 16, 0)
        result = get_last_closed_date()
        assert result == date(2026, 3, 3)

    @patch("adrs_warehouse.data.fetch.datetime")
    def test_after_close_on_weekday_returns_today(self, mock_dt):
        # Wednesday 2026-03-04 at 18:00 ET → returns Wednesday 2026-03-04
        mock_dt.now.return_value = self._make_et(2026, 3, 4, 18, 0)
        result = get_last_closed_date()
        assert result == date(2026, 3, 4)

    @patch("adrs_warehouse.data.fetch.datetime")
    def test_saturday_returns_friday(self, mock_dt):
        # Saturday 2026-03-07 any time → returns Friday 2026-03-06
        mock_dt.now.return_value = self._make_et(2026, 3, 7, 10, 0)
        result = get_last_closed_date()
        assert result == date(2026, 3, 6)

    @patch("adrs_warehouse.data.fetch.datetime")
    def test_sunday_returns_friday(self, mock_dt):
        # Sunday 2026-03-08 any time → returns Friday 2026-03-06
        mock_dt.now.return_value = self._make_et(2026, 3, 8, 20, 0)
        result = get_last_closed_date()
        assert result == date(2026, 3, 6)


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
    def test_passes_end_date_to_yf_download(self, mock_yf):
        mock_yf.download.return_value = pd.DataFrame()

        download_adr_data(
            tickers=["YPF"], start_date="2026-01-01", end_date="2026-03-06"
        )

        call_kwargs = mock_yf.download.call_args
        assert call_kwargs[1]["end"] == "2026-03-06"

    @patch("adrs_warehouse.data.fetch.yf")
    def test_end_date_none_by_default(self, mock_yf):
        mock_yf.download.return_value = pd.DataFrame()

        download_adr_data()

        call_kwargs = mock_yf.download.call_args
        assert call_kwargs[1]["end"] is None

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
        assert not ypf_row["has_data"]


class TestUpdateWarehouseEndDateCapping:
    @patch("adrs_warehouse.data.fetch.create_database")
    @patch("adrs_warehouse.data.fetch.get_last_closed_date")
    @patch("adrs_warehouse.data.fetch.yf")
    def test_passes_capped_end_date_to_download(
        self, mock_yf, mock_last_closed, mock_create_db
    ):
        mock_last_closed.return_value = date(2026, 3, 5)

        mock_db = MagicMock()
        mock_db.get_last_loaded_date.return_value = None
        mock_db.get_ticker_id_map.return_value = {}
        mock_create_db.return_value = mock_db
        mock_yf.download.return_value = pd.DataFrame()

        update_warehouse()

        call_kwargs = mock_yf.download.call_args
        # end is exclusive, so last_closed_date + 1 day = 2026-03-06
        assert call_kwargs[1]["end"] == "2026-03-06"
