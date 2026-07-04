"""Tests for the Tushare Pro vendor implementation.

Covers symbol classification, ts_code normalization, column normalization,
cache behavior, the graceful-degradation path (tushare not installed OR
TUSHARE_API_KEY unset -> VendorNotConfiguredError -> router falls through to
the next vendor), rate-limit classification, and the financial-statement
transpose.

Network calls are mocked throughout; no live Tushare requests are made.
"""

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
    VendorNotConfiguredError,
)
from tradingagents.dataflows.tushare_impl import (
    TushareNotConfiguredError,
    TushareRateLimitError,
)


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _reset_tushare_cache():
    """Reset the cached tushare module + pro_api so each test re-imports."""
    tushare_impl._tushare_module = None
    tushare_impl._tushare_pro_api = None


def _make_tushare_ohlcv_frame(rows=5, end="2026-01-15"):
    """Build a minimal OHLCV frame with Tushare's lowercase column schema."""
    end_dt = pd.to_datetime(end)
    dates = pd.date_range(end=end_dt, periods=rows, freq="B")
    df = pd.DataFrame(
        {
            "ts_code": ["600519.SH"] * rows,
            "trade_date": dates.strftime("%Y%m%d"),
            "open": [100.0 + i for i in range(rows)],
            "high": [102.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [101.0 + i for i in range(rows)],
            "vol": [10000.0 + i for i in range(rows)],
            "amount": [1e6 + i for i in range(rows)],
        }
    )
    return df


def _make_stock_basic_frame():
    return pd.DataFrame(
        [
            {
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "enname": "Kweichow Moutai",
                "area": "贵州",
                "industry": "白酒",
                "market": "主板",
                "exchange": "SSE",
                "list_date": "20010827",
            }
        ]
    )


def _make_daily_basic_frame():
    return pd.DataFrame(
        [
            {
                "ts_code": "600519.SH",
                "trade_date": "20260115",
                "close": 1800.0,
                "pe_ttm": 30.5,
                "pb": 10.2,
                "ps_ttm": 15.0,
                "dv_ttm": 1.5,
                "total_mv": 2.26e7,  # 万元
                "circ_mv": 2.26e7,
                "total_share": 12562.0,
                "float_share": 12562.0,
                "turnover_rate": 0.3,
            }
        ]
    )


def _make_balancesheet_frame():
    return pd.DataFrame(
        [
            {
                "ts_code": "600519.SH",
                "ann_date": "20240328",
                "f_ann_date": "20240328",
                "end_date": "20231231",
                "report_type": "1",
                "update_flag": "1",
                "total_assets": 1e8,
                "total_liab": 5e7,
            },
            {
                "ts_code": "600519.SH",
                "ann_date": "20230831",
                "f_ann_date": "20230831",
                "end_date": "20230630",
                "report_type": "1",
                "update_flag": "1",
                "total_assets": 9.5e7,
                "total_liab": 4.8e7,
            },
        ]
    )


@pytest.mark.unit
class DetectMarketTests(unittest.TestCase):
    """_detect_market must classify A-share symbols without any network calls."""

    def test_a_share_bare_code(self):
        self.assertEqual(tushare_impl._detect_market("600519"), "a_share")

    def test_a_share_with_suffix(self):
        for sym in ("600519.SH", "000001.SZ", "600000.SS", "830799.BJ"):
            self.assertEqual(tushare_impl._detect_market(sym), "a_share", sym)

    def test_a_share_lowercase_suffix(self):
        self.assertEqual(tushare_impl._detect_market("600519.sh"), "a_share")

    def test_star_market_code(self):
        # 688xxx is Shanghai STAR Market (科创板) — still SH.
        self.assertEqual(tushare_impl._detect_market("688981"), "a_share")

    def test_chinext_code(self):
        # 300xxx is ChiNext (创业板) — still SZ.
        self.assertEqual(tushare_impl._detect_market("300750"), "a_share")

    def test_bse_code(self):
        # 8xxxxx is Beijing Stock Exchange.
        self.assertEqual(tushare_impl._detect_market("830799"), "a_share")

    def test_hk_not_supported(self):
        # Tushare here only serves A-shares; HK falls through to yfinance.
        self.assertIsNone(tushare_impl._detect_market("0700.HK"))

    def test_us_equity_not_supported(self):
        for sym in ("AAPL", "TSLA", "GOOG", "BRK.B"):
            self.assertIsNone(tushare_impl._detect_market(sym), sym)

    def test_yahoo_index_not_supported(self):
        self.assertIsNone(tushare_impl._detect_market("^GSPC"))

    def test_yahoo_future_not_supported(self):
        self.assertIsNone(tushare_impl._detect_market("GC=F"))

    def test_forex_not_supported(self):
        self.assertIsNone(tushare_impl._detect_market("EURUSD=X"))

    def test_crypto_not_supported(self):
        self.assertIsNone(tushare_impl._detect_market("BTC-USD"))

    def test_empty_or_garbage(self):
        self.assertIsNone(tushare_impl._detect_market(""))
        self.assertIsNone(tushare_impl._detect_market("123"))
        self.assertIsNone(tushare_impl._detect_market(None))


@pytest.mark.unit
class ToTushareTsCodeTests(unittest.TestCase):
    """_to_tushare_ts_code normalizes to Tushare's ts_code form."""

    def test_bare_code_infers_sh(self):
        # 6xxxxx -> SH
        self.assertEqual(tushare_impl._to_tushare_ts_code("600519"), "600519.SH")
        # 688xxx STAR Market -> SH
        self.assertEqual(tushare_impl._to_tushare_ts_code("688981"), "688981.SH")

    def test_bare_code_infers_sz(self):
        # 0xxxxx / 3xxxxx -> SZ
        self.assertEqual(tushare_impl._to_tushare_ts_code("000001"), "000001.SZ")
        self.assertEqual(tushare_impl._to_tushare_ts_code("300750"), "300750.SZ")

    def test_bare_code_infers_bj(self):
        # 8/4/9xxxxx -> BJ
        self.assertEqual(tushare_impl._to_tushare_ts_code("830799"), "830799.BJ")

    def test_explicit_suffix_preserved(self):
        self.assertEqual(tushare_impl._to_tushare_ts_code("600519.SH"), "600519.SH")
        self.assertEqual(tushare_impl._to_tushare_ts_code("000001.SZ"), "000001.SZ")
        self.assertEqual(tushare_impl._to_tushare_ts_code("830799.BJ"), "830799.BJ")

    def test_ss_suffix_normalized_to_sh(self):
        # Sina's .SS synonym must become Tushare's .SH.
        self.assertEqual(tushare_impl._to_tushare_ts_code("600000.SS"), "600000.SH")

    def test_lowercase_normalized(self):
        self.assertEqual(tushare_impl._to_tushare_ts_code("600519.sh"), "600519.SH")


@pytest.mark.unit
class NormalizeColumnsTests(unittest.TestCase):
    def test_renames_lowercase_columns(self):
        df = _make_tushare_ohlcv_frame(rows=3)
        result = tushare_impl._normalize_tushare_columns(df)
        for col in ("Date", "Open", "High", "Low", "Close", "Volume", "Amount"):
            self.assertIn(col, result.columns)

    def test_converts_trade_date_to_timestamp(self):
        df = _make_tushare_ohlcv_frame(rows=2)
        result = tushare_impl._normalize_tushare_columns(df)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(result["Date"]))

    def test_sorts_ascending_by_date(self):
        df = _make_tushare_ohlcv_frame(rows=5, end="2026-01-15")
        # Reverse the order so the frame starts with the latest date.
        df = df.iloc[::-1].reset_index(drop=True)
        result = tushare_impl._normalize_tushare_columns(df)
        self.assertTrue(result["Date"].is_monotonic_increasing)

    def test_drops_ts_code_column(self):
        df = _make_tushare_ohlcv_frame(rows=2)
        result = tushare_impl._normalize_tushare_columns(df)
        self.assertNotIn("ts_code", result.columns)

    def test_empty_frame_passthrough(self):
        self.assertTrue(tushare_impl._normalize_tushare_columns(pd.DataFrame()).empty)


