"""Tushare Pro vendor implementation for A-share OHLCV, indicators, and
financial statements.

Tushare Pro (https://tushare.pro) is a token-authenticated Chinese market-data
API. It is the highest-quality source for A-shares (Shanghai / Shenzhen /
Beijing exchanges), covering daily prices, daily fundamentals (PE / PB / market
cap), and full quarterly financial statements. It complements yfinance and
akshare as a last-resort A-share fallback — yfinance's A-share coverage is
spotty, and akshare's Eastmoney backend occasionally drops connections.

Only A-share symbols are handled here; non-A-share instruments (HK / US /
index / forex / crypto) raise ``NoMarketDataError`` so the router falls through
to yfinance / akshare / alpha_vantage. This keeps Tushare's token-gated API
budget focused on the market segment it uniquely serves.

Tushare is an *optional* dependency: it is imported lazily inside each public
function, and a missing install OR missing ``TUSHARE_API_KEY`` raises
``VendorNotConfiguredError`` so the routing layer
(``interface.route_to_vendor``) skips to the next vendor instead of crashing.
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
from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError
from .stockstats_utils import (
    _assert_ohlcv_not_stale,
    _clean_dataframe,
    filter_financials_by_date,
)
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

# Tushare SDK + pro_api client cached after first successful import + token set.
# Both are reset to None in tests so the import path runs again.
_tushare_module = None
_tushare_pro_api = None

# Transient transport errors worth a retry: tushare's HTTP layer (requests
# under the hood) occasionally drops the connection mid-response or times out
# under load. Retrying these absorbs the blip inside the vendor before the
# router treats it as a hard failure and aborts a core data call (#989).
_TRANSIENT_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)

# Tushare error-message keywords that signal a throttle / quota / permission
# issue (router should skip to next vendor) vs. a hard failure (propagate).
# Chinese keywords dominate because Tushare returns localized messages:
# 频率 (frequency), 次数 (count/times), 积分 (points/credits), 限制 (limit),
# 超过 (exceed), 权限 (permission), 抱歉 (sorry — usually in quota messages).
_RATE_LIMIT_KEYWORDS = (
    "频率",
    "次数",
    "积分",
    "限制",
    "超过",
    "权限",
    "抱歉",
    "rate",
    "limit",
    "quota",
)


class TushareNotConfiguredError(VendorNotConfiguredError):
    """Raised when Tushare is selected but the package or TUSHARE_API_KEY is missing.

    A ``VendorNotConfiguredError`` (and thus still a ``ValueError``), so the
    routing layer's "vendor unavailable" handling and existing ValueError
    callers both keep working.
    """

    pass


class TushareRateLimitError(VendorRateLimitError):
    """Raised when Tushare throttles the request (frequency / points / quota exceeded)."""

    pass


def _get_api_key() -> str:
    """Retrieve the Tushare token from the TUSHARE_API_KEY environment variable."""
    api_key = os.getenv("TUSHARE_API_KEY")
    if not api_key:
        raise TushareNotConfiguredError(
            "TUSHARE_API_KEY environment variable is not set. "
            "Get a token at https://tushare.pro/register"
        )
    return api_key


def _get_tushare_pro():
    """Lazily import tushare, set the token, and return the cached pro_api client.

    Imported on demand so the optional dependency (and its transitive requests
    stack) isn't required by the rest of the package. The router catches
    ``VendorNotConfiguredError`` and falls through to the next vendor, so a
    missing install OR missing token degrades gracefully.
    """
    global _tushare_module, _tushare_pro_api
    if _tushare_pro_api is not None:
        return _tushare_pro_api
    try:
        import tushare as ts
    except ImportError as exc:
        raise TushareNotConfiguredError(
            "Tushare support requires the optional 'tushare' dependency. "
            "Install it with: pip install tushare"
        ) from exc
    token = _get_api_key()
    ts.set_token(token)
    _tushare_module = ts
    _tushare_pro_api = ts.pro_api()
    return _tushare_pro_api


def _classify_tushare_error(exc: Exception) -> Exception:
    """Wrap a raw tushare exception in the appropriate vendor error type.

    Tushare raises ``tushare.errors.TushareException`` (or a plain ``Exception``)
    with Chinese messages. Classify so the router treats quota / permission
    issues as transient (skip to next vendor via ``VendorRateLimitError``) and
    lets genuine failures surface to the generic handler.
    """
    msg = str(exc).lower()
    if any(kw.lower() in msg for kw in _RATE_LIMIT_KEYWORDS):
        return TushareRateLimitError(f"Tushare quota/rate limit: {exc}")
    return exc


def _tushare_retry(func, max_retries=3, base_delay=2.0):
    """Execute a Tushare call with exponential backoff on transient transport errors.

    Mirrors ``_akshare_retry``: absorbs ``ConnectionError`` / ``Timeout`` inside
    the vendor before the router treats them as hard failures. Vendor-level
    errors (``NoMarketDataError``, ``TushareNotConfiguredError``,
    ``TushareRateLimitError``) are never retried — they are deterministic per
    call.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except _TRANSIENT_NETWORK_ERRORS as e:
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Tushare transient error, retrying in %.0fs (attempt %d/%d): %s",
                    delay,
                    attempt + 1,
                    max_retries,
                    e,
                )
                time.sleep(delay)
            else:
                raise


