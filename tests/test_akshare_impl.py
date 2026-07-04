"""Tests for the AKShare vendor implementation.

Covers symbol classification, column normalization, cache behavior, and the
graceful-degradation path (akshare not installed → VendorNotConfiguredError →
router falls through to the next vendor).

Network calls are mocked throughout; no live AKShare requests are made.
"""

import copy
import os
import tempfile
import unittest
from unittest import mock

import pandas as pd
import pytest
import requests

import tradingagents.dataflows.akshare_impl as akshare_impl
import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorNotConfiguredError


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _make_ohlcv_frame(rows=5, end="2026-01-15"):
    """Build a minimal OHLCV frame with Chinese column names (AKShare's schema)."""
    end_dt = pd.to_datetime(end)
    dates = pd.date_range(end=end_dt, periods=rows, freq="B")
    df = pd.DataFrame(
        {
            "日期": dates.strftime("%Y-%m-%d"),
            "开盘": [100.0 + i for i in range(rows)],
            "收盘": [101.0 + i for i in range(rows)],
            "最高": [102.0 + i for i in range(rows)],
            "最低": [99.0 + i for i in range(rows)],
            "成交量": [10000 + i for i in range(rows)],
        }
    )
    return df


@pytest.mark.unit
class DetectMarketTests(unittest.TestCase):
    """_detect_market must classify symbols without any network calls."""

    def test_a_share_bare_code(self):
        self.assertEqual(akshare_impl._detect_market("600519"), "a_share")

    def test_a_share_with_suffix(self):
        for sym in ("600519.SH", "000001.SZ", "600000.SS", "830799.BJ"):
            self.assertEqual(akshare_impl._detect_market(sym), "a_share", sym)

    def test_a_share_lowercase_suffix(self):
        self.assertEqual(akshare_impl._detect_market("600519.sh"), "a_share")

    def test_hk_with_suffix(self):
        for sym in ("0700.HK", "9988.HK", "1.HK", "9999.HK"):
            self.assertEqual(akshare_impl._detect_market(sym), "hk", sym)

    def test_hk_lowercase_suffix(self):
        self.assertEqual(akshare_impl._detect_market("0700.hk"), "hk")

    def test_us_equity(self):
        for sym in ("AAPL", "TSLA", "GOOG", "BRK.B"):
            self.assertEqual(akshare_impl._detect_market(sym), "us", sym)

    def test_yahoo_index_not_supported(self):
        self.assertIsNone(akshare_impl._detect_market("^GSPC"))

    def test_yahoo_future_not_supported(self):
        self.assertIsNone(akshare_impl._detect_market("GC=F"))

    def test_forex_not_supported(self):
        self.assertIsNone(akshare_impl._detect_market("EURUSD=X"))

    def test_crypto_not_supported(self):
        self.assertIsNone(akshare_impl._detect_market("BTC-USD"))

    def test_empty_or_garbage(self):
        self.assertIsNone(akshare_impl._detect_market(""))
        self.assertIsNone(akshare_impl._detect_market("123"))
        self.assertIsNone(akshare_impl._detect_market(None))


@pytest.mark.unit
class ToAkshareAShareTests(unittest.TestCase):
    def test_strips_exchange_suffix(self):
        self.assertEqual(akshare_impl._to_akshare_a_share("600519.SH"), "600519")
        self.assertEqual(akshare_impl._to_akshare_a_share("000001.SZ"), "000001")

    def test_passes_through_bare_code(self):
        self.assertEqual(akshare_impl._to_akshare_a_share("600519"), "600519")


@pytest.mark.unit
class ToAkshareHkTests(unittest.TestCase):
    def test_zero_pads_to_five_digits(self):
        self.assertEqual(akshare_impl._to_akshare_hk("0700.HK"), "00700")
        self.assertEqual(akshare_impl._to_akshare_hk("9988.HK"), "09988")

    def test_short_code_pads(self):
        self.assertEqual(akshare_impl._to_akshare_hk("1.HK"), "00001")

    def test_already_five_digits(self):
        self.assertEqual(akshare_impl._to_akshare_hk("99999.HK"), "99999")