@pytest.mark.unit
class ClassifyTushareErrorTests(unittest.TestCase):
    """_classify_tushare_error routes quota/permission messages to rate-limit."""

    def test_chinese_quota_message_becomes_rate_limit(self):
        exc = Exception("抱歉，您每天最多访问该接口 2 次")
        result = tushare_impl._classify_tushare_error(exc)
        self.assertIsInstance(result, TushareRateLimitError)

    def test_points_message_becomes_rate_limit(self):
        exc = Exception("积分不足，权限不够")
        result = tushare_impl._classify_tushare_error(exc)
        self.assertIsInstance(result, TushareRateLimitError)

    def test_english_rate_limit_message_becomes_rate_limit(self):
        exc = Exception("rate limit exceeded")
        result = tushare_impl._classify_tushare_error(exc)
        self.assertIsInstance(result, TushareRateLimitError)

    def test_other_exception_passes_through(self):
        exc = ValueError("bad parameter")
        result = tushare_impl._classify_tushare_error(exc)
        self.assertIs(result, exc)


@pytest.mark.unit
class GetTushareNotConfiguredTests(unittest.TestCase):
    """When tushare isn't installed, _get_tushare_pro raises VendorNotConfiguredError."""

    def setUp(self):
        _reset_tushare_cache()

    def tearDown(self):
        _reset_tushare_cache()

    def test_missing_package_raises_not_configured(self):
        with mock.patch.dict("sys.modules", {"tushare": None}):
            with self.assertRaises(VendorNotConfiguredError):
                tushare_impl._get_tushare_pro()

    def test_missing_api_key_raises_not_configured(self):
        # Tushare package is "installed" (mocked) but the token is missing.
        fake_ts = mock.Mock()
        with (
            mock.patch.dict("sys.modules", {"tushare": fake_ts}),
            mock.patch.object(
                tushare_impl, "_get_api_key", side_effect=TushareNotConfiguredError("no key")
            ),self.assertRaises(VendorNotConfiguredError)
        ):
            tushare_impl._get_tushare_pro()

    def test_get_stock_data_raises_not_configured_when_package_missing(self):
        with mock.patch.dict("sys.modules", {"tushare": None}):
            with self.assertRaises(VendorNotConfiguredError):
                tushare_impl.get_stock_data("600519", "2026-01-01", "2026-01-10")


