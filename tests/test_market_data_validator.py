"""Tests for the deterministic market-data verification snapshot (#830/#881)."""

from __future__ import annotations

import pandas as pd
import pytest

import tradingagents.dataflows.market_data_validator as validator
from tradingagents.dataflows.errors import NoMarketDataError


def _sample_ohlcv() -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-05-20")
    closes = [100 + i for i in range(len(dates))]
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [c - 0.5 for c in closes],
            "High": [c + 1.0 for c in closes],
            "Low": [c - 1.0 for c in closes],
            "Close": closes,
            "Volume": [1_000_000 + i for i in range(len(dates))],
        }
    )


@pytest.mark.unit
class TestVerifiedSnapshot:
    def test_excludes_future_rows(self, monkeypatch):
        data = pd.concat(
            [
                _sample_ohlcv(),
                pd.DataFrame(
                    {
                        "Date": [pd.Timestamp("2026-06-01")],
                        "Open": [999.0],
                        "High": [999.0],
                        "Low": [999.0],
                        "Close": [999.0],
                        "Volume": [999],
                    }
                ),
            ],
            ignore_index=True,
        )
        monkeypatch.setattr(validator, "load_ohlcv_routed", lambda s, d: data)

        snap = validator.build_verified_market_snapshot("COF", "2026-05-13")
        assert "Verified market data snapshot for COF" in snap
        assert "Requested analysis date: 2026-05-13" in snap
        assert "Latest trading row used: 2026-05-13" in snap
        assert "999.00" not in snap  # future row excluded
        assert "boll_lb" in snap  # indicators present

    def test_uses_previous_trading_day_when_date_is_weekend(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv_routed", lambda s, d: _sample_ohlcv())
        # 2026-05-16 is a Saturday; latest row should be Fri 2026-05-15
        snap = validator.build_verified_market_snapshot("COF", "2026-05-16")
        assert "Latest trading row used: 2026-05-15" in snap
        assert "Recent verified closes" in snap

    def test_look_back_window_capped_at_30(self, monkeypatch):
        monkeypatch.setattr(validator, "load_ohlcv_routed", lambda s, d: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot("COF", "2026-05-20", look_back_days=999)
        # last-N closes table has at most 30 data rows
        close_rows = [ln for ln in snap.splitlines() if ln.startswith("| 2026-")]
        assert 0 < len(close_rows) <= 30


@pytest.mark.unit
class TestVerifiedSnapshotNoDataSentinel:
    """When every vendor is exhausted, the builder must return a sentinel
    string instead of raising — matching ``route_to_vendor``'s convention so
    the LangChain ToolNode doesn't crash the analysis task.

    Regression for the 2026-07-04 production traceback: yfinance rate-limited
    + akshare ConnectionError propagated uncaught through load_ohlcv_routed,
    aborting the whole run. The builder now catches NoMarketDataError and
    degrades to a ``NO_DATA_AVAILABLE:`` sentinel.
    """

    def test_no_market_data_returns_sentinel(self, monkeypatch):
        def _no_data(symbol, curr_date):
            raise NoMarketDataError(symbol, symbol, "all vendors exhausted")

        monkeypatch.setattr(validator, "load_ohlcv_routed", _no_data)
        snap = validator.build_verified_market_snapshot("0700.HK", "2026-05-13")
        assert "NO_DATA_AVAILABLE" in snap
        assert "0700.HK" in snap
        assert "all vendors exhausted" in snap
        # The agent must be told NOT to fabricate values.
        assert "Do not estimate" in snap or "do not fabricate" in snap.lower()

    def test_no_market_data_with_stale_detail_surfaces_reason(self, monkeypatch):
        def _stale(symbol, curr_date):
            raise NoMarketDataError(
                symbol, symbol, "latest row is 2026-01-01, 134 days before (stale)"
            )

        monkeypatch.setattr(validator, "load_ohlcv_routed", _stale)
        snap = validator.build_verified_market_snapshot("AAPL", "2026-05-13")
        assert "NO_DATA_AVAILABLE" in snap
        assert "stale" in snap

    def test_value_error_on_empty_frame_returns_sentinel(self, monkeypatch):
        """An empty frame raises ValueError inside _verified_rows — degrade too."""
        monkeypatch.setattr(validator, "load_ohlcv_routed", lambda s, d: pd.DataFrame())
        snap = validator.build_verified_market_snapshot("COF", "2026-05-13")
        assert "NO_DATA_AVAILABLE" in snap
        assert "COF" in snap

    def test_no_rows_on_or_before_date_returns_sentinel(self, monkeypatch):
        """Frame has data, but nothing on/before curr_date (e.g. a new listing)."""
        monkeypatch.setattr(validator, "load_ohlcv_routed", lambda s, d: _sample_ohlcv())
        snap = validator.build_verified_market_snapshot("COF", "2020-01-01")
        assert "NO_DATA_AVAILABLE" in snap
        assert "2020-01-01" in snap


@pytest.mark.unit
class TestTool:
    def test_tool_delegates_to_builder(self, monkeypatch):
        from tradingagents.agents.utils.market_data_validation_tools import (
            get_verified_market_snapshot,
        )

        monkeypatch.setattr(validator, "load_ohlcv_routed", lambda s, d: _sample_ohlcv())
        out = get_verified_market_snapshot.invoke({"symbol": "COF", "curr_date": "2026-05-20"})
        assert "Verified market data snapshot for COF" in out
