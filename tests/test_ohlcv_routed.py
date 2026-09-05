"""Config-driven OHLCV loading (load_ohlcv_routed).

``load_ohlcv_routed`` selects its vendor chain from ``market_vendors`` the
same way ``route_to_vendor`` does for ``get_stock_data`` — so the
verified-market-snapshot path and the market analyst use the same vendors,
including fallback. CN-classified symbols default to ``a_stock,yfinance``,
US to ``yfinance,alpha_vantage``, HK to ``yfinance``.
"""

import copy
import unittest
from unittest import mock

import pandas as pd
import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import stockstats_utils
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.symbol_utils import NoMarketDataError


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


def _ohlcv_df(date="2026-01-01", close=100.0):
    return pd.DataFrame(
        {
            "Date": pd.to_datetime([date]),
            "Open": [close],
            "High": [close],
            "Low": [close],
            "Close": [close],
            "Volume": [1000],
        }
    )


@pytest.mark.unit
class TestLoadOhlcvRouted(unittest.TestCase):
    def setUp(self):
        _reset_config()

    def tearDown(self):
        _reset_config()

    # ---- default-config routing (unchanged behavior) ----

    def test_cn_symbol_routes_to_astock(self):
        cn_df = _ohlcv_df("2026-01-01", close=10.5)
        with (
            mock.patch.object(stockstats_utils, "load_ohlcv") as yf_loader,
            mock.patch(
                "tradingagents.dataflows.a_stock._load_ohlcv_astock", return_value=cn_df
            ) as astock_loader,
        ):
            result = stockstats_utils.load_ohlcv_routed("600519", "2026-01-02")
        astock_loader.assert_called_once_with("600519", "2026-01-02")
        yf_loader.assert_not_called()
        self.assertEqual(len(result), 1)

    def test_cn_symbol_with_suffix_routes_to_astock(self):
        with (
            mock.patch.object(stockstats_utils, "load_ohlcv"),
            mock.patch(
                "tradingagents.dataflows.a_stock._load_ohlcv_astock",
                return_value=_ohlcv_df(),
            ) as astock_loader,
        ):
            stockstats_utils.load_ohlcv_routed("600519.SS", "2026-01-02")
        astock_loader.assert_called_once_with("600519.SS", "2026-01-02")

    def test_us_symbol_routes_to_yfinance(self):
        with (
            mock.patch.object(
                stockstats_utils, "load_ohlcv", return_value=_ohlcv_df()
            ) as yf_loader,
            mock.patch("tradingagents.dataflows.a_stock._load_ohlcv_astock") as astock_loader,
            mock.patch("tradingagents.dataflows.alpha_vantage_stock._load_ohlcv_alpha_vantage"),
        ):
            result = stockstats_utils.load_ohlcv_routed("AAPL", "2026-01-02")
        yf_loader.assert_called_once_with("AAPL", "2026-01-02")
        astock_loader.assert_not_called()
        self.assertEqual(len(result), 1)

    def test_hk_symbol_routes_to_yfinance(self):
        with (
            mock.patch.object(
                stockstats_utils, "load_ohlcv", return_value=_ohlcv_df()
            ) as yf_loader,
            mock.patch("tradingagents.dataflows.a_stock._load_ohlcv_astock") as astock_loader,
        ):
            stockstats_utils.load_ohlcv_routed("0700.HK", "2026-01-02")
        yf_loader.assert_called_once_with("0700.HK", "2026-01-02")
        astock_loader.assert_not_called()

    # ---- fallback within configured chain ----

    def test_cn_a_stock_fallback_to_yfinance(self):
        # CN default chain is "a_stock,yfinance": a_stock no-data -> yfinance.
        set_config({"market_vendors": {"cn": {"core_stock_apis": "a_stock,yfinance"}}})
        yf_df = _ohlcv_df("2026-01-01", close=10.5)
        with (
            mock.patch.object(stockstats_utils, "load_ohlcv", return_value=yf_df) as yf_loader,
            mock.patch(
                "tradingagents.dataflows.a_stock._load_ohlcv_astock",
                side_effect=NoMarketDataError("600519", "600519", "mootdx empty"),
            ) as astock_loader,
        ):
            result = stockstats_utils.load_ohlcv_routed("600519", "2026-01-02")
        astock_loader.assert_called_once()
        yf_loader.assert_called_once_with("600519", "2026-01-02")
        self.assertEqual(len(result), 1)

    def test_us_yfinance_fallback_to_alpha_vantage(self):
        # US default chain is "yfinance,alpha_vantage": yfinance no-data -> AV.
        set_config({"market_vendors": {"us": {"core_stock_apis": "yfinance,alpha_vantage"}}})
        av_df = _ohlcv_df("2026-01-01", close=150.0)
        with (
            mock.patch.object(
                stockstats_utils,
                "load_ohlcv",
                side_effect=NoMarketDataError("AAPL", "AAPL", "yfinance empty"),
            ),
            mock.patch(
                "tradingagents.dataflows.alpha_vantage_stock._load_ohlcv_alpha_vantage",
                return_value=av_df,
            ) as av_loader,
        ):
            result = stockstats_utils.load_ohlcv_routed("AAPL", "2026-01-02")
        av_loader.assert_called_once_with("AAPL", "2026-01-02")
        self.assertEqual(len(result), 1)

    def test_yfinance_generic_exception_falls_back_to_alpha_vantage(self):
        # A non-VendorError exception (e.g. ConnectionError, JSONDecodeError)
        # from yfinance must NOT crash the snapshot path — it should fall back
        # to the next vendor, mirroring route_to_vendor's generic-Exception
        # handling. Regression for the missing except-Exception clause.
        set_config({"market_vendors": {"us": {"core_stock_apis": "yfinance,alpha_vantage"}}})
        av_df = _ohlcv_df("2026-01-01", close=150.0)
        with (
            mock.patch.object(
                stockstats_utils,
                "load_ohlcv",
                side_effect=ConnectionError("yahoo down"),
            ),
            mock.patch(
                "tradingagents.dataflows.alpha_vantage_stock._load_ohlcv_alpha_vantage",
                return_value=av_df,
            ) as av_loader,
        ):
            result = stockstats_utils.load_ohlcv_routed("AAPL", "2026-01-02")
        av_loader.assert_called_once_with("AAPL", "2026-01-02")
        self.assertEqual(len(result), 1)

    def test_alpha_vantage_csv_parsed_to_dataframe(self):
        # Verify _load_ohlcv_alpha_vantage parses AV's CSV into a proper frame.
        from tradingagents.dataflows.alpha_vantage_stock import _load_ohlcv_alpha_vantage

        csv_text = (
            "timestamp,open,high,low,close,adjusted_close,volume,dividend_amount,split_coefficient\n"
            "2026-01-01,149.0,151.0,148.0,150.0,150.0,1000000,0.0,1.0\n"
            "2026-01-02,150.0,152.0,149.5,151.5,151.5,1100000,0.0,1.0\n"
        )
        with mock.patch(
            "tradingagents.dataflows.alpha_vantage_stock.get_stock", return_value=csv_text
        ):
            df = _load_ohlcv_alpha_vantage("AAPL", "2026-01-02")
        self.assertEqual(list(df.columns), ["Date", "Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[-1]["Close"], 151.5)  # adjusted_close -> Close

    def test_alpha_vantage_empty_csv_raises_no_data(self):
        from tradingagents.dataflows.alpha_vantage_stock import _load_ohlcv_alpha_vantage

        with (
            mock.patch("tradingagents.dataflows.alpha_vantage_stock.get_stock", return_value=""),
            self.assertRaises(NoMarketDataError),
        ):
            _load_ohlcv_alpha_vantage("AAPL", "2026-01-02")

    # ---- config override ----

    def test_cn_config_override_to_yfinance_only(self):
        # User pins CN to yfinance: a_stock must NOT be called (regression for
        # the old hardcoded cn->a_stock behavior that bypassed config).
        set_config({"market_vendors": {"cn": {"core_stock_apis": "yfinance"}}})
        with (
            mock.patch.object(
                stockstats_utils, "load_ohlcv", return_value=_ohlcv_df()
            ) as yf_loader,
            mock.patch("tradingagents.dataflows.a_stock._load_ohlcv_astock") as astock_loader,
        ):
            stockstats_utils.load_ohlcv_routed("600519", "2026-01-02")
        yf_loader.assert_called_once_with("600519", "2026-01-02")
        astock_loader.assert_not_called()

    def test_tool_vendors_override_takes_precedence(self):
        # tool_vendors["get_stock_data"] overrides market_vendors for all markets.
        set_config({"tool_vendors": {"get_stock_data": "yfinance"}})
        with (
            mock.patch.object(
                stockstats_utils, "load_ohlcv", return_value=_ohlcv_df()
            ) as yf_loader,
            mock.patch("tradingagents.dataflows.a_stock._load_ohlcv_astock") as astock_loader,
        ):
            stockstats_utils.load_ohlcv_routed("600519", "2026-01-02")
        yf_loader.assert_called_once()
        astock_loader.assert_not_called()

    # ---- all vendors fail ----

    def test_all_vendors_no_data_raises(self):
        set_config({"market_vendors": {"us": {"core_stock_apis": "yfinance,alpha_vantage"}}})
        with (
            mock.patch.object(
                stockstats_utils,
                "load_ohlcv",
                side_effect=NoMarketDataError("AAPL", "AAPL", "empty"),
            ),
            mock.patch(
                "tradingagents.dataflows.alpha_vantage_stock._load_ohlcv_alpha_vantage",
                side_effect=NoMarketDataError("AAPL", "AAPL", "empty"),
            ),
            self.assertRaises(NoMarketDataError),
        ):
            stockstats_utils.load_ohlcv_routed("AAPL", "2026-01-02")


if __name__ == "__main__":
    unittest.main()
