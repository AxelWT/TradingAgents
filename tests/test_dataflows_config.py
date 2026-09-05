"""Config isolation: get/set must not leak nested-dict references."""

import copy
import unittest

import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows.config import get_config, set_config


@pytest.mark.unit
class DataflowsConfigIsolationTests(unittest.TestCase):
    def setUp(self):
        set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))

    def test_get_config_returns_deep_copy(self):
        cfg = get_config()
        cfg["market_vendors"]["us"]["core_stock_apis"] = "alpha_vantage"
        cfg["tool_vendors"]["get_stock_data"] = "alpha_vantage"

        fresh = get_config()
        self.assertEqual(fresh["market_vendors"]["us"]["core_stock_apis"], "yfinance,alpha_vantage")
        self.assertNotIn("get_stock_data", fresh["tool_vendors"])

    def test_set_config_does_not_alias_caller_nested_dicts(self):
        custom = copy.deepcopy(default_config.DEFAULT_CONFIG)
        custom["market_vendors"]["us"]["core_stock_apis"] = "alpha_vantage"
        custom["tool_vendors"]["get_stock_data"] = "alpha_vantage"

        set_config(custom)

        custom["market_vendors"]["us"]["core_stock_apis"] = "yfinance"
        custom["tool_vendors"]["get_stock_data"] = "yfinance"

        fresh = get_config()
        self.assertEqual(fresh["market_vendors"]["us"]["core_stock_apis"], "alpha_vantage")
        self.assertEqual(fresh["tool_vendors"]["get_stock_data"], "alpha_vantage")

    def test_partial_nested_update_preserves_existing_defaults(self):
        set_config(
            {
                "market_vendors": {
                    "us": {
                        "core_stock_apis": "alpha_vantage",
                    }
                }
            }
        )

        fresh = get_config()
        self.assertEqual(fresh["market_vendors"]["us"]["core_stock_apis"], "alpha_vantage")
        self.assertEqual(
            fresh["market_vendors"]["us"]["technical_indicators"], "yfinance,alpha_vantage"
        )
        self.assertEqual(
            fresh["market_vendors"]["us"]["fundamental_data"], "yfinance,alpha_vantage"
        )
        self.assertEqual(fresh["market_vendors"]["us"]["news_data"], "yfinance,alpha_vantage")

    def test_partial_market_update_preserves_other_markets(self):
        set_config({"market_vendors": {"cn": {"core_stock_apis": "akshare"}}})

        fresh = get_config()
        self.assertEqual(fresh["market_vendors"]["cn"]["core_stock_apis"], "akshare")
        self.assertEqual(fresh["market_vendors"]["us"]["core_stock_apis"], "yfinance,alpha_vantage")
        self.assertEqual(fresh["market_vendors"]["hk"]["core_stock_apis"], "yfinance")

    def test_nested_dict_updates_deep_merge(self):
        set_config({"tool_vendors": {"get_stock_data": "alpha_vantage"}})
        set_config({"tool_vendors": {"get_news": "alpha_vantage"}})

        fresh = get_config()
        self.assertEqual(fresh["tool_vendors"]["get_stock_data"], "alpha_vantage")
        self.assertEqual(fresh["tool_vendors"]["get_news"], "alpha_vantage")