# --- symbol detection -------------------------------------------------------

# A-share symbols: bare 6-digit code (600519) or with exchange suffix
# (600519.SH / 000001.SZ / 600000.SS / 830799.BJ). The SS suffix is Sina's
# synonym for SH (Shanghai Stock Exchange).
_A_SHARE_RE = re.compile(r"^\d{6}(\.(SH|SZ|SS|BJ))?$", re.IGNORECASE)


def _detect_market(symbol: str) -> str | None:
    """Return ``"a_share"`` if symbol is an A-share code, else ``None``.

    Tushare Pro only serves A-shares here; HK / US / index / forex / crypto
    return ``None`` so the router skips Tushare and tries yfinance / akshare
    instead of probing pointlessly against a token-gated API.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    s = symbol.strip().upper()
    if _A_SHARE_RE.match(s):
        return "a_share"
    return None


def _infer_exchange(code: str) -> str:
    """Infer the exchange suffix for a bare 6-digit A-share code.

    6xxxxx (incl. 688 STAR Market / 6xxxxx B-shares) → SH
    0xxxxx / 3xxxxx (main board + ChiNext) → SZ
    8/4/9xxxxx (Beijing Stock Exchange / former NEEQ) → BJ
    """
    first = code[0]
    if first == "6":
        return "SH"
    if first in ("0", "3"):
        return "SZ"
    if first in ("8", "4", "9"):
        return "BJ"
    return "SH"  # safe default for unusual codes


def _to_tushare_ts_code(symbol: str) -> str:
    """Normalize to Tushare's ``ts_code`` format: ``600519.SH`` / ``000001.SZ`` / ``830799.BJ``.

    Accepts bare 6-digit codes (infers the exchange from the leading digit) or
    codes with ``.SH`` / ``.SZ`` / ``.SS`` / ``.BJ`` suffixes. ``.SS`` (Sina's
    Shanghai synonym) is normalized to ``.SH`` (Tushare's form).
    """
    s = symbol.strip().upper()
    if "." in s:
        code, suffix = s.split(".", 1)
        if suffix == "SS":
            suffix = "SH"
        return f"{code}.{suffix}"
    return f"{s}.{_infer_exchange(s)}"


# --- column normalization ---------------------------------------------------

# Tushare's pro.daily returns lowercase column names. Map them to the OHLCV
# schema the rest of the pipeline (stockstats, _clean_dataframe) expects.
# `vol` is in 手 (100-share lots); `amount` is in 千元 (thousands of CNY).
# The units are preserved as-is — stockstats indicators (VWMA / MFI) only need
# relative volume, and the CSV header documents the schema for the agent.
_TUSHARE_COLUMN_MAP = {
    "trade_date": "Date",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "vol": "Volume",
    "amount": "Amount",
}


def _normalize_tushare_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename Tushare's lowercase columns to the OHLCV schema and parse dates.

    ``trade_date`` arrives as a ``YYYYMMDD`` string; convert to a
    ``pd.Timestamp`` so ``_clean_dataframe`` can parse it. Rows are sorted
    ascending by date to match the yfinance / akshare convention.
    """
    if df is None or df.empty:
        return df
    renamed = df.rename(columns=_TUSHARE_COLUMN_MAP)
    if "Date" in renamed.columns:
        renamed["Date"] = pd.to_datetime(renamed["Date"], format="%Y%m%d", errors="coerce")
    keep = [
        c
        for c in ("Date", "Open", "High", "Low", "Close", "Volume", "Amount")
        if c in renamed.columns
    ]
    out = renamed[keep].sort_values("Date").reset_index(drop=True)
    return out


# --- OHLCV loading with cache -----------------------------------------------


def load_ohlcv_tushare(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch A-share OHLCV via Tushare with per-symbol disk cache.

    Downloads 5 years of daily data up to today and caches per symbol (file
    prefixed ``tushare-`` to avoid colliding with yfinance / akshare caches).
    Rows after ``curr_date`` are dropped to prevent look-ahead bias in
    backtests. Stale frames are rejected via ``_assert_ohlcv_not_stale``.

    Raises ``NoMarketDataError`` for non-A-share symbols or empty results, and
    ``TushareNotConfiguredError`` if tushare / ``TUSHARE_API_KEY`` is missing.
    """
    if _detect_market(symbol) is None:
        # Tushare can't serve this instrument class — let the router try the
        # next vendor instead of burning a token-gated request.
        raise NoMarketDataError(symbol, symbol, "Tushare only serves A-shares")

    ts_code = _to_tushare_ts_code(symbol)
    pro = _get_tushare_pro()

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    # Cache uses a fixed window (5y to today) so one file per symbol.
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y%m%d")
    end_str = today_date.strftime("%Y%m%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    safe_sym = safe_ticker_component(symbol.replace(".", "_"))
    data_file = os.path.join(
        config["data_cache_dir"],
        f"tushare-a_share-{safe_sym}-{start_str}-{end_str}.csv",
    )

    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if not cached.empty and "Close" in cached.columns:
            data = cached

    if data is None:
        downloaded = _download_ohlcv(pro, ts_code, start_str, end_str)
        downloaded = _normalize_tushare_columns(downloaded)
        if downloaded is None or downloaded.empty or "Close" not in downloaded.columns:
            raise NoMarketDataError(symbol, ts_code, "Tushare returned no rows")
        downloaded.to_csv(data_file, index=False, encoding="utf-8")
        data = downloaded

    data = _clean_dataframe(data)
    data = data[data["Date"] <= curr_date_dt]
    _assert_ohlcv_not_stale(data, curr_date, symbol, ts_code)
    return data


def _download_ohlcv(pro, ts_code: str, start_str: str, end_str: str) -> pd.DataFrame:
    """Call ``pro.daily`` with retry and error classification."""
    try:
        return _tushare_retry(
            lambda: pro.daily(ts_code=ts_code, start_date=start_str, end_date=end_str)
        )
    except Exception as e:
        # Re-classify as rate limit if it matches quota keywords; otherwise
        # let it propagate so the router records it as a hard vendor failure.
        raise _classify_tushare_error(e) from e


# --- public vendor functions ------------------------------------------------


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Retrieve A-share OHLCV via Tushare, formatted to match the yfinance vendor output.

    The header mirrors ``get_YFin_data_online`` so downstream agents can't tell
    which vendor served the data — only the resolved symbol label differs.
    """
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")

    # load_ohlcv_tushare fetches a 5y window to today, so we just slice it.
    data = load_ohlcv_tushare(symbol, end_date)

    start_dt = pd.to_datetime(start_date)
    end_pdt = pd.to_datetime(end_date)
    data = data[(data["Date"] >= start_dt) & (data["Date"] <= end_pdt)]

    if data.empty:
        raise NoMarketDataError(symbol, symbol, f"no rows between {start_date} and {end_date}")

    numeric_columns = ["Open", "High", "Low", "Close"]
    for col in numeric_columns:
        if col in data.columns:
            data[col] = data[col].round(2)

    # Match yfinance's OHLCV schema (Date, Open, High, Low, Close, Volume) —
    # drop Tushare's `Amount` column so downstream agents see a uniform shape.
    output_cols = [
        c for c in ("Date", "Open", "High", "Low", "Close", "Volume") if c in data.columns
    ]
    csv_string = data[output_cols].to_csv(index=False)

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
    """Compute a technical indicator over a Tushare-sourced OHLCV window.

    Mirrors ``get_stock_stats_indicators_window`` (yfinance) and akshare's
    ``get_indicators``; only the data-loading call differs. The indicator math
    (stockstats) is vendor-agnostic.
    """
    from stockstats import wrap

    # Same indicator catalog and descriptions as the akshare vendor so agents
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
        data = load_ohlcv_tushare(symbol, curr_date)
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
        logger.warning("Tushare indicator %s for %s failed: %s", indicator, symbol, e)
        ind_string = ""

    result_str = (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {end_date}:\n\n"
        + ind_string
        + "\n\n"
        + best_ind_params.get(indicator, "No description available.")
    )
    return result_str


def _fetch_daily_basic(pro, ts_code: str, curr_date: str) -> pd.DataFrame:
    """Fetch the ``daily_basic`` snapshot (PE / PB / market cap) nearest curr_date.

    Tries ``curr_date`` first; if empty (non-trading day or no quote), widens
    to a 30-day window and takes the latest available row so fundamentals stay
    current even when the requested date is a holiday.
    """
    if curr_date:
        curr_yyyymmdd = pd.to_datetime(curr_date).strftime("%Y%m%d")
    else:
        curr_yyyymmdd = datetime.today().strftime("%Y%m%d")

    try:
        df = _tushare_retry(lambda: pro.daily_basic(ts_code=ts_code, trade_date=curr_yyyymmdd))
        if df is None or df.empty:
            # Non-trading day or no data; widen the window and take the latest.
            start = (
                pd.to_datetime(curr_yyyymmdd, format="%Y%m%d") - pd.Timedelta(days=30)
            ).strftime("%Y%m%d")
            df = _tushare_retry(
                lambda: pro.daily_basic(ts_code=ts_code, start_date=start, end_date=curr_yyyymmdd)
            )
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").tail(1)
        return df
    except Exception as e:
        raise _classify_tushare_error(e) from e


def get_fundamentals(
    ticker: Annotated[str, "ticker symbol of the company"],
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get A-share company fundamentals overview from Tushare.

    Combines ``stock_basic`` (name / industry / area / list date) with
    ``daily_basic`` (PE / PB / market cap / dividend yield) to approximate
    yfinance's fundamentals field set for A-share agents.
    """
    if _detect_market(ticker) is None:
        raise NoMarketDataError(ticker, ticker, "Tushare only serves A-shares")

    ts_code = _to_tushare_ts_code(ticker)
    pro = _get_tushare_pro()

    try:
        # Company static info.
        try:
            basic_df = _tushare_retry(lambda: pro.stock_basic(ts_code=ts_code))
        except Exception as e:
            raise _classify_tushare_error(e) from e

        if basic_df is None or basic_df.empty:
            raise NoMarketDataError(ticker, ts_code, "Tushare stock_basic returned no rows")

        basic_row = basic_df.iloc[0].to_dict()

        # Daily fundamentals snapshot (PE/PB/market cap) near curr_date.
        daily_basic_df = _fetch_daily_basic(pro, ts_code, curr_date)
        db_row = (
            daily_basic_df.iloc[0].to_dict()
            if (daily_basic_df is not None and not daily_basic_df.empty)
            else {}
        )

        def _fmt(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            return v

        def _mv(v):
            """Format market value (万元) as 亿元 (100M CNY) with 2 decimals."""
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            try:
                return f"{float(v) / 10000:.2f}"
            except (TypeError, ValueError):
                return v

        fields = [
            ("Name", basic_row.get("name")),
            ("English Name", basic_row.get("enname")),
            ("Area", basic_row.get("area")),
            ("Industry", basic_row.get("industry")),
            ("Market", basic_row.get("market")),
            ("Exchange", basic_row.get("exchange")),
            ("List Date", basic_row.get("list_date")),
            ("PE (TTM)", _fmt(db_row.get("pe_ttm"))),
            ("PB", _fmt(db_row.get("pb"))),
            ("PS (TTM)", _fmt(db_row.get("ps_ttm"))),
            ("Dividend Yield (TTM)", _fmt(db_row.get("dv_ttm"))),
            ("Total Market Cap (亿元 CNY)", _mv(db_row.get("total_mv"))),
            ("Circulating Market Cap (亿元 CNY)", _mv(db_row.get("circ_mv"))),
            ("Total Shares (万股)", _fmt(db_row.get("total_share"))),
            ("Circulating Shares (万股)", _fmt(db_row.get("float_share"))),
            ("Turnover Rate", _fmt(db_row.get("turnover_rate"))),
            ("Close (on snapshot date)", _fmt(db_row.get("close"))),
        ]

        lines = [f"{label}: {value}" for label, value in fields if value is not None]
        if not lines:
            raise NoMarketDataError(ticker, ts_code, "no fundamental fields returned")

        header = f"# Company Fundamentals for {ts_code}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return header + "\n".join(lines)

    except NoMarketDataError:
        raise
    except TushareRateLimitError:
        raise
    except Exception as e:
        return f"Error retrieving fundamentals for {ticker}: {str(e)}"


# Metadata columns Tushare mixes into financial-statement rows. After
# transpose they'd appear as field rows; drop them so the output matches
# yfinance's schema (financial fields only, periods as columns).
_FINANCIAL_METADATA_FIELDS = frozenset(
    {"ts_code", "ann_date", "f_ann_date", "end_date", "end_type", "report_type", "update_flag"}
)


def _fetch_financial_statements(
    pro, ts_code: str, endpoint, freq: str, curr_date: str
) -> pd.DataFrame:
    """Fetch and transpose a Tushare financial-statement endpoint to match
    yfinance's schema (fields as rows, fiscal periods as columns).

    Tushare returns one row per fiscal period with an ``end_date`` (YYYYMMDD)
    and ``ann_date``; we transpose so periods become columns, then drop
    metadata rows (``ts_code`` / ``ann_date`` / ``update_flag``). When
    ``freq='annual'``, only December year-ends are kept. Restated periods
    (duplicate ``end_date`` with different ``update_flag``) are de-duplicated
    keeping the most recent amendment.
    """
    try:
        df = _tushare_retry(lambda: endpoint(ts_code=ts_code))
    except Exception as e:
        raise _classify_tushare_error(e) from e

    if df is None or df.empty:
        return pd.DataFrame()

    # Filter by frequency: annual = December year-ends only; quarterly = all.
    if freq.lower() == "annual" and "end_date" in df.columns:
        df = df[df["end_date"].astype(str).str.endswith("1231")]

    # Sort by period end descending (most recent first) and dedupe restated
    # reports — keep the first row per end_date (latest update_flag after sort).
    if "end_date" in df.columns:
        df = df.sort_values("end_date", ascending=False)
        df = df.drop_duplicates(subset=["end_date"], keep="first")

    # Transpose: periods become columns, fields become rows.
    df_t = df.set_index("end_date").T
    # Convert YYYYMMDD column headers to Timestamps so
    # filter_financials_by_date can compare them against curr_date.
    df_t.columns = pd.to_datetime(df_t.columns, format="%Y%m%d", errors="coerce")
    # Drop metadata rows (ts_code / ann_date / update_flag etc.) that Tushare
    # mixes into the statement; only financial fields should remain.
    df_t = df_t.drop(index=[r for r in _FINANCIAL_METADATA_FIELDS if r in df_t.index])
    return df_t


def get_balance_sheet(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get A-share balance sheet from Tushare, transposed to yfinance schema."""
    if _detect_market(ticker) is None:
        raise NoMarketDataError(ticker, ticker, "Tushare only serves A-shares")

    ts_code = _to_tushare_ts_code(ticker)
    pro = _get_tushare_pro()

    try:
        data = _fetch_financial_statements(pro, ts_code, pro.balancesheet, freq, curr_date)
        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            raise NoMarketDataError(ticker, ts_code, "no balance sheet data")

        csv_string = data.to_csv()
        header = f"# Balance Sheet data for {ts_code} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return header + csv_string
    except NoMarketDataError:
        raise
    except TushareRateLimitError:
        raise
    except Exception as e:
        return f"Error retrieving balance sheet for {ticker}: {str(e)}"


def get_cashflow(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get A-share cash flow from Tushare, transposed to yfinance schema."""
    if _detect_market(ticker) is None:
        raise NoMarketDataError(ticker, ticker, "Tushare only serves A-shares")

    ts_code = _to_tushare_ts_code(ticker)
    pro = _get_tushare_pro()

    try:
        data = _fetch_financial_statements(pro, ts_code, pro.cashflow, freq, curr_date)
        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            raise NoMarketDataError(ticker, ts_code, "no cash flow data")

        csv_string = data.to_csv()
        header = f"# Cash Flow data for {ts_code} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return header + csv_string
    except NoMarketDataError:
        raise
    except TushareRateLimitError:
        raise
    except Exception as e:
        return f"Error retrieving cash flow for {ticker}: {str(e)}"


def get_income_statement(
    ticker: Annotated[str, "ticker symbol of the company"],
    freq: Annotated[str, "frequency of data: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get A-share income statement from Tushare, transposed to yfinance schema."""
    if _detect_market(ticker) is None:
        raise NoMarketDataError(ticker, ticker, "Tushare only serves A-shares")

    ts_code = _to_tushare_ts_code(ticker)
    pro = _get_tushare_pro()

    try:
        data = _fetch_financial_statements(pro, ts_code, pro.income, freq, curr_date)
        data = filter_financials_by_date(data, curr_date)

        if data.empty:
            raise NoMarketDataError(ticker, ts_code, "no income statement data")

        csv_string = data.to_csv()
        header = f"# Income Statement data for {ts_code} ({freq})\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        return header + csv_string
    except NoMarketDataError:
        raise
    except TushareRateLimitError:
        raise
    except Exception as e:
        return f"Error retrieving income statement for {ticker}: {str(e)}"