@pytest.mark.unit
class NormalizeColumnsTests(unittest.TestCase):
    def test_renames_chinese_columns(self):
        df = _make_ohlcv_frame(rows=3)
        result = akshare_impl._normalize_akshare_columns(df)
        self.assertIn("Date", result.columns)
        self.assertIn("Open", result.columns)
        self.assertIn("Close", result.columns)
        self.assertIn("High", result.columns)
        self.assertIn("Low", result.columns)
        self.assertIn("Volume", result.columns)

    def test_drops_auxiliary_chinese_columns(self):
        df = _make_ohlcv_frame(rows=2)
        df["成交额"] = [1e6, 1.1e6]
        df["换手率"] = [0.5, 0.6]
        result = akshare_impl._normalize_akshare_columns(df)
        self.assertNotIn("成交额", result.columns)
        self.assertNotIn("换手率", result.columns)

    def test_empty_frame_passthrough(self):
        self.assertTrue(akshare_impl._normalize_akshare_columns(pd.DataFrame()).empty)


@pytest.mark.unit
class GetAkshareNotInstalledTests(unittest.TestCase):
    """When akshare isn't installed, _get_akshare raises VendorNotConfiguredError."""

    def setUp(self):
        # Reset the cached module so the import path runs again.
        akshare_impl._akshare_module = None

    def tearDown(self):
        akshare_impl._akshare_module = None

    def test_raises_vendor_not_configured(self):
        with mock.patch.dict("sys.modules", {"akshare": None}):
            with self.assertRaises(VendorNotConfiguredError):
                akshare_impl._get_akshare()

    def test_get_stock_data_raises_not_configured(self):
        with mock.patch.dict("sys.modules", {"akshare": None}):
            with self.assertRaises(VendorNotConfiguredError):
                akshare_impl.get_stock_data("AAPL", "2026-01-01", "2026-01-10")


@pytest.mark.unit
class ToAkshareUsTests(unittest.TestCase):
    """_to_akshare_us probes exchange prefixes and caches the winner."""

    def setUp(self):
        akshare_impl._us_symbol_prefix_cache.clear()
        akshare_impl._akshare_module = None

    def tearDown(self):
        akshare_impl._us_symbol_prefix_cache.clear()
        akshare_impl._akshare_module = None

    def test_returns_cached_prefix_without_probe(self):
        akshare_impl._us_symbol_prefix_cache["AAPL"] = "106"
        # Even if akshare is unavailable, cached prefix is used.
        result = akshare_impl._to_akshare_us("AAPL")
        self.assertEqual(result, "106.AAPL")

    def test_probes_prefixes_and_caches_winner(self):
        mock_ak = mock.Mock()
        # NASDAQ (106) returns empty, NYSE (105) returns data.
        mock_ak.stock_us_hist.side_effect = [
            pd.DataFrame(),  # 106 probe
            _make_ohlcv_frame(rows=2),  # 105 probe → hit
        ]
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            result = akshare_impl._to_akshare_us("BRK.B")
        self.assertEqual(result, "105.BRK.B")
        self.assertEqual(akshare_impl._us_symbol_prefix_cache["BRK.B"], "105")


