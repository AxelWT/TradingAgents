"""Tests for the multi-vendor fallback in ``load_ohlcv_routed``.

Covers the resilience contract that ``market_data_validator`` (and other
DataFrame consumers) rely on: a transient transport failure in one vendor
(``ConnectionError`` / ``Timeout``) must fall through to the next vendor
instead of crashing the caller. This is the regression that caused analysis
tasks to abort when yfinance was rate-limited AND akshare's Eastmoney backend
dropped the connection (#989 / production traceback 2026-07-04).

The fallback chain under test: yfinance -> akshare -> tushare (A-shares only).
All vendor entry points are mocked; no live network calls are made.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from unittest import mock

import pandas as pd
import pytest
import requests

import tradingagents.dataflows.config as config_module
import tradingagents.dataflows.tushare_impl as tushare_impl
import tradingagents.default_config as default_config
from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorRateLimitError,
)


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _make_ohlcv(rows=10, end="2026-01-15"):
    """Minimal English-column OHLCV frame (yfinance schema)."""
    dates = pd.bdate_range(end=pd.to_datetime(end), periods=rows)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [100.0 + i for i in range(rows)],
            "High": [102.0 + i for i in range(rows)],
            "Low": [99.0 + i for i in range(rows)],
            "Close": [101.0 + i for i in range(rows)],
            "Volume": [10000 + i for i in range(rows)],
        }
    )


@pytest.mark.unit
class LoadOhlcvRoutedFallbackTests(unittest.TestCase):
    """The routed loader must absorb transient vendor failures and fall through."""

    def setUp(self):
        _reset_config()
        tushare_impl._tushare_module = None
        tushare_impl._tushare_pro_api = None
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir

    def tearDown(self):
        _reset_config()
        tushare_impl._tushare_module = None
        tushare_impl._tushare_pro_api = None

    def test_yfinance_success_skips_akshare_and_tushare(self):
        """A healthy yfinance response means neither fallback is consulted."""
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        yf_data = _make_ohlcv(rows=10, end="2026-01-15")
        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                return_value=yf_data,
            ) as mock_yf,
            mock.patch("tradingagents.dataflows.akshare_impl.load_ohlcv_akshare") as mock_ak,
            mock.patch("tradingagents.dataflows.tushare_impl.load_ohlcv_tushare") as mock_ts,
        ):
            result = load_ohlcv_routed("AAPL", "2026-01-15")
        mock_yf.assert_called_once_with("AAPL", "2026-01-15")
        mock_ak.assert_not_called()
        mock_ts.assert_not_called()
        self.assertFalse(result.empty)

    def test_yfinance_no_data_falls_to_akshare(self):
        """yfinance NoMarketDataError -> try akshare."""
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        ak_data = _make_ohlcv(rows=10, end="2026-01-15")

        def _yf_no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "yfinance returned no rows")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_yf_no_data,
            ),
            mock.patch(
                "tradingagents.dataflows.akshare_impl.load_ohlcv_akshare",
                return_value=ak_data,
            ) as mock_ak,
            mock.patch("tradingagents.dataflows.tushare_impl.load_ohlcv_tushare") as mock_ts,
        ):
            result = load_ohlcv_routed("AAPL", "2026-01-15")
        mock_ak.assert_called_once_with("AAPL", "2026-01-15")
        mock_ts.assert_not_called()
        self.assertFalse(result.empty)

    def test_yfinance_rate_limited_falls_to_akshare(self):
        """yfinance VendorRateLimitError -> try akshare."""
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        ak_data = _make_ohlcv(rows=10, end="2026-01-15")

        def _yf_rate_limited(symbol, curr_date):
            raise VendorRateLimitError("yfinance rate limit exceeded")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_yf_rate_limited,
            ),
            mock.patch(
                "tradingagents.dataflows.akshare_impl.load_ohlcv_akshare",
                return_value=ak_data,
            ) as mock_ak,
        ):
            result = load_ohlcv_routed("AAPL", "2026-01-15")
        mock_ak.assert_called_once_with("AAPL", "2026-01-15")
        self.assertFalse(result.empty)

    def test_akshare_connection_error_falls_to_tushare(self):
        """akshare ConnectionError (after its own retries) -> try tushare.

        This is the exact regression from the production traceback: yfinance
        rate-limited, akshare's Eastmoney backend dropped the connection, and
        the ConnectionError propagated uncaught — crashing the analysis task.
        The routed loader must absorb it and try tushare.
        """
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        ts_data = _make_ohlcv(rows=10, end="2026-01-15")

        def _yf_no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "yfinance returned no rows")

        def _ak_conn_error(symbol, curr_date):
            raise requests.exceptions.ConnectionError("Remote end closed connection")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_yf_no_data,
            ),
            mock.patch(
                "tradingagents.dataflows.akshare_impl.load_ohlcv_akshare",
                side_effect=_ak_conn_error,
            ) as mock_ak,
            mock.patch(
                "tradingagents.dataflows.tushare_impl.load_ohlcv_tushare",
                return_value=ts_data,
            ) as mock_ts,
        ):
            result = load_ohlcv_routed("600519", "2026-01-15")
        mock_ak.assert_called_once_with("600519", "2026-01-15")
        mock_ts.assert_called_once_with("600519", "2026-01-15")
        self.assertFalse(result.empty)

    def test_yfinance_and_akshare_connection_error_falls_to_tushare(self):
        """Both yfinance and akshare transport failures -> tushare succeeds.

        This is the exact scenario from the production traceback (0700.HK
        symbol) — except here we use an A-share so tushare can actually serve
        it. yfinance ConnectionError + akshare ConnectionError must not
        propagate; tushare gets the call.
        """
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        ts_data = _make_ohlcv(rows=10, end="2026-01-15")

        def _yf_conn_error(symbol, curr_date):
            raise requests.exceptions.ConnectionError("yfinance down")

        def _ak_conn_error(symbol, curr_date):
            raise requests.exceptions.ConnectionError("akshare down")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_yf_conn_error,
            ),
            mock.patch(
                "tradingagents.dataflows.akshare_impl.load_ohlcv_akshare",
                side_effect=_ak_conn_error,
            ),
            mock.patch(
                "tradingagents.dataflows.tushare_impl.load_ohlcv_tushare",
                return_value=ts_data,
            ) as mock_ts,
        ):
            result = load_ohlcv_routed("600519", "2026-01-15")
        mock_ts.assert_called_once_with("600519", "2026-01-15")
        self.assertFalse(result.empty)

    def test_all_vendors_no_data_raises_no_market_data(self):
        """All three vendors report clean no-data -> surface NoMarketDataError."""
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        def _no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "no rows")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_no_data,
            ),
            mock.patch(
                "tradingagents.dataflows.akshare_impl.load_ohlcv_akshare",
                side_effect=_no_data,
            ),
            mock.patch(
                "tradingagents.dataflows.tushare_impl.load_ohlcv_tushare",
                side_effect=_no_data,
            ),
        ):
            with self.assertRaises(NoMarketDataError):
                load_ohlcv_routed("999999", "2026-01-15")

    def test_all_vendors_transport_failure_raises_no_market_data(self):
        """All three vendors hit transport errors -> NoMarketDataError (not ConnectionError).

        The caller (market_data_validator) catches NoMarketDataError and
        degrades to a sentinel string. A raw ConnectionError would crash the
        LangChain ToolNode and abort the analysis task — the exact bug we're
        fixing. The routed loader must translate total failure into a clean
        NoMarketDataError regardless of the underlying exception type.
        """
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        def _conn_error(symbol, curr_date):
            raise requests.exceptions.ConnectionError("all backends down")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_conn_error,
            ),
            mock.patch(
                "tradingagents.dataflows.akshare_impl.load_ohlcv_akshare",
                side_effect=_conn_error,
            ),
            mock.patch(
                "tradingagents.dataflows.tushare_impl.load_ohlcv_tushare",
                side_effect=_conn_error,
            ),
        ):
            with self.assertRaises(NoMarketDataError):
                load_ohlcv_routed("600519", "2026-01-15")

    def test_tushare_rate_limit_raises_no_market_data(self):
        """tushare VendorRateLimitError (no further fallback) -> NoMarketDataError."""
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        def _no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "no rows")

        def _tushare_rate_limited(symbol, curr_date):
            raise VendorRateLimitError("tushare quota exceeded")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_no_data,
            ),
            mock.patch(
                "tradingagents.dataflows.akshare_impl.load_ohlcv_akshare",
                side_effect=_no_data,
            ),
            mock.patch(
                "tradingagents.dataflows.tushare_impl.load_ohlcv_tushare",
                side_effect=_tushare_rate_limited,
            ),
        ):
            with self.assertRaises(NoMarketDataError):
                load_ohlcv_routed("600519", "2026-01-15")

    def test_non_a_share_skips_tushare_after_akshare_failure(self):
        """A non-A-share symbol (e.g. 0700.HK) -> tushare NoMarketDataError is expected.

        tushare only serves A-shares, so it raises NoMarketDataError for HK
        symbols. Combined with yfinance + akshare failures, the routed loader
        must surface NoMarketDataError (not crash). This is the 0700.HK
        scenario from the production traceback.
        """
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        def _yf_no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "yfinance rate limited")

        def _ak_conn_error(symbol, curr_date):
            raise requests.exceptions.ConnectionError("akshare Eastmoney down")

        def _tushare_non_a_share(symbol, curr_date):
            # Real tushare_impl raises this for non-A-share symbols.
            raise NoMarketDataError(symbol, symbol, "Tushare only serves A-shares")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_yf_no_data,
            ),
            mock.patch(
                "tradingagents.dataflows.akshare_impl.load_ohlcv_akshare",
                side_effect=_ak_conn_error,
            ),
            mock.patch(
                "tradingagents.dataflows.tushare_impl.load_ohlcv_tushare",
                side_effect=_tushare_non_a_share,
            ) as mock_ts,
        ):
            with self.assertRaises(NoMarketDataError):
                load_ohlcv_routed("0700.HK", "2026-01-15")
        # tushare WAS tried (the bug was that it wasn't in the chain at all).
        mock_ts.assert_called_once_with("0700.HK", "2026-01-15")


if __name__ == "__main__":
    unittest.main()