@pytest.mark.unit
class TushareRetryTests(unittest.TestCase):
    """_tushare_retry absorbs transient transport blips inside the vendor."""

    def setUp(self):
        _reset_config()
        _reset_tushare_cache()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir
        self._sleep_patcher = mock.patch.object(tushare_impl.time, "sleep")
        self._sleep_patcher.start()

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()
        self._sleep_patcher.stop()

    def test_transient_error_retried_then_succeeds(self):
        mock_pro = mock.Mock()
        frame = _make_tushare_ohlcv_frame(rows=10, end="2026-01-15")
        # First attempt drops the connection; second succeeds.
        mock_pro.daily.side_effect = [
            requests.exceptions.ConnectionError("Remote end closed connection"),
            frame,
        ]
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            data = tushare_impl.load_ohlcv_tushare("600519", "2026-01-15")
        self.assertFalse(data.empty)
        self.assertEqual(mock_pro.daily.call_count, 2)
        tushare_impl.time.sleep.assert_called_once()

    def test_transient_error_exhausted_propagates(self):
        mock_pro = mock.Mock()
        mock_pro.daily.side_effect = requests.exceptions.ConnectionError("down")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            with self.assertRaises(requests.exceptions.ConnectionError):
                tushare_impl.load_ohlcv_tushare("600519", "2026-01-15")
        # Initial attempt + 3 retries = 4 calls before giving up.
        self.assertEqual(mock_pro.daily.call_count, 4)

    def test_no_market_data_not_retried(self):
        # An empty result is a deterministic NoMarketDataError, not a blip —
        # it must surface immediately without burning retries.
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = pd.DataFrame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            with self.assertRaises(NoMarketDataError):
                tushare_impl.load_ohlcv_tushare("999999", "2026-01-15")
        self.assertEqual(mock_pro.daily.call_count, 1)
        tushare_impl.time.sleep.assert_not_called()

    def test_rate_limit_classified_not_retried(self):
        # A TushareException with quota keywords is classified as rate-limit
        # and propagates immediately (router skips to next vendor).
        mock_pro = mock.Mock()
        mock_pro.daily.side_effect = Exception("抱歉，您每天最多访问该接口 2 次")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            with self.assertRaises(TushareRateLimitError):
                tushare_impl.load_ohlcv_tushare("600519", "2026-01-15")
        self.assertEqual(mock_pro.daily.call_count, 1)
        tushare_impl.time.sleep.assert_not_called()