@pytest.mark.unit
class LoadOhlcvAkshareTests(unittest.TestCase):
    """load_ohlcv_akshare: cache hit, cache miss, no-data, stale rejection."""

    def setUp(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir

    def tearDown(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()

    def test_a_share_download_and_cache(self):
        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.return_value = _make_ohlcv_frame(rows=10, end="2026-01-15")
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            data = akshare_impl.load_ohlcv_akshare("600519", "2026-01-15")
        self.assertFalse(data.empty)
        self.assertIn("Close", data.columns)
        # All rows are on or before curr_date.
        self.assertTrue((data["Date"] <= pd.Timestamp("2026-01-15")).all())
        # Second call should hit the cache (no new download).
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            akshare_impl.load_ohlcv_akshare("600519", "2026-01-15")
        self.assertEqual(mock_ak.stock_zh_a_hist.call_count, 1)

    def test_us_symbol_uses_us_endpoint(self):
        akshare_impl._us_symbol_prefix_cache["AAPL"] = "106"
        mock_ak = mock.Mock()
        mock_ak.stock_us_hist.return_value = _make_ohlcv_frame(rows=10, end="2026-01-15")
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            akshare_impl.load_ohlcv_akshare("AAPL", "2026-01-15")
        mock_ak.stock_us_hist.assert_called_once()

    def test_hk_symbol_uses_hk_endpoint(self):
        mock_ak = mock.Mock()
        mock_ak.stock_hk_hist.return_value = _make_ohlcv_frame(rows=10, end="2026-01-15")
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            data = akshare_impl.load_ohlcv_akshare("0700.HK", "2026-01-15")
        mock_ak.stock_hk_hist.assert_called_once()
        # Verify the symbol was zero-padded to 5 digits.
        call_args = mock_ak.stock_hk_hist.call_args
        self.assertEqual(call_args.kwargs["symbol"], "00700")
        self.assertFalse(data.empty)

    def test_empty_result_raises_no_data(self):
        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame()
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            with self.assertRaises(NoMarketDataError):
                akshare_impl.load_ohlcv_akshare("999999", "2026-01-15")

    def test_unsupported_symbol_raises_no_data(self):
        # ^GSPC is an index — AKShare can't serve it.
        with self.assertRaises(NoMarketDataError):
            akshare_impl.load_ohlcv_akshare("^GSPC", "2026-01-15")


@pytest.mark.unit
class AkshareRetryTests(unittest.TestCase):
    """_akshare_retry absorbs transient transport blips inside the vendor.

    A single ``RemoteDisconnected``/``ConnectionError`` used to surface straight
    to the router, which (when yfinance + alpha_vantage were also down) aborted
    the whole analysis task. The retry now swallows the blip; exhaustion still
    propagates so the router's generic fallback remains intact.
    """

    def setUp(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir
        # Patch time.sleep so retries don't slow the suite.
        self._sleep_patcher = mock.patch.object(akshare_impl.time, "sleep")
        self._sleep_patcher.start()

    def tearDown(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()
        self._sleep_patcher.stop()

    def test_transient_error_retried_then_succeeds(self):
        mock_ak = mock.Mock()
        frame = _make_ohlcv_frame(rows=10, end="2026-01-15")
        # First attempt drops the connection; second succeeds.
        mock_ak.stock_hk_hist.side_effect = [
            requests.exceptions.ConnectionError("Remote end closed connection"),
            frame,
        ]
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            data = akshare_impl.load_ohlcv_akshare("0700.HK", "2026-01-15")
        self.assertFalse(data.empty)
        self.assertEqual(mock_ak.stock_hk_hist.call_count, 2)
        # Retry slept once between the failed and successful attempt.
        akshare_impl.time.sleep.assert_called_once()

    def test_transient_error_exhausted_propagates(self):
        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.side_effect = requests.exceptions.ConnectionError("down")
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            with self.assertRaises(requests.exceptions.ConnectionError):
                akshare_impl.load_ohlcv_akshare("600519", "2026-01-15")
        # Initial attempt + 3 retries = 4 calls before giving up.
        self.assertEqual(mock_ak.stock_zh_a_hist.call_count, 4)

    def test_no_market_data_not_retried(self):
        # An empty result is a deterministic NoMarketDataError, not a blip —
        # it must surface immediately without burning retries.
        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame()
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            with self.assertRaises(NoMarketDataError):
                akshare_impl.load_ohlcv_akshare("999999", "2026-01-15")
        self.assertEqual(mock_ak.stock_zh_a_hist.call_count, 1)
        akshare_impl.time.sleep.assert_not_called()


@pytest.mark.unit
class GetStockDataTests(unittest.TestCase):
    """get_stock_data: output format and date-range slicing."""

    def setUp(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir

    def tearDown(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()

    def test_returns_csv_with_header(self):
        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.return_value = _make_ohlcv_frame(rows=10, end="2026-01-15")
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            result = akshare_impl.get_stock_data("600519", "2026-01-13", "2026-01-15")
        self.assertIn("# Stock data for 600519", result)
        self.assertIn("# Total records:", result)
        self.assertIn("Close", result)

    def test_empty_range_raises_no_data(self):
        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.return_value = _make_ohlcv_frame(rows=5, end="2026-01-15")
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            with self.assertRaises(NoMarketDataError):
                # Range entirely before available data.
                akshare_impl.get_stock_data("600519", "2025-01-01", "2025-01-05")


@pytest.mark.unit
class GetIndicatorsTests(unittest.TestCase):
    """get_indicators: computes a stockstats indicator over AKShare OHLCV."""

    def setUp(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir

    def tearDown(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()

    def test_rsi_indicator_returns_window(self):
        # Need enough rows for stockstats to compute RSI (14-period minimum).
        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.return_value = _make_ohlcv_frame(rows=60, end="2026-01-15")
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            result = akshare_impl.get_indicators("600519", "rsi", "2026-01-15", 5)
        self.assertIn("## rsi values", result)

    def test_unsupported_indicator_raises_value_error(self):
        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.return_value = _make_ohlcv_frame(rows=5, end="2026-01-15")
        with mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak):
            with self.assertRaises(ValueError):
                akshare_impl.get_indicators("600519", "bogus_ind", "2026-01-15", 5)


@pytest.mark.unit
class RouterSkipsAkshareWhenNotConfiguredTests(unittest.TestCase):
    """When akshare isn't installed, the router must skip it and fall through."""

    def setUp(self):
        _reset_config()
        akshare_impl._akshare_module = None

    def tearDown(self):
        _reset_config()
        akshare_impl._akshare_module = None

    def test_akshare_not_configured_falls_through_to_yfinance(self):
        from tradingagents.dataflows import interface

        config_module._config["data_vendors"]["core_stock_apis"] = "akshare,yfinance"
        with mock.patch.dict("sys.modules", {"akshare": None}):
            with mock.patch.dict(
                interface.VENDOR_METHODS,
                {
                    "get_stock_data": {
                        "akshare": interface.VENDOR_METHODS["get_stock_data"]["akshare"],
                        "yfinance": lambda *a, **k: "YF_DATA",
                    }
                },
                clear=False,
            ):
                result = interface.route_to_vendor(
                    "get_stock_data", "AAPL", "2026-01-01", "2026-01-10"
                )
        self.assertEqual(result, "YF_DATA")


@pytest.mark.unit
class LoadOhlcvRoutedTests(unittest.TestCase):
    """load_ohlcv_routed: yfinance failure falls back to akshare (DataFrame contract)."""

    def setUp(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir

    def tearDown(self):
        _reset_config()
        akshare_impl._akshare_module = None
        akshare_impl._us_symbol_prefix_cache.clear()

    def test_yfinance_success_does_not_call_akshare(self):
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        yf_data = _make_ohlcv_frame(rows=10, end="2026-01-15")
        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                return_value=yf_data,
            ) as mock_load,
            mock.patch.object(akshare_impl, "_get_akshare") as mock_get_ak,
        ):
            result = load_ohlcv_routed("AAPL", "2026-01-15")
        mock_load.assert_called_once_with("AAPL", "2026-01-15")
        mock_get_ak.assert_not_called()
        self.assertFalse(result.empty)

    def test_yfinance_no_data_falls_back_to_akshare(self):
        from tradingagents.dataflows.errors import NoMarketDataError
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        mock_ak = mock.Mock()
        mock_ak.stock_us_hist.return_value = _make_ohlcv_frame(rows=10, end="2026-01-15")
        akshare_impl._us_symbol_prefix_cache["AAPL"] = "106"

        def _yf_no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "yfinance returned no rows")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_yf_no_data,
            ),
            mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak),
        ):
            result = load_ohlcv_routed("AAPL", "2026-01-15")
        mock_ak.stock_us_hist.assert_called_once()
        self.assertFalse(result.empty)

    def test_both_vendors_no_data_raises(self):
        from tradingagents.dataflows.errors import NoMarketDataError
        from tradingagents.dataflows.stockstats_utils import load_ohlcv_routed

        def _yf_no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "yfinance returned no rows")

        mock_ak = mock.Mock()
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame()

        # 999999 is a 6-digit code -> tushare would be tried as a third
        # fallback. Patch load_ohlcv_tushare to also raise NoMarketDataError
        # so all three vendors are exhausted and the routed loader surfaces
        # the no-data verdict.
        def _tushare_no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "tushare returned no rows")

        with (
            mock.patch(
                "tradingagents.dataflows.stockstats_utils.load_ohlcv",
                side_effect=_yf_no_data,
            ),
            mock.patch.object(akshare_impl, "_get_akshare", return_value=mock_ak),
            mock.patch(
                "tradingagents.dataflows.tushare_impl.load_ohlcv_tushare",
                side_effect=_tushare_no_data,
            ),
        ):
            with self.assertRaises(NoMarketDataError):
                load_ohlcv_routed("999999", "2026-01-15")


if __name__ == "__main__":
    unittest.main()
