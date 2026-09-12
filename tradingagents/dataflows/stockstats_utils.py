import logging
import os
import time
from typing import Annotated

import pandas as pd
import yfinance as yf
from stockstats import wrap
from yfinance.exceptions import YFRateLimitError

from .config import get_config
from .errors import VendorNotConfiguredError, VendorRateLimitError
from .symbol_utils import NoMarketDataError, normalize_symbol
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

# A vendor's latest OHLCV row this many calendar days before the requested date
# is treated as stale. Generous enough to span long holiday weekends, tight
# enough to catch the year-old frames yfinance occasionally returns (#1021).
MAX_OHLCV_STALE_DAYS = 10

# How long a same-day cache that does not yet reach the requested day may be
# reused before it is refetched (#1150). Short enough that an intraday run picks
# up today's close soon after it publishes, long enough that a day with no bar
# at all (weekend, holiday) cannot trigger a download on every call.
OHLCV_CACHE_TTL_SECONDS = 900


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. When retries are exhausted the YFRateLimitError is
    converted to VendorRateLimitError so route_to_vendor falls back to
    the next vendor — yfinance's own exception type is not a VendorError
    and would otherwise bypass the rate-limit fallback path. Other
    exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError as e:
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(delay)
            else:
                raise VendorRateLimitError(
                    f"yfinance rate limited after {max_retries} retries"
                ) from e


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize the date column to ``Date``.

    Some yfinance builds leave the index unnamed (so ``reset_index()`` yields
    ``index``) or use ``Datetime`` for intraday data. Rename the first
    date-like column so indicators don't silently drop when it isn't ``Date``.
    """
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _local_midnight(value) -> pd.Timestamp:
    """A single timestamp as its naive, midnight-normalized local date (or NaT)."""
    if pd.isna(value):
        return pd.NaT
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return pd.NaT
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)  # drop tz, keep the local wall-clock date
    return ts.normalize()


def _normalize_dates(dates) -> pd.Series:
    """Parse to naive, midnight-normalized dates so tz-aware or intraday
    timestamps compare correctly against the naive ``curr_date`` cutoff (#1201).

    Normalized per element: 5 years of yfinance bars span daylight-saving
    changes (and cache CSVs round-trip the offsets as strings), so the series can
    carry mixed UTC offsets that ``pd.to_datetime`` cannot unify without
    ``utc=True`` — which would shift non-US (positive-offset) markets to the
    previous day. Keeping each bar's own local date avoids both.
    """
    return pd.to_datetime(pd.Series(dates).map(_local_midnight))


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse/normalize dates and
    coerce prices to numeric (NaN where invalid). Dropping incomplete rows and
    filling gaps is left to ``_fill_price_gaps`` so the caller can first inspect
    the latest in-range bar (#1201)."""
    data = _ensure_date_column(data)
    data["Date"] = _normalize_dates(data["Date"])
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    return data


def _fill_price_gaps(data: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with no close and forward/back-fill remaining price gaps so
    indicators compute on a continuous series."""
    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    # copy() so a filtered (sliced) input is written to safely, not via a view.
    data = data.dropna(subset=["Close"]).copy()
    data[price_cols] = data[price_cols].ffill().bfill()
    return data


def _coerce_ohlcv_dates(data: pd.DataFrame) -> pd.Series:
    """Return parsed dates from an OHLCV frame, whether Date is a column or the index."""
    if "Date" in data.columns:
        return pd.to_datetime(data["Date"], errors="coerce").dropna()
    # yfinance keeps the dates in the index (a DatetimeIndex, sometimes unnamed).
    if isinstance(data.index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(data.index, errors="coerce")).dropna()
    # Fallback: expose the index and look for any date-like column.
    df = data.reset_index()
    for col in ("Date", "Datetime", "date", "index"):
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if not parsed.empty:
                return parsed
    return pd.Series(dtype="datetime64[ns]")


def _assert_ohlcv_not_stale(
    data: pd.DataFrame,
    curr_date: str,
    symbol: str,
    canonical: str | None = None,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,
) -> None:
    """Reject OHLCV whose latest row is far older than curr_date.

    Raises NoMarketDataError (with a stale-specific detail) so the router treats
    it like any other "no usable data from this vendor" — try the next vendor,
    then emit one clear unavailable signal. Empty frames are left to the
    caller's existing no-data handling; this guards only the dangerous case of
    present-but-stale rows (a vendor returning a year-old frame that would
    otherwise feed wrong prices to the agent, #1021).
    """
    if data is None or data.empty:
        return
    requested = pd.to_datetime(curr_date, errors="coerce")
    if pd.isna(requested):
        return
    requested = requested.normalize()
    dates = _coerce_ohlcv_dates(data)
    if dates.empty:
        return
    latest = dates.max().normalize()
    stale_days = (requested - latest).days
    if stale_days > max_stale_days:
        raise NoMarketDataError(
            symbol,
            canonical,
            f"latest row is {latest.date()}, {stale_days} days before the "
            f"requested {requested.date()} (stale) — refusing to use it",
        )


def _needs_same_day_refresh(data_file, curr_date_dt, today_date) -> bool:
    """Whether a cached frame must be refetched to reflect the requested day.

    The cache file is keyed per day, so without this a run started before the
    day's bar was final keeps serving that snapshot to every later run (#1150).
    Two distinct staleness cases exist for a current-day request: the bar may be
    missing entirely, or present but still in progress — Yahoo publishes a
    partial daily candle during market hours, whose ``Close`` is not the closing
    price. Row inspection cannot tell a partial bar from a final one, so the TTL
    governs every current-day cache. Historical requests always reuse the cache,
    since those rows are immutable.
    """
    if curr_date_dt.date() < today_date.date():
        return False
    return time.time() - os.path.getmtime(data_file) > OHLCV_CACHE_TTL_SECONDS


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 5 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.
    """
    # Resolve broker/forex symbols (XAUUSD+ -> GC=F) to Yahoo's convention,
    # then reject values that would escape the cache directory when
    # interpolated into the cache filename (e.g. ``../../tmp/x``).
    canonical = normalize_symbol(symbol)
    safe_symbol = safe_ticker_component(canonical)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date).normalize()

    # Cache uses a fixed window (5y to today) so one file per symbol.
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    # yfinance ``end`` is EXCLUSIVE; request tomorrow so today's row is included
    # when curr_date is the current day (#986). Look-ahead is still prevented by
    # the curr_date filter below.
    end_str = (today_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    # A cached file may be empty if a prior fetch failed (unknown symbol,
    # transient rate limit). Treat an empty/columnless cache as a miss and
    # re-fetch rather than serving the poisoned file forever.
    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        # Serve the cache only when it is usable and not a stale snapshot of the
        # day being requested (#1150); otherwise fall through and refetch.
        if (
            not cached.empty
            and "Close" in cached.columns
            and not _needs_same_day_refresh(data_file, curr_date_dt, today_date)
        ):
            data = cached

    if data is None:
        try:
            downloaded = yf_retry(
                lambda: yf.download(
                    canonical,
                    start=start_str,
                    end=end_str,
                    multi_level_index=False,
                    progress=False,
                    auto_adjust=True,
                )
            )
            downloaded = _ensure_date_column(downloaded.reset_index())
        except Exception as fetch_exc:
            # The refetch failed (network/rate-limit/yfinance outage). If a
            # cached file exists from a prior successful fetch, serve it rather
            # than crashing the run — stale-but-present is better than absent,
            # and the staleness guard below still rejects truly dangerous frames.
            if os.path.exists(data_file):
                cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
                if not cached.empty and "Close" in cached.columns:
                    logger.warning(
                        "yfinance refetch failed for %s (%s); serving cached "
                        "data (latest row may be stale).",
                        canonical,
                        fetch_exc,
                    )
                    downloaded = cached
                else:
                    raise NoMarketDataError(
                        symbol,
                        canonical,
                        f"Yahoo Finance returned no rows and cache is empty/invalid "
                        f"(fetch error: {fetch_exc})",
                    ) from fetch_exc
            else:
                raise NoMarketDataError(
                    symbol,
                    canonical,
                    f"Yahoo Finance returned no rows (fetch error: {fetch_exc})",
                ) from fetch_exc
        # Only cache real data — never persist an empty frame.
        if not downloaded.empty and "Close" in downloaded.columns:
            downloaded.to_csv(data_file, index=False, encoding="utf-8")
            data = downloaded
        else:
            # Download returned empty; fall back to cache if available.
            if os.path.exists(data_file):
                cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
                if not cached.empty and "Close" in cached.columns:
                    logger.warning(
                        "yfinance returned empty for %s; serving cached data "
                        "(latest row may be stale).",
                        canonical,
                    )
                    data = cached
                else:
                    raise NoMarketDataError(symbol, canonical, "Yahoo Finance returned no rows")
            else:
                raise NoMarketDataError(symbol, canonical, "Yahoo Finance returned no rows")

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting.
    data = data[data["Date"] <= curr_date_dt]

    # Guard the latest in-range bar before dropping incomplete rows: a newest bar
    # with no close is "not settled yet", not "does not exist". Silently dropping
    # it would make the previous trading day look like the latest (#1201); raise
    # instead so the router surfaces it rather than fabricating a fallback.
    if not data.empty and pd.isna(data["Close"].iloc[-1]):
        raise NoMarketDataError(symbol, canonical, "latest in-range OHLCV bar has no closing price")

    data = _fill_price_gaps(data)

    # Reject a stale frame (latest row far older than curr_date) rather than
    # feeding year-old prices into indicators (#1021).
    _assert_ohlcv_not_stale(data, curr_date, symbol, canonical)

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


def _load_ohlcv_for_vendor(vendor: str, symbol: str, curr_date: str) -> pd.DataFrame:
    """Dispatch to a vendor's raw OHLCV DataFrame loader.

    Lazy-imports non-yfinance vendors to avoid circular imports
    (``stockstats_utils`` -> ``interface`` -> ``y_finance`` ->
    ``stockstats_utils``). Each loader returns a DataFrame with columns
    ``Date, Open, High, Low, Close, Volume`` filtered to ``<= curr_date``.
    """
    if vendor == "yfinance":
        return load_ohlcv(symbol, curr_date)
    if vendor == "a_stock":
        from .a_stock import _load_ohlcv_astock

        return _load_ohlcv_astock(symbol, curr_date)
    if vendor == "alpha_vantage":
        from .alpha_vantage_stock import _load_ohlcv_alpha_vantage

        return _load_ohlcv_alpha_vantage(symbol, curr_date)
    raise ValueError(f"No raw OHLCV loader for vendor {vendor!r}")


# Vendors with raw DataFrame OHLCV loaders. Order mirrors VENDOR_METHODS so
# the "default" sentinel expansion matches route_to_vendor's behavior. Must
# stay in sync with ``_load_ohlcv_for_vendor``.
_RAW_OHLCV_VENDORS: tuple[str, ...] = ("alpha_vantage", "yfinance", "a_stock")


def load_ohlcv_routed(symbol: str, curr_date: str) -> pd.DataFrame:
    """Config-driven, market-aware OHLCV loader with vendor fallback.

    Selects the vendor chain the same way ``route_to_vendor`` does for
    ``get_stock_data`` — reading ``analysis_market_var`` (set by the graph from
    the analyzed ticker) and then ``market_vendors[market][core_stock_apis]``
    (or a ``tool_vendors`` override) — so the verified-market-snapshot path and
    the market analyst's ``get_stock_data`` use the same vendors, including
    fallback. Outside a graph run (no ContextVar set), the market is inferred
    from the symbol so a standalone CN-symbol snapshot still routes to a_stock.
    Vendors are tried in configured order; on ``NoMarketDataError``,
    ``VendorRateLimitError``, ``VendorNotConfiguredError``, or any other
    ``Exception`` the next vendor is tried, mirroring ``route_to_vendor``'s
    error handling.
    """
    # Lazy import: interface -> y_finance -> stockstats_utils would cycle.
    from .config import analysis_market_var
    from .interface import get_vendor
    from .symbol_utils import classify_market

    # Within a graph run, use the run's market (set from the analyzed ticker
    # via analysis_market_var) so this path matches route_to_vendor's market
    # selection exactly. Outside a run (standalone snapshot), fall back to
    # inferring from the symbol so a CN symbol still routes to a_stock.
    market = analysis_market_var.get() or classify_market(symbol)
    vendor_config = get_vendor("core_stock_apis", method="get_stock_data", market=market)
    configured = [v.strip() for v in vendor_config.split(",") if v.strip()]

    # Resolve the chain: explicit vendors are used as-is (skipping any that
    # lack a raw loader); the "default" sentinel expands to all raw loaders.
    if configured and "default" not in [v.lower() for v in configured]:
        vendor_chain = configured
    else:
        vendor_chain = list(_RAW_OHLCV_VENDORS)

    last_no_data: NoMarketDataError | None = None
    first_error: Exception | None = None
    for vendor in vendor_chain:
        if vendor not in _RAW_OHLCV_VENDORS:
            logger.warning("No raw OHLCV loader for vendor %r; skipping.", vendor)
            continue
        try:
            return _load_ohlcv_for_vendor(vendor, symbol, curr_date)
        except NoMarketDataError as e:
            last_no_data = e
            continue
        except (VendorRateLimitError, VendorNotConfiguredError) as e:
            logger.warning(
                "Vendor %r unavailable for OHLCV %s; trying next vendor.",
                vendor,
                symbol,
            )
            if first_error is None:
                first_error = e
            continue
        except Exception as e:
            # Mirror route_to_vendor: don't let one vendor's failure crash the
            # call when another can serve it, but never swallow silently.
            logger.warning("Vendor %r failed for OHLCV %s: %s", vendor, symbol, e)
            if first_error is None:
                first_error = e
            continue

    if last_no_data is not None:
        raise last_no_data
    if first_error is not None:
        raise first_error
    raise NoMarketDataError(symbol, symbol, "no OHLCV vendor available")


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[str, "curr date for retrieving stock price data, YYYY-mm-dd"],
    ):
        data = load_ohlcv_routed(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