@pytest.mark.unit
class LoadOhlcvTushareTests(unittest.TestCase):
    """load_ohlcv_tushare: cache hit, cache miss, no-data, stale rejection."""

    def setUp(self):
        _reset_config()
        _reset_tushare_cache()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()

    def test_a_share_download_and_cache(self):
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = _make_tushare_ohlcv_frame(rows=10, end="2026-01-15")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            data = tushare_impl.load_ohlcv_tushare("600519", "2026-01-15")
        self.assertFalse(data.empty)
        self.assertIn("Close", data.columns)
        # All rows are on or before curr_date.
        self.assertTrue((data["Date"] <= pd.Timestamp("2026-01-15")).all())
        # Second call should hit the cache (no new download).
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            tushare_impl.load_ohlcv_tushare("600519", "2026-01-15")
        self.assertEqual(mock_pro.daily.call_count, 1)

    def test_a_share_with_suffix(self):
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = _make_tushare_ohlcv_frame(rows=5, end="2026-01-15")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            data = tushare_impl.load_ohlcv_tushare("600519.SH", "2026-01-15")
        # ts_code passed to pro.daily should use .SH suffix.
        call_args = mock_pro.daily.call_args
        self.assertEqual(call_args.kwargs["ts_code"], "600519.SH")
        self.assertFalse(data.empty)

    def test_ss_suffix_normalized_to_sh(self):
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = _make_tushare_ohlcv_frame(rows=5, end="2026-01-15")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            tushare_impl.load_ohlcv_tushare("600000.SS", "2026-01-15")
        call_args = mock_pro.daily.call_args
        self.assertEqual(call_args.kwargs["ts_code"], "600000.SH")

    def test_empty_result_raises_no_data(self):
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = pd.DataFrame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            with self.assertRaises(NoMarketDataError):
                tushare_impl.load_ohlcv_tushare("999999", "2026-01-15")

    def test_non_a_share_raises_no_data(self):
        # ^GSPC is an index — Tushare can't serve it.
        with self.assertRaises(NoMarketDataError):
            tushare_impl.load_ohlcv_tushare("^GSPC", "2026-01-15")

    def test_us_symbol_raises_no_data(self):
        # US equities aren't handled by this vendor.
        with self.assertRaises(NoMarketDataError):
            tushare_impl.load_ohlcv_tushare("AAPL", "2026-01-15")


