"""china_macro vendor unit tests.

The china_macro vendor serves China-specific macro indicators (LPR, SHIBOR, CPI,
PMI, M2, …) via direct HTTP to Eastmoney's datacenter, sharing the a_stock
``_em_get`` throttle. Tests mock the HTTP layer and verify alias dispatch,
look-ahead date filtering, and the NoMarketDataError contract (unknown alias or
no rows → raise, so the router can fall back to fred).
"""

import unittest
from unittest import mock

import pytest

from tradingagents.dataflows import china_macro
from tradingagents.dataflows.errors import NoMarketDataError


@pytest.mark.unit
class TestChinaMacroAliases(unittest.TestCase):
    def test_unknown_alias_raises_no_market_data(self):
        with self.assertRaises(NoMarketDataError):
            china_macro.get_macro_data("totally_unknown_xyz", "2026-01-01", 365)

    def test_alias_does_not_collide_with_fred(self):
        # FRED aliases (cpi, fed_funds_rate) must NOT be in the china_macro
        # catalogue — a "china_macro,fred" chain relies on each vendor serving
        # disjoint aliases so one doesn't mask the other.
        fred_aliases = {
            "cpi",
            "core_pce",
            "fed_funds_rate",
            "10y_treasury",
            "unemployment",
            "real_gdp",
            "vix",
        }
        self.assertTrue(fred_aliases.isdisjoint(china_macro._INDICATORS.keys()))


@pytest.mark.unit
class TestChinaMacroFetch(unittest.TestCase):
    def _mock_response(self, rows):
        resp = mock.MagicMock()
        resp.json.return_value = {"result": {"data": rows}}
        return resp

    def test_lpr_returns_formatted_report(self):
        rows = [
            {"REPORT_DATE": "2025-12-20", "LPR1Y": 3.10},
            {"REPORT_DATE": "2026-01-20", "LPR1Y": 3.05},
        ]
        with mock.patch.object(china_macro, "_em_get", return_value=self._mock_response(rows)):
            result = china_macro.get_macro_data("lpr", "2026-02-01", 365)
        self.assertIn("Loan Prime Rate", result)
        self.assertIn("3.05", result)  # latest value
        self.assertIn("2026-01-20", result)  # latest date

    def test_filters_rows_after_curr_date(self):
        # A row dated after curr_date must not appear (look-ahead protection).
        rows = [
            {"REPORT_DATE": "2026-01-20", "LPR1Y": 3.05},
            {"REPORT_DATE": "2026-03-20", "LPR1Y": 2.90},  # after curr_date
        ]
        with mock.patch.object(china_macro, "_em_get", return_value=self._mock_response(rows)):
            result = china_macro.get_macro_data("lpr", "2026-02-01", 365)
        self.assertIn("3.05", result)
        self.assertNotIn("2.90", result)
        self.assertNotIn("2026-03-20", result)

    def test_no_rows_raises_no_market_data(self):
        with (
            mock.patch.object(china_macro, "_em_get", return_value=self._mock_response([])),
            self.assertRaises(NoMarketDataError),
        ):
            china_macro.get_macro_data("lpr", "2026-01-01", 365)

    def test_http_failure_raises_no_market_data(self):
        with (
            mock.patch.object(china_macro, "_em_get", side_effect=Exception("net")),
            self.assertRaises(NoMarketDataError),
        ):
            china_macro.get_macro_data("cn_cpi", "2026-01-01", 365)

    def test_default_lookback_365_days(self):
        # look_back_days=None → 365-day window. Verify by checking the fetch
        # is called (rows returned), not crashing on None.
        rows = [{"REPORT_DATE": "2026-01-01", "LPR1Y": 3.10}]
        with mock.patch.object(china_macro, "_em_get", return_value=self._mock_response(rows)):
            result = china_macro.get_macro_data("lpr", "2026-02-01", None)
        self.assertIn("365 days", result)


if __name__ == "__main__":
    unittest.main()
