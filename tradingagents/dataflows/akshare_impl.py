"""AKShare vendor implementation for OHLCV price data and technical indicators.

AKShare (https://akshare.akfamily.xyz/) is a keyless Chinese data-source
aggregator that pulls from Sina/Eastmoney etc. It covers both A-shares
(``stock_zh_a_hist``) and US stocks (``stock_us_hist``) with no daily request
cap, making it a resilient fallback when yfinance is rate-limited and Alpha
Vantage's free tier (25 req/day) is exhausted.

Only the price-data categories (``core_stock_apis`` + ``technical_indicators``)
are implemented here; fundamentals/news stay on yfinance + alpha_vantage since
AKShare's coverage there is weaker for US tickers.

AKShare is an *optional* dependency: it is imported lazily inside each public
function, and a missing install raises ``VendorNotConfiguredError`` so the
routing layer (``interface.route_to_vendor``) skips to the next vendor instead
of crashing.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from typing import Annotated

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from .config import get_config
from .errors import NoMarketDataError, VendorNotConfiguredError
from .stockstats_utils import (
    _assert_ohlcv_not_stale,
    _clean_dataframe,
)
from .symbol_utils import normalize_symbol
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

# AKShare is an optional dependency. Cached after first successful import so
# the per-call import cost is paid only once.
_akshare_module = None

# Transient transport errors worth a retry: AKShare's Eastmoney/Sina backends
# occasionally drop the connection mid-response (``RemoteDisconnected``) or
# time out under load. ``requests.exceptions.ConnectionError`` covers
# ``RemoteDisconnected``/``ConnectionResetError``; ``Timeout`` covers reads
# that exceeded the socket window. Retrying these here absorbs the blip inside
# the vendor before the router treats it as a hard failure and aborts a core
# data call (#989).
_TRANSIENT_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def _get_akshare():
    """Lazily import akshare, raising VendorNotConfiguredError if absent.

    Imported on demand so the optional dependency (and its transitive crawl
    stack: lxml/beautifulsoup/requests) isn't required by the rest of the
    package. The router catches ``VendorNotConfiguredError`` and falls through
    to the next vendor, so a missing install degrades gracefully.
    """
    global _akshare_module
    if _akshare_module is not None:
        return _akshare_module
    try:
        import akshare as ak
    except ImportError as exc:
        raise VendorNotConfiguredError(
            "AKShare support requires the optional 'akshare' dependency. "
            "Install it with: pip install akshare"
        ) from exc
    _akshare_module = ak
    return ak


def _akshare_retry(func, max_retries=3, base_delay=2.0):
    """Execute an AKShare call with exponential backoff on transient network errors.

    AKShare's Eastmoney/Sina backends intermittently drop connections
    (``RemoteDisconnected`` / ``ConnectionResetError``) or time out under load.
    Unlike ``yf_retry`` (which targets HTTP 429 throttles and translates them
    to ``VendorRateLimitError`` so the router skips to the next vendor), this
    wrapper retries *transport* blips that usually succeed on a second attempt;
    once retries are exhausted the original exception propagates so the
    router's generic ``except Exception`` branch still records it as a
    ``first_error`` and falls through to the next configured vendor. Vendor
    semantics (``NoMarketDataError`` / ``VendorNotConfiguredError``) are never
    retried — they are deterministic per call.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except _TRANSIENT_NETWORK_ERRORS as e:
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "AKShare transient error, retrying in %.0fs (attempt %d/%d): %s",
                    delay,
                    attempt + 1,
                    max_retries,
                    e,
                )
                time.sleep(delay)
            else:
                raise


# --- market detection -------------------------------------------------------

# A-share symbols: bare 6-digit code (600519) or with exchange suffix
# (600519.SH / 000001.SZ / 600000.SS / 830799.BJ). The SS suffix is Sina's
# synonym for SH (Shanghai Stock Exchange).
_A_SHARE_RE = re.compile(r"^\d{6}(\.(SH|SZ|SS|BJ))?$", re.IGNORECASE)

