"""Market-aware vendor routing.

The router infers the market from the ticker symbol (first positional arg)
and selects the vendor chain from ``market_vendors[market]``. Non-symbol
methods default to the "us" market. ``tool_vendors`` overrides everything.
"""

import copy
import unittest
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import analysis_market_var, set_config
from tradingagents.dataflows.errors import NoMarketDataError


def _reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    # Reset the per-run ContextVar so a previous test's market doesn't leak.
    _reset_analysis_market()


def _reset_analysis_market():
    # ContextVar.reset requires a Token from a prior set; we don't track that
    # here, so use set(None) (the default sentinel) to clear any run-scoped value.
    analysis_market_var.set(None)


def _no_data(symbol, *a, **k):
    raise NoMarketDataError(symbol, symbol, "no rows")


def _returns(value):
    def impl(*a, **k):
        return value

    return impl


@pytest.mark.unit
class TestMarketAwareRouting(unittest.TestCase):
    def setUp(self):
        _reset_config()

    def tearDown(self):
        _reset_config()

    def test_cn_symbol_uses_cn_market_vendors(self):
        # market=cn (set via ContextVar) → market_vendors["cn"]["core_stock_apis"]
        # = "a_stock,yfinance". With a_stock stubbed to return data, the router
        # returns that data (it no longer degrades to NO_DATA_AVAILABLE now that
        # a_stock is a real vendor).
        analysis_market_var.set("cn")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"a_stock": _returns("ASTOCK_DATA"), "yfinance": _no_data}},
            clear=False,
        ):
            result = interface.route_to_vendor(
                "get_stock_data", "600519.SS", "2026-01-01", "2026-01-10"
            )
        self.assertEqual(result, "ASTOCK_DATA")

    def test_hk_symbol_uses_hk_market_vendors(self):
        # market=hk → market_vendors["hk"]["core_stock_apis"] = "yfinance"
        analysis_market_var.set("hk")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"yfinance": _returns("HK_DATA")}},
            clear=False,
        ):
            result = interface.route_to_vendor(
                "get_stock_data", "0700.HK", "2026-01-01", "2026-01-10"
            )
        self.assertEqual(result, "HK_DATA")

    def test_us_symbol_uses_us_market_vendors(self):
        # market=us → market_vendors["us"]["core_stock_apis"]
        analysis_market_var.set("us")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"yfinance": _returns("US_DATA"), "alpha_vantage": _no_data}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "US_DATA")

    def test_tool_vendors_overrides_market(self):
        # tool_vendors[method] takes precedence over market_vendors.
        set_config({"tool_vendors": {"get_stock_data": "yfinance"}})
        analysis_market_var.set("cn")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_stock_data": {"yfinance": _returns("TOOL_OVERRIDE"), "tushare": _no_data}},
            clear=False,
        ):
            # Even with market=cn, tool_vendors forces yfinance.
            result = interface.route_to_vendor(
                "get_stock_data", "600519.SS", "2026-01-01", "2026-01-10"
            )
        self.assertEqual(result, "TOOL_OVERRIDE")

    def test_non_symbol_method_uses_us_default(self):
        # No run-scoped market (analysis_market_var is None per setUp) → "us".
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_macro_indicators": {"fred": _returns("MACRO_OK")}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_macro_indicators", "cpi", "2026-01-01", 365)
        self.assertEqual(result, "MACRO_OK")

    def test_cn_fundamentals_uses_a_stock(self):
        # market=cn → fundamental_data → "a_stock" (the A-share vendor)
        analysis_market_var.set("cn")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_fundamentals": {"a_stock": _returns("ASTOCK_FUND")}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_fundamentals", "600519.SS", "2026-01-01")
        self.assertEqual(result, "ASTOCK_FUND")

    def test_cn_news_uses_a_stock(self):
        # market=cn → news_data → "a_stock" (the A-share vendor)
        analysis_market_var.set("cn")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_news": {"a_stock": _returns("ASTOCK_NEWS")}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_news", "600519.SS", "2026-01-01", "2026-01-10")
        self.assertEqual(result, "ASTOCK_NEWS")

    def test_cn_macro_routes_to_china_macro(self):
        # Non-symbol method: analysis_market_var=cn (set via ContextVar) →
        # macro_data chain "china_macro,fred". With china_macro stubbed to
        # return data and fred raising NoMarketDataError, the router returns
        # china_macro's data.
        analysis_market_var.set("cn")
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_macro_indicators": {"china_macro": _returns("CN_MACRO"), "fred": _no_data}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_macro_indicators", "lpr", "2026-01-01", 365)
        self.assertEqual(result, "CN_MACRO")

    def test_us_macro_uses_default_market(self):
        # Non-symbol method with no run-scoped market → defaults to "us" → fred.
        # (analysis_market_var is None here per setUp reset.)
        with mock.patch.dict(
            interface.VENDOR_METHODS,
            {"get_macro_indicators": {"fred": _returns("FRED_MACRO"), "china_macro": _no_data}},
            clear=False,
        ):
            result = interface.route_to_vendor("get_macro_indicators", "cpi", "2026-01-01", 365)
        self.assertEqual(result, "FRED_MACRO")

    def test_get_vendor_resolves_by_market(self):
        self.assertEqual(
            interface.get_vendor("core_stock_apis", market="us"),
            "yfinance,alpha_vantage",
        )
        self.assertEqual(
            interface.get_vendor("core_stock_apis", market="cn"),
            "a_stock,yfinance",
        )
        self.assertEqual(
            interface.get_vendor("core_stock_apis", market="hk"),
            "yfinance",
        )

    def test_get_vendor_cn_macro_chain(self):
        # CN macro chain falls back china_macro → fred.
        self.assertEqual(
            interface.get_vendor("macro_data", market="cn"),
            "china_macro,fred",
        )

    def test_get_vendor_tool_overrides_market(self):
        set_config({"tool_vendors": {"get_stock_data": "alpha_vantage"}})
        self.assertEqual(
            interface.get_vendor("core_stock_apis", method="get_stock_data", market="cn"),
            "alpha_vantage",
        )

    def test_get_vendor_unknown_market_returns_default(self):
        self.assertEqual(
            interface.get_vendor("core_stock_apis", market="jp"),
            "default",
        )


if __name__ == "__main__":
    unittest.main()
