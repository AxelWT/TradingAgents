"""a_stock vendor unit tests.

The a_stock vendor (mootdx TCP + Tencent/Eastmoney/Sina/THS/CLS direct HTTP)
is the A-share data source. These tests mock the network/mootdx layer so they
run offline and fast, focusing on the error-contract adaptation (raising
``NoMarketDataError`` so the router can fall back / emit a sentinel) and ticker
normalization.
"""

import unittest
from unittest import mock

import pandas as pd
import pytest

from tradingagents.dataflows import a_stock
from tradingagents.dataflows.errors import NoMarketDataError


@pytest.mark.unit
class TestNormalizeTicker(unittest.TestCase):
    def test_plain_6_digits(self):
        self.assertEqual(a_stock._normalize_ticker("600519"), "600519")

    def test_sh_suffix(self):
        self.assertEqual(a_stock._normalize_ticker("600519.SH"), "600519")
        self.assertEqual(a_stock._normalize_ticker("600519.SS"), "600519")

    def test_sz_suffix(self):
        self.assertEqual(a_stock._normalize_ticker("000001.SZ"), "000001")

    def test_sh_prefix(self):
        self.assertEqual(a_stock._normalize_ticker("SH600519"), "600519")
        self.assertEqual(a_stock._normalize_ticker("sh600519"), "600519")

    def test_rejects_hk_4_digit(self):
        with self.assertRaises(NoMarketDataError):
            a_stock._normalize_ticker("0700")

    def test_rejects_hk_with_suffix(self):
        with self.assertRaises(NoMarketDataError):
            a_stock._normalize_ticker("0700.HK")

    def test_rejects_us_letters(self):
        with self.assertRaises(NoMarketDataError):
            a_stock._normalize_ticker("AAPL")


@pytest.mark.unit
class TestGetStockDataErrorContract(unittest.TestCase):
    """get_stock_data must raise NoMarketDataError (not return an error string)
    when no data can be obtained, so the router can fall back / emit a sentinel.
    """

    def test_raises_when_mootdx_and_sina_both_fail(self):
        with (
            mock.patch.object(a_stock, "_mootdx_call", side_effect=RuntimeError("no tdx")),
            mock.patch.object(a_stock, "_sina_kline_fallback", side_effect=Exception("no sina")),
            mock.patch.object(a_stock, "_supplement_stale_ohlcv_with_sina") as suppl,
        ):
            suppl.return_value = (pd.DataFrame(), False)
            with self.assertRaises(NoMarketDataError):
                a_stock.get_stock_data("600519", "2026-01-01", "2026-01-10")

    def test_raises_when_filtered_df_empty(self):
        # mootdx returns data but none falls in the requested window → empty
        # after filter → NoMarketDataError (genuine "no data in range").
        df = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2025-01-01"]),
                "Open": [10.0],
                "High": [11.0],
                "Low": [9.0],
                "Close": [10.5],
                "Volume": [1000],
            }
        )
        with (
            mock.patch.object(a_stock, "_mootdx_call", return_value=df),
            mock.patch.object(a_stock, "_supplement_stale_ohlcv_with_sina") as suppl,
        ):
            suppl.return_value = (df, False)
            with self.assertRaises(NoMarketDataError):
                a_stock.get_stock_data("600519", "2026-01-01", "2026-01-10")


@pytest.mark.unit
class TestGetFundamentalsErrorContract(unittest.TestCase):
    def test_raises_when_all_sources_empty(self):
        # Every source fails → lines stays empty → NoMarketDataError. Use today
        # as curr_date so no look-ahead snapshot-notice is prepended (which would
        # make `lines` non-empty and mask the all-sources-failed condition).
        from datetime import date

        today = date.today().strftime("%Y-%m-%d")
        with (
            mock.patch.object(a_stock, "_tencent_quote", side_effect=Exception("net")),
            mock.patch.object(a_stock, "_mootdx_call", side_effect=Exception("no tdx")),
            mock.patch.object(a_stock, "_em_get", side_effect=Exception("net")),
            mock.patch.object(a_stock, "_ths_eps_forecast", side_effect=Exception("net")),
            self.assertRaises(NoMarketDataError),
        ):
            a_stock.get_fundamentals("600519", today)


@pytest.mark.unit
class TestGetBalanceSheetErrorContract(unittest.TestCase):
    def test_raises_when_em_empty(self):
        with (
            mock.patch.object(a_stock, "_get_financial_report_em", return_value=pd.DataFrame()),
            self.assertRaises(NoMarketDataError),
        ):
            a_stock.get_balance_sheet("600519", "quarterly", "2026-01-01")


@pytest.mark.unit
class TestGetNewsErrorContract(unittest.TestCase):
    def test_raises_when_both_sources_fail(self):
        with (
            mock.patch.object(a_stock, "_fetch_news_eastmoney", side_effect=Exception("net")),
            mock.patch.object(a_stock, "_fetch_news_sina", side_effect=Exception("net")),
            self.assertRaises(NoMarketDataError),
        ):
            a_stock.get_news("600519", "2026-01-01", "2026-01-10")

    def test_returns_string_when_sources_respond_but_empty(self):
        # Sources respond with no articles (legitimate sparseness, not a source
        # failure) → return a "no news" string, not raise.
        with (
            mock.patch.object(a_stock, "_fetch_news_eastmoney", return_value=[]),
            mock.patch.object(a_stock, "_fetch_news_sina", return_value=[]),
        ):
            result = a_stock.get_news("600519", "2026-01-01", "2026-01-10")
        self.assertIn("No news", result)


@pytest.mark.unit
class TestGetGlobalNewsNoneDefaults(unittest.TestCase):
    """The fork's tool passes look_back_days=None / limit=None. The vendor must
    fall back to config defaults rather than crashing on relativedelta(days=None).
    """

    def test_none_defaults_fall_back_to_config(self):
        from tradingagents.dataflows.config import set_config

        set_config({"global_news_lookback_days": 7, "global_news_article_limit": 5})
        cls_articles = [{"title": "t", "content": "c", "time": "2026-01-01", "source": "CLS Wire"}]

        with (
            mock.patch.object(a_stock._requests, "get") as cls_get,
            mock.patch.object(a_stock, "_em_get") as em_get,
        ):
            cls_get.return_value.json.return_value = {"data": {"roll_data": cls_articles}}
            em_get.return_value.json.return_value = {"data": {"fastNewsList": []}}
            # Must not raise on None look_back_days/limit.
            result = a_stock.get_global_news("2026-01-08", None, None)
        self.assertIn("CLS Wire", result)


if __name__ == "__main__":
    unittest.main()