# Hong Kong symbols: 1-5 digit code with a .HK suffix (0700.HK, 9988.HK).
# AKShare's stock_hk_hist wants a zero-padded 5-digit code.
_HK_RE = re.compile(r"^\d{1,5}\.HK$", re.IGNORECASE)

# Yahoo-native symbols that AKShare cannot serve: indices (^GSPC), futures
# (GC=F), forex (EURUSD=X), crypto (BTC-USD). AKShare only handles plain
# equity tickers.
_NON_EQUITY_RE = re.compile(r"[\^=]")

# US exchange prefixes used by AKShare's stock_us_hist. The symbol passed to
# that function must be "<prefix>.<TICKER>". We try NASDAQ first (most US
# tech names the agents analyze live there), then NYSE, then AMEX. The first
# prefix that returns a non-empty frame is cached per symbol so subsequent
# calls skip the probe.
_US_EXCHANGE_PREFIXES = ("106", "105", "107")  # NASDAQ, NYSE, AMEX
_us_symbol_prefix_cache: dict[str, str] = {}


def _detect_market(symbol: str) -> str | None:
    """Classify a symbol as ``"a_share"``, ``"us"``, or ``None`` (unsupported).

    AKShare serves plain equities only. Yahoo-native instruments (indices,
    futures, forex, crypto) return ``None`` so the router skips AKShare and
    tries the next vendor instead of failing every prefix combination.

    A-share detection is purely syntactic (6 digits with optional exchange
    suffix); anything else that looks like an equity ticker is treated as US.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    s = symbol.strip().upper()
    if _A_SHARE_RE.match(s):
        return "a_share"
    if _HK_RE.match(s):
        return "hk"
    # Reject Yahoo-native non-equity symbols (indices/futures/forex/crypto).
    if _NON_EQUITY_RE.search(s):
        return None
    # A bare equity ticker (letters, maybe dots for class shares like BRK.B).
    # Must be mostly alphabetic to avoid matching dates/garbage.
    if re.match(r"^[A-Z][A-Z.]*$", s):
        return "us"
    return None


def _to_akshare_a_share(symbol: str) -> str:
    """Strip the exchange suffix; AKShare's stock_zh_a_hist wants bare 6-digit."""
    s = symbol.strip().upper()
    if "." in s:
        s = s.split(".")[0]
    return s


def _to_akshare_hk(symbol: str) -> str:
    """Zero-pad the HK code to 5 digits; AKShare's stock_hk_hist requires it.

    e.g. ``0700.HK`` -> ``00700``, ``9988.HK`` -> ``09988``.
    """
    s = symbol.strip().upper()
    code = s.split(".")[0]
    return code.zfill(5)


