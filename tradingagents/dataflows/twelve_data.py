"""Twelve Data vendor for TradingAgents — US stock data via direct REST API.

Covers all data categories for US stocks: OHLCV, technical indicators,
fundamentals, financial statements, and news. Uses Twelve Data's free tier
(8 req/min, 800 req/day) with a registered API key.

Replaces yfinance/alpha_vantage as the primary US-market vendor to avoid
their chronic rate-limiting issues. Direct REST calls (no SDK dependency)
keep the module self-contained and consistent with the other vendors in
this package.

API docs: https://twelvedata.com/docs
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Annotated

import pandas as pd
import requests

from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.twelvedata.com"
REQUEST_TIMEOUT = 30

# Min interval between Twelve Data requests (seconds). Free tier allows 8/min,
# so ~7.5s spacing avoids throttling. A lock isn't needed: the routing layer
# is sequential per vendor within a single method call.
_MIN_INTERVAL = 7.5
_last_call = [0.0]


class TwelveDataNotConfiguredError(VendorNotConfiguredError):
    """Raised when Twelve Data is selected but no API key is configured."""

    pass


class TwelveDataRateLimitError(VendorRateLimitError):
    """Raised when Twelve Data API rate limit is exceeded."""

    pass


def get_api_key() -> str:
    """Retrieve the Twelve Data API key from environment variables."""
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        raise TwelveDataNotConfiguredError("TWELVE_DATA_API_KEY environment variable is not set.")
    return api_key


def _throttle():
    """Enforce min interval between requests to respect 8/min free-tier limit."""
    wait = _MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


def _request(endpoint: str, params: dict | None = None) -> dict | str:
    """Make a throttled GET request to Twelve Data API.

    Raises TwelveDataRateLimitError on 429 or rate-limit status, and
    NoMarketDataError when the API returns an explicit error for an
    unknown/invalid symbol.
    """
    _throttle()
    api_params = {"apikey": get_api_key()}
    if params:
        api_params.update(params)

    try:
        response = requests.get(
            f"{API_BASE_URL}/{endpoint}", params=api_params, timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as e:
        raise NoMarketDataError(
            params.get("symbol", ""),
            params.get("symbol", ""),
            f"network error: {e}",
        ) from e

    if response.status_code == 429:
        raise TwelveDataRateLimitError("Twelve Data rate limit exceeded (429)")

    try:
        data = response.json()
    except ValueError:
        return response.text

    # Twelve Data returns {"status": "error", "message": "..."} for failures.
    if isinstance(data, dict) and data.get("status") == "error":
        msg = data.get("message", "")
        low = msg.lower()
        if "rate" in low or "limit" in low:
            raise TwelveDataRateLimitError(f"Twelve Data rate limit: {msg}")
        # Unknown symbol, invalid params, etc.
        symbol = params.get("symbol", "")
        raise NoMarketDataError(symbol, symbol, msg)

    return data


# ---------------------------------------------------------------------------
# 1. OHLCV stock data
# ---------------------------------------------------------------------------


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get daily OHLCV stock data via Twelve Data time_series endpoint."""
    canonical = normalize_symbol(symbol)

    params = {
        "symbol": canonical,
        "interval": "1day",
        "start_date": start_date,
        "end_date": end_date,
        "format": "JSON",
        "timezone": "America/New_York",
    }
    data = _request("time_series", params)

    if not isinstance(data, dict) or not data.get("values"):
        raise NoMarketDataError(symbol, canonical, f"no rows between {start_date} and {end_date}")

    rows = data["values"]
    # Twelve Data returns newest-first; reverse to chronological.
    rows.reverse()

    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.rename(
        columns={
            "datetime": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Close"] = df["Close"].round(2)

    csv_string = df.to_csv(index=False)

    label = canonical if canonical == symbol.upper() else f"{canonical} (from {symbol})"
    header = f"# Stock data for {label} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(df)}\n"
    header += "# Data source: Twelve Data\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string


# ---------------------------------------------------------------------------
# 2. Technical indicators
# ---------------------------------------------------------------------------

# Map our indicator names to Twelve Data API parameters.
# Our name → (twelvedata function name, interval param, extra params)
_INDICATOR_MAP = {
    "close_50_sma": ("sma", {"interval": "1day", "time_period": 50}),
    "close_200_sma": ("sma", {"interval": "1day", "time_period": 200}),
    "close_10_ema": ("ema", {"interval": "1day", "time_period": 10}),
    "macd": ("macd", {"interval": "1day"}),
    "macds": ("macd", {"interval": "1day"}),
    "macdh": ("macd", {"interval": "1day"}),
    "rsi": ("rsi", {"interval": "1day", "time_period": 14}),
    "boll": ("bbands", {"interval": "1day", "time_period": 20}),
    "boll_ub": ("bbands", {"interval": "1day", "time_period": 20}),
    "boll_lb": ("bbands", {"interval": "1day", "time_period": 20}),
    "atr": ("atr", {"interval": "1day", "time_period": 14}),
    "vwma": ("vwma", {"interval": "1day", "time_period": 20}),
    "mfi": ("mfi", {"interval": "1day", "time_period": 14}),
}

_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: A medium-term trend indicator.",
    "close_200_sma": "200 SMA: A long-term trend benchmark.",
    "close_10_ema": "10 EMA: A responsive short-term average.",
    "macd": "MACD: Computes momentum via differences of EMAs.",
    "macds": "MACD Signal: An EMA smoothing of the MACD line.",
    "macdh": "MACD Histogram: Shows the gap between the MACD line and its signal.",
    "rsi": "RSI: Measures momentum to flag overbought/oversold conditions.",
    "boll": "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: Typically 2 standard deviations above the middle line.",
    "boll_lb": "Bollinger Lower Band: Typically 2 standard deviations below the middle line.",
    "atr": "ATR: Averages true range to measure volatility.",
    "vwma": "VWMA: A moving average weighted by volume.",
    "mfi": "MFI: The Money Flow Index, a momentum indicator using price and volume.",
}


def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator"],
    curr_date: Annotated[str, "current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Get technical indicator values via Twelve Data indicators endpoint."""
    canonical = normalize_symbol(symbol)

    if indicator not in _INDICATOR_MAP:
        raise ValueError(
            f"Indicator {indicator} is not supported. "
            f"Please choose from: {list(_INDICATOR_MAP.keys())}"
        )

    func_name, extra_params = _INDICATOR_MAP[indicator]
    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)

    params = {
        "symbol": canonical,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
        "format": "JSON",
        "timezone": "America/New_York",
        **extra_params,
    }
    data = _request(func_name, params)

    if not isinstance(data, dict) or not data.get("values"):
        raise NoMarketDataError(symbol, canonical, f"no indicator values for {indicator}")

    rows = data["values"]
    rows.reverse()  # chronological

    # Extract the right output field based on indicator type
    result_lines = []
    for row in rows:
        date_str = row.get("datetime", "")[:10]
        if indicator == "macd":
            value = row.get("macd", "N/A")
        elif indicator == "macds":
            value = row.get("macd_signal", "N/A")
        elif indicator == "macdh":
            value = row.get("macd_histogram", "N/A")
        elif indicator == "boll":
            value = row.get("middle_band", "N/A")
        elif indicator == "boll_ub":
            value = row.get("upper_band", "N/A")
        elif indicator == "boll_lb":
            value = row.get("lower_band", "N/A")
        else:
            value = row.get(
                indicator, row.get("sma", row.get("ema", row.get("rsi", row.get("atr", "N/A"))))
            )
        result_lines.append(f"{date_str}: {value}")

    result_str = (
        f"## {indicator} values from {start_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + "\n".join(result_lines)
        + "\n\n"
        + _INDICATOR_DESCRIPTIONS.get(indicator, "No description available.")
    )
    return result_str


# ---------------------------------------------------------------------------
# 3. Fundamentals
# ---------------------------------------------------------------------------


def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get company fundamentals via Twelve Data profile endpoint."""
    canonical = normalize_symbol(ticker)

    data = _request("profile", {"symbol": canonical})

    if not isinstance(data, dict) or data.get("status") == "error":
        raise NoMarketDataError(ticker, canonical, "no fundamentals returned")

    fields = [
        ("Name", data.get("name")),
        ("Exchange", data.get("exchange")),
        ("Sector", data.get("sector")),
        ("Industry", data.get("industry")),
        ("Market Cap", data.get("market_cap")),
        ("PE Ratio (TTM)", data.get("pe_ratio")),
        ("Forward PE", data.get("forward_pe")),
        ("PEG Ratio", data.get("peg_ratio")),
        ("Price to Book", data.get("price_book")),
        ("EPS (TTM)", data.get("earnings_per_share")),
        ("Dividend Yield", data.get("dividend_yield")),
        ("Beta", data.get("beta")),
        ("52 Week High", data.get("high_52_week")),
        ("52 Week Low", data.get("low_52_week")),
        ("50 Day Average", data.get("simple_moving_average_50_day")),
        ("200 Day Average", data.get("simple_moving_average_200_day")),
        ("Revenue (TTM)", data.get("revenue_ttm")),
        ("Gross Profit (TTM)", data.get("gross_profit_ttm")),
        ("Net Income (TTM)", data.get("net_income_ttm")),
        ("Profit Margin", data.get("profit_margin")),
        ("Operating Margin", data.get("operating_margin")),
        ("Return on Equity", data.get("return_on_equity")),
        ("Return on Assets", data.get("return_on_assets")),
        ("Debt to Equity", data.get("debt_to_equity")),
        ("Current Ratio", data.get("current_ratio")),
        ("Book Value", data.get("book_value")),
        ("Free Cash Flow", data.get("free_cash_flow_ttm")),
    ]

    lines = [f"{label}: {value}" for label, value in fields if value is not None]

    if not lines:
        raise NoMarketDataError(ticker, canonical, "no fundamental fields returned")

    header = f"# Company Fundamentals for {canonical}\n"
    header += "# Data source: Twelve Data\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Financial statements
# ---------------------------------------------------------------------------


def _get_financial_statement(symbol: str, statement: str, freq: str, curr_date: str | None) -> str:
    """Shared helper for balance sheet / income statement / cash flow.

    statement: 'balance_sheet' | 'income_statement' | 'cash_flow'
    freq: 'annual' or 'quarterly'
    """
    canonical = normalize_symbol(symbol)
    period = "quarterly" if freq.lower() == "quarterly" else "annual"

    data = _request(statement, {"symbol": canonical, "period": period, "format": "JSON"})

    if not isinstance(data, dict) or not data.get(statement):
        raise NoMarketDataError(symbol, canonical, f"no {statement} data")

    reports = data[statement]
    if not isinstance(reports, list) or not reports:
        raise NoMarketDataError(symbol, canonical, f"no {statement} rows")

    # Filter by curr_date (point-in-time): drop reports after curr_date.
    if curr_date:
        cutoff = pd.to_datetime(curr_date)
        filtered = []
        for report in reports:
            report_date = report.get("date") or report.get("fiscal_date")
            if report_date:
                try:
                    if pd.to_datetime(report_date) <= cutoff:
                        filtered.append(report)
                except Exception:
                    filtered.append(report)
            else:
                filtered.append(report)
        reports = filtered if filtered else reports

    df = pd.DataFrame(reports)
    csv_string = df.to_csv(index=False)

    label_map = {
        "balance_sheet": "Balance Sheet",
        "income_statement": "Income Statement",
        "cash_flow": "Cash Flow",
    }
    label = label_map.get(statement, statement)

    header = f"# {label} for {canonical} ({freq})\n"
    header += "# Data source: Twelve Data\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string


def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get balance sheet via Twelve Data."""
    return _get_financial_statement(ticker, "balance_sheet", freq, curr_date)


def get_cashflow(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get cash flow statement via Twelve Data."""
    return _get_financial_statement(ticker, "cash_flow", freq, curr_date)


def get_income_statement(
    ticker: Annotated[str, "ticker symbol"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get income statement via Twelve Data."""
    return _get_financial_statement(ticker, "income_statement", freq, curr_date)


# ---------------------------------------------------------------------------
# 5. News
# ---------------------------------------------------------------------------


def get_news(
    ticker: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get stock-specific news via Twelve Data news endpoint."""
    canonical = normalize_symbol(ticker)

    params = {
        "symbol": canonical,
        "start_date": start_date,
        "end_date": end_date,
        "format": "JSON",
    }
    data = _request("news", params)

    if not isinstance(data, list) or not data:
        raise NoMarketDataError(
            ticker,
            canonical,
            f"no news from Twelve Data between {start_date} and {end_date}",
        )

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    news_str = ""
    count = 0
    for article in data:
        pub_date_str = article.get("published", "") or article.get("date", "")
        try:
            pub_dt = datetime.strptime(pub_date_str[:10], "%Y-%m-%d")
            if pub_dt < start_dt or pub_dt > end_dt:
                continue
        except (ValueError, IndexError):
            pass

        title = article.get("title", "No title")
        summary = article.get("summary", "") or article.get("body", "")
        source = article.get("source", "Twelve Data")
        link = article.get("url", "")

        news_str += f"### {title} (source: {source})\n"
        if summary:
            snippet = summary[:300] + "..." if len(summary) > 300 else summary
            news_str += f"{snippet}\n"
        if link:
            news_str += f"Link: {link}\n"
        news_str += "\n"
        count += 1

    if count == 0:
        raise NoMarketDataError(
            ticker,
            canonical,
            f"no news in date range {start_date} to {end_date} from Twelve Data",
        )

    return f"## {canonical} News, from {start_date} to {end_date}:\n\n" + news_str


def get_global_news(
    curr_date: Annotated[str, "Current date yyyy-mm-dd"],
    look_back_days: Annotated[int | None, "Days to look back; None = 7"] = None,
    limit: Annotated[int | None, "Max articles; None = 10"] = None,
) -> str:
    """Get global market news via Twelve Data news endpoint (no symbol filter).

    Twelve Data's news endpoint without a symbol returns general market news.
    """
    if look_back_days is None:
        look_back_days = 7
    if limit is None:
        limit = 10

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=look_back_days)

    params = {
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": curr_date,
        "format": "JSON",
    }
    data = _request("news", params)

    if not isinstance(data, list) or not data:
        raise NoMarketDataError(
            curr_date,
            curr_date,
            f"no global news from Twelve Data ending {curr_date}",
        )

    news_str = ""
    count = 0
    for article in data[:limit]:
        title = article.get("title", "No title")
        summary = article.get("summary", "") or article.get("body", "")
        source = article.get("source", "Twelve Data")
        pub_date = article.get("published", "") or article.get("date", "")
        link = article.get("url", "")

        news_str += f"### {title} (source: {source}, date: {pub_date[:10]})\n"
        if summary:
            snippet = summary[:300] + "..." if len(summary) > 300 else summary
            news_str += f"{snippet}\n"
        if link:
            news_str += f"Link: {link}\n"
        news_str += "\n"
        count += 1

    if count == 0:
        raise NoMarketDataError(
            curr_date,
            curr_date,
            "no global news in date range from Twelve Data",
        )

    return f"## Global News, from {start_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n" + news_str


# ---------------------------------------------------------------------------
# 6. Insider transactions (not available on Twelve Data free tier)
# ---------------------------------------------------------------------------


def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol of the company"],
) -> str:
    """Twelve Data does not offer insider transactions on the free tier.

    Raises NoMarketDataError so the routing layer falls back to yfinance.
    """
    canonical = normalize_symbol(ticker)
    raise NoMarketDataError(
        ticker,
        canonical,
        "Twelve Data does not provide insider transactions on the free tier",
    )
