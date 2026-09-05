"""Market classification for vendor routing.

``classify_market`` drives ``market_vendors`` selection — it must be purely
syntactic (no network) and classify A-share, HK, and US tickers correctly
based on the symbol string alone.
"""

import unittest

import pytest

from tradingagents.dataflows.symbol_utils import classify_market


@pytest.mark.unit
class TestClassifyMarket(unittest.TestCase):
    # CN — 6 accepted forms
    def test_cn_plain_6_digits(self):
        self.assertEqual(classify_market("600519"), "cn")

    def test_cn_ss_suffix(self):
        self.assertEqual(classify_market("600519.SS"), "cn")

    def test_cn_sh_suffix(self):
        self.assertEqual(classify_market("600519.SH"), "cn")

    def test_cn_sz_suffix(self):
        self.assertEqual(classify_market("000001.SZ"), "cn")

    def test_cn_sh_prefix(self):
        self.assertEqual(classify_market("sh600519"), "cn")

    def test_cn_sz_prefix(self):
        self.assertEqual(classify_market("sz000001"), "cn")

    def test_cn_lowercase_prefix(self):
        self.assertEqual(classify_market("SH600519"), "cn")

    # HK
    def test_hk_4_digit(self):
        self.assertEqual(classify_market("0700.HK"), "hk")

    def test_hk_5_digit(self):
        self.assertEqual(classify_market("00700.HK"), "hk")

    def test_hk_lowercase_suffix(self):
        self.assertEqual(classify_market("0700.hk"), "hk")

    # US (fallthrough)
    def test_us_plain(self):
        self.assertEqual(classify_market("AAPL"), "us")

    def test_us_dot_suffix(self):
        self.assertEqual(classify_market("BRK.B"), "us")

    def test_us_bare_4_digit(self):
        # Decision: bare 4-digit without .HK → us (conservative)
        self.assertEqual(classify_market("0700"), "us")

    def test_us_crypto(self):
        self.assertEqual(classify_market("BTC-USD"), "us")

    def test_us_forex(self):
        self.assertEqual(classify_market("EURUSD=X"), "us")

    def test_us_metal(self):
        self.assertEqual(classify_market("GC=F"), "us")

    def test_us_yahoo_index(self):
        self.assertEqual(classify_market("^GSPC"), "us")

    def test_us_exchange_suffix(self):
        self.assertEqual(classify_market("SHOP.TO"), "us")

    # Edge cases
    def test_empty_string(self):
        self.assertEqual(classify_market(""), "us")

    def test_none(self):
        self.assertEqual(classify_market(None), "us")

    def test_non_string(self):
        self.assertEqual(classify_market(12345), "us")

    def test_whitespace_stripped(self):
        self.assertEqual(classify_market("  600519.SS  "), "cn")


if __name__ == "__main__":
    unittest.main()