@pytest.mark.unit
class GetStockDataTests(unittest.TestCase):
    """get_stock_data: output format and date-range slicing."""

    def setUp(self):
        _reset_config()
        _reset_tushare_cache()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()

    def test_returns_csv_with_header(self):
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = _make_tushare_ohlcv_frame(rows=10, end="2026-01-15")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            result = tushare_impl.get_stock_data("600519", "2026-01-13", "2026-01-15")
        self.assertIn("# Stock data for 600519", result)
        self.assertIn("# Total records:", result)
        self.assertIn("Close", result)
        # The Amount column is dropped to match yfinance's OHLCV schema.
        self.assertNotIn("Amount", result)

    def test_empty_range_raises_no_data(self):
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = _make_tushare_ohlcv_frame(rows=5, end="2026-01-15")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            with self.assertRaises(NoMarketDataError):
                # Range entirely before available data.
                tushare_impl.get_stock_data("600519", "2025-01-01", "2025-01-05")


@pytest.mark.unit
class GetIndicatorsTests(unittest.TestCase):
    """get_indicators: computes a stockstats indicator over Tushare OHLCV."""

    def setUp(self):
        _reset_config()
        _reset_tushare_cache()
        self.tmpdir = tempfile.mkdtemp()
        config_module._config["data_cache_dir"] = self.tmpdir

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()

    def test_rsi_indicator_returns_window(self):
        # Need enough rows for stockstats to compute RSI (14-period minimum).
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = _make_tushare_ohlcv_frame(rows=60, end="2026-01-15")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            result = tushare_impl.get_indicators("600519", "rsi", "2026-01-15", 5)
        self.assertIn("## rsi values", result)

    def test_unsupported_indicator_raises_value_error(self):
        mock_pro = mock.Mock()
        mock_pro.daily.return_value = _make_tushare_ohlcv_frame(rows=5, end="2026-01-15")
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            with self.assertRaises(ValueError):
                tushare_impl.get_indicators("600519", "bogus_ind", "2026-01-15", 5)


@pytest.mark.unit
class GetFundamentalsTests(unittest.TestCase):
    """get_fundamentals: combines stock_basic + daily_basic."""

    def setUp(self):
        _reset_config()
        _reset_tushare_cache()

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()

    def test_returns_fundamentals_with_header(self):
        mock_pro = mock.Mock()
        mock_pro.stock_basic.return_value = _make_stock_basic_frame()
        mock_pro.daily_basic.return_value = _make_daily_basic_frame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            result = tushare_impl.get_fundamentals("600519", "2026-01-15")
        self.assertIn("# Company Fundamentals for 600519.SH", result)
        self.assertIn("Name:", result)
        self.assertIn("PE (TTM):", result)
        self.assertIn("Total Market Cap", result)

    def test_non_a_share_raises_no_data(self):
        with self.assertRaises(NoMarketDataError):
            tushare_impl.get_fundamentals("AAPL")

    def test_empty_stock_basic_raises_no_data(self):
        mock_pro = mock.Mock()
        mock_pro.stock_basic.return_value = pd.DataFrame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            with self.assertRaises(NoMarketDataError):
                tushare_impl.get_fundamentals("999999")


