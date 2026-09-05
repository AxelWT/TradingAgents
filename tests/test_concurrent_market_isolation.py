"""Concurrent-run market isolation regression test (#1290).

Two threads simulating concurrent graph runs with different tickers (one CN,
one US) must each see their own market for non-symbol methods. Before #1290,
``analysis_market`` lived in the process-global ``_config`` dict and the second
run's write clobbered the first, causing a CN run's ``get_macro_indicators``
call to route to the US vendor (fred) instead of china_macro.
"""

import threading
import unittest
from unittest import mock

import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows.config import analysis_market_var
from tradingagents.dataflows.errors import NoMarketDataError


def _no_data(symbol, *a, **k):
    raise NoMarketDataError(symbol, symbol, "no rows")


def _returns(value):
    def impl(*a, **k):
        return value

    return impl


@pytest.mark.unit
class TestConcurrentMarketIsolation(unittest.TestCase):
    def test_two_threads_different_markets_do_not_clobber(self):
        # Two threads, each simulating a graph run: one CN, one US. Each sets
        # its own ``analysis_market_var`` (the ContextVar that replaces the
        # old global ``_config["analysis_market"]``) and calls
        # ``route_to_vendor`` for a non-symbol method. Pre-#1290 the second
        # write overwrote the first in the shared dict; with ContextVar each
        # thread's value is isolated and propagated through ``copy_context``
        # (done automatically by Python 3.9+ ``Thread.start``).
        barrier = threading.Barrier(2)
        results = {}
        errors = []

        def _run(ticker: str, market: str, expected: str):
            try:
                # Set the per-run market BEFORE the barrier so both threads
                # have written before either reads — the worst-case interleaving
                # for a shared global. ContextVar isolation makes this safe.
                token = analysis_market_var.set(market)
                barrier.wait()
                with mock.patch.dict(
                    interface.VENDOR_METHODS,
                    {
                        "get_macro_indicators": {
                            "china_macro": _returns("CN_MACRO"),
                            "fred": _returns("FRED_MACRO"),
                        }
                    },
                    clear=False,
                ):
                    out = interface.route_to_vendor(
                        "get_macro_indicators", "cpi", "2026-01-01", 365
                    )
                results[ticker] = out
                analysis_market_var.reset(token)
            except Exception as e:
                errors.append(e)

        cn_thread = threading.Thread(
            target=_run, args=("600519.SS", "cn", "CN_MACRO"), name="cn-run"
        )
        us_thread = threading.Thread(target=_run, args=("AAPL", "us", "FRED_MACRO"), name="us-run")
        cn_thread.start()
        us_thread.start()
        cn_thread.join(timeout=10)
        us_thread.join(timeout=10)

        self.assertEqual(errors, [], f"threads raised: {errors}")
        self.assertEqual(results.get("600519.SS"), "CN_MACRO")
        self.assertEqual(results.get("AAPL"), "FRED_MACRO")


if __name__ == "__main__":
    unittest.main()