def _to_akshare_us(symbol: str) -> str:
    """Resolve a US ticker to AKShare's ``<prefix>.<TICKER>`` form.

    AKShare requires an exchange prefix (106=NASDAQ, 105=NYSE, 107=AMEX) and
    has no symbol-search endpoint, so we probe prefixes on first sight and
    cache the winner. Subsequent calls for the same ticker hit the cache and
    skip the probe entirely.
    """
    ticker = symbol.strip().upper()
    cached = _us_symbol_prefix_cache.get(ticker)
    if cached:
        return f"{cached}.{ticker}"

    ak = _get_akshare()
    today = pd.Timestamp.today()
    start = (today - pd.Timedelta(days=7)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    for prefix in _US_EXCHANGE_PREFIXES:
        candidate = f"{prefix}.{ticker}"
        try:
            df = ak.stock_us_hist(
                symbol=candidate,
                period="daily",
                start_date=start,
                end_date=end,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                _us_symbol_prefix_cache[ticker] = prefix
                logger.info("Resolved US ticker %s to AKShare symbol %s", ticker, candidate)
                return candidate
        except Exception as e:
            logger.debug("AKShare prefix %s for %s failed: %s", prefix, ticker, e)
            continue
    # No prefix worked — return the NASDAQ form (most common) so the caller's
    # fetch raises a clean NoMarketDataError rather than a format error.
    return f"{_US_EXCHANGE_PREFIXES[0]}.{ticker}"


# --- column normalization ---------------------------------------------------

# AKShare returns Chinese column names. Map them to the English OHLCV schema
# the rest of the pipeline (stockstats, _clean_dataframe) expects.
_AK_COLUMN_MAP = {
    "日期": "Date",
    "开盘": "Open",
    "收盘": "Close",
    "最高": "High",
    "最低": "Low",
    "成交量": "Volume",
}


def _normalize_akshare_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename AKShare's Chinese columns to the OHLCV schema.

    Falls back to keeping any column that already matches the English names
    (some AKShare endpoints return mixed casing), so this is idempotent.
    """
    if df is None or df.empty:
        return df
    renamed = df.rename(columns=_AK_COLUMN_MAP)
    # Drop the Chinese-only auxiliary columns (成交额, 振幅, 涨跌幅, 涨跌额,
    # 换手率) that stockstats doesn't understand.
    keep = [c for c in ("Date", "Open", "High", "Low", "Close", "Volume") if c in renamed.columns]
    return renamed[keep]


# --- OHLCV loading with cache -----------------------------------------------


def load_ohlcv_akshare(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV via AKShare with per-symbol disk cache, mirroring load_ohlcv.

    Downloads 5 years of daily data up to today and caches per symbol (file
    prefixed ``akshare-`` to avoid colliding with yfinance's cache). Rows
    after ``curr_date`` are dropped to prevent look-ahead bias in backtests.
    Stale frames are rejected via ``_assert_ohlcv_not_stale``.

    Raises ``NoMarketDataError`` if the symbol is unknown or AKShare returns
    no rows, and ``VendorNotConfiguredError`` if akshare isn't installed.
    """
    market = _detect_market(symbol)
    if market is None:
        # AKShare can't serve this instrument class — let the router try the
        # next vendor instead of probing pointlessly.
        raise NoMarketDataError(symbol, symbol, "AKShare does not cover this symbol type")

    ak = _get_akshare()

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    # Cache uses a fixed window (5y to today) so one file per symbol.
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y%m%d")
    end_str = today_date.strftime("%Y%m%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    # Cache key includes the market so a US "AAPL" and an A-share can't
    # collide (they can't — different formats — but being explicit is cheap).
    safe_sym = safe_ticker_component(symbol.replace(".", "_"))
    data_file = os.path.join(
        config["data_cache_dir"],
        f"akshare-{market}-{safe_sym}-{start_str}-{end_str}.csv",
    )

    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if not cached.empty and "Close" in cached.columns:
            data = cached

    if data is None:
        downloaded = _download_ohlcv(ak, market, symbol, start_str, end_str)
        downloaded = _normalize_akshare_columns(downloaded)
        if downloaded is None or downloaded.empty or "Close" not in downloaded.columns:
            raise NoMarketDataError(symbol, symbol, "AKShare returned no rows")
        downloaded.to_csv(data_file, index=False, encoding="utf-8")
        data = downloaded

    data = _clean_dataframe(data)
    data = data[data["Date"] <= curr_date_dt]
    _assert_ohlcv_not_stale(data, curr_date, symbol, symbol)
    return data


def _download_ohlcv(ak, market: str, symbol: str, start_str: str, end_str: str) -> pd.DataFrame:
    """Call the AKShare endpoint appropriate for the market.

    All three endpoints (``stock_zh_a_hist`` / ``stock_hk_hist`` /
    ``stock_us_hist``) take ``YYYYMMDD`` dates and return a Chinese-named
    daily OHLCV frame; column normalization happens in the caller.
    """
    if market == "a_share":
        ak_symbol = _to_akshare_a_share(symbol)
        return _akshare_retry(
            lambda: ak.stock_zh_a_hist(
                symbol=ak_symbol,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq",
            )
        )
    if market == "hk":
        ak_symbol = _to_akshare_hk(symbol)
        return _akshare_retry(
            lambda: ak.stock_hk_hist(
                symbol=ak_symbol,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq",
            )
        )
    # US
    ak_symbol = _to_akshare_us(symbol)
    return _akshare_retry(
        lambda: ak.stock_us_hist(
            symbol=ak_symbol,
            period="daily",
            start_date=start_str,
            end_date=end_str,
            adjust="qfq",
        )
    )


# --- public vendor functions ------------------------------------------------


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve OHLCV via AKShare, formatted to match the yfinance vendor output.

    The header mirrors ``get_YFin_data_online`` so downstream agents can't
    tell which vendor served the data — only the resolved symbol label differs.
    """
    datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    # AKShare has no end-exclusive quirk; request through end_date inclusive.
    # load_ohlcv_akshare fetches a 5y window to today, so we just slice it.
    data = load_ohlcv_akshare(symbol, end_date)

    start_dt = pd.to_datetime(start_date)
    end_pdt = pd.to_datetime(end_date)
    data = data[(data["Date"] >= start_dt) & (data["Date"] <= end_pdt)]

    if data.empty:
        raise NoMarketDataError(symbol, symbol, f"no rows between {start_date} and {end_date}")

    # AKShare dates are already timezone-naive (unlike yfinance), so no
    # tz_localize is needed.

    numeric_columns = ["Open", "High", "Low", "Close"]
    for col in numeric_columns:
        if col in data.columns:
            data[col] = data[col].round(2)

    csv_string = data.to_csv()

    label = symbol
    header = f"# Stock data for {label} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + csv_string


def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Compute a technical indicator over an AKShare-sourced OHLCV window.

    Mirrors ``get_stock_stats_indicators_window`` (yfinance) but sources OHLCV
    from ``load_ohlcv_akshare``. The indicator math (stockstats) is
    vendor-agnostic, so only the data-loading call differs.
    """
    from stockstats import wrap

    # Same indicator catalog and descriptions as the yfinance vendor so agents
    # get consistent tool behavior regardless of which vendor served the data.
    best_ind_params = {
        "close_50_sma": "50 SMA: A medium-term trend indicator.",
        "close_200_sma": "200 SMA: A long-term trend benchmark.",
        "close_10_ema": "10 EMA: A responsive short-term average.",
        "macd": "MACD: Computes momentum via differences of EMAs.",
        "macds": "MACD Signal: An EMA smoothing of the MACD line.",
        "macdh": "MACD Histogram: Shows the gap between MACD and its signal.",
        "rsi": "RSI: Measures momentum to flag overbought/oversold conditions.",
        "boll": "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands.",
        "boll_ub": "Bollinger Upper Band: Typically 2 std dev above the middle.",
        "boll_lb": "Bollinger Lower Band: Typically 2 std dev below the middle.",
        "atr": "ATR: Averages true range to measure volatility.",
        "vwma": "VWMA: A moving average weighted by volume.",
        "mfi": "MFI: Money Flow Index, momentum using price and volume.",
    }

    if indicator not in best_ind_params:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(best_ind_params.keys())}"
        )

    end_date = curr_date
    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)

    try:
        data = load_ohlcv_akshare(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        df[indicator]  # trigger stockstats to calculate the indicator

        date_values = []
        current_dt = curr_date_dt
        while current_dt >= before:
            date_str = current_dt.strftime("%Y-%m-%d")
            matching = df[df["Date"] == date_str]
            if not matching.empty:
                val = matching[indicator].values[0]
                date_values.append((date_str, "N/A" if pd.isna(val) else str(val)))
            else:
                date_values.append((date_str, "N/A: Not a trading day (weekend or holiday)"))
            current_dt = current_dt - relativedelta(days=1)

        ind_string = "".join(f"{d}: {v}\n" for d, v in date_values)
    except NoMarketDataError:
        raise  # Unknown/delisted symbol — let the router emit the sentinel
    except Exception as e:
        logger.warning("AKShare indicator %s for %s failed: %s", indicator, symbol, e)
        ind_string = ""

    result_str = (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + best_ind_params.get(indicator, "No description available.")
    )
    return result_str