@pytest.mark.unit
class GetBalanceSheetTests(unittest.TestCase):
    """get_balance_sheet: transpose, freq filter, date filter."""

    def setUp(self):
        _reset_config()
        _reset_tushare_cache()

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()

    def test_returns_transposed_balance_sheet(self):
        mock_pro = mock.Mock()
        mock_pro.balancesheet.return_value = _make_balancesheet_frame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            result = tushare_impl.get_balance_sheet("600519", "quarterly", "2024-04-01")
        self.assertIn("# Balance Sheet data for 600519.SH", result)
        # Financial fields appear as rows; periods as columns.
        self.assertIn("total_assets", result)
        # Metadata rows are dropped.
        self.assertNotIn("ts_code", result.split("\n\n", 1)[1])

    def test_annual_filter_keeps_only_december_ends(self):
        mock_pro = mock.Mock()
        mock_pro.balancesheet.return_value = _make_balancesheet_frame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            # Annual freq should drop the 20230630 row.
            result = tushare_impl.get_balance_sheet("600519", "annual", "2024-04-01")
        # Only the 2023-12-31 period column should be present.
        self.assertIn("2023-12-31", result)
        self.assertNotIn("2023-06-30", result)

    def test_curr_date_filters_future_periods(self):
        mock_pro = mock.Mock()
        mock_pro.balancesheet.return_value = _make_balancesheet_frame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            # curr_date before the 2023-12-31 period end should drop it.
            result = tushare_impl.get_balance_sheet("600519", "quarterly", "2023-09-01")
        self.assertNotIn("2023-12-31", result)

    def test_non_a_share_raises_no_data(self):
        with self.assertRaises(NoMarketDataError):
            tushare_impl.get_balance_sheet("AAPL")

    def test_empty_result_raises_no_data(self):
        mock_pro = mock.Mock()
        mock_pro.balancesheet.return_value = pd.DataFrame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            with self.assertRaises(NoMarketDataError):
                tushare_impl.get_balance_sheet("600519")


@pytest.mark.unit
class GetCashflowTests(unittest.TestCase):
    def setUp(self):
        _reset_config()
        _reset_tushare_cache()

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()

    def test_returns_transposed_cashflow(self):
        mock_pro = mock.Mock()
        mock_pro.cashflow.return_value = _make_balancesheet_frame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            result = tushare_impl.get_cashflow("600519", "quarterly", "2024-04-01")
        self.assertIn("# Cash Flow data for 600519.SH", result)


@pytest.mark.unit
class GetIncomeStatementTests(unittest.TestCase):
    def setUp(self):
        _reset_config()
        _reset_tushare_cache()

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()

    def test_returns_transposed_income(self):
        mock_pro = mock.Mock()
        mock_pro.income.return_value = _make_balancesheet_frame()
        with mock.patch.object(tushare_impl, "_get_tushare_pro", return_value=mock_pro):
            result = tushare_impl.get_income_statement("600519", "quarterly", "2024-04-01")
        self.assertIn("# Income Statement data for 600519.SH", result)


@pytest.mark.unit
class RouterSkipsTushareWhenNotConfiguredTests(unittest.TestCase):
    """When tushare isn't installed, the router must skip it and fall through."""

    def setUp(self):
        _reset_config()
        _reset_tushare_cache()

    def tearDown(self):
        _reset_config()
        _reset_tushare_cache()

    def test_tushare_not_configured_falls_through_to_yfinance(self):
        from tradingagents.dataflows import interface

        config_module._config["data_vendors"]["core_stock_apis"] = "tushare,yfinance"
        with mock.patch.dict("sys.modules", {"tushare": None}), mock.patch.dict(
            interface.VENDOR_METHODS,
            {
                "get_stock_data": {
                    "tushare": interface.VENDOR_METHODS["get_stock_data"]["tushare"],
                    "yfinance": lambda *a, **k: "YF_DATA",
                }
            },
            clear=False,
        ):
            result = interface.route_to_vendor(
                "get_stock_data", "600519", "2026-01-01", "2026-01-10"
            )
        self.assertEqual(result, "YF_DATA")

    def test_tushare_non_a_share_falls_through_to_yfinance(self):
        # A non-A-share symbol raises NoMarketDataError from tushare, so the
        # router must fall through to the next configured vendor.
        from tradingagents.dataflows import interface

        config_module._config["data_vendors"]["core_stock_apis"] = "tushare,yfinance"
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {
                "get_stock_data": {
                    "tushare": interface.VENDOR_METHODS["get_stock_data"]["tushare"],
                    "yfinance": lambda *a, **k: "YF_DATA",
                }
            },
            clear=False,
        ):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "YF_DATA")


if __name__ == "__main__":
    unittest.main()
