from datetime import datetime
from io import StringIO
import pandas as pd

from .alpha_vantage_common import _filter_csv_by_date_range, _make_api_request
from .errors import NoMarketDataError


def get_stock(
    symbol: str,
    start_date: str,
    end_date: str
) -> str:
    """
    Returns raw daily OHLCV values, adjusted close values, and historical split/dividend events
    filtered to the specified date range.

    Args:
        symbol: The name of the equity. For example: symbol=IBM
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        CSV string containing the daily adjusted time series data filtered to the date range.
    """
    # Parse dates to determine the range
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    today = datetime.now()

    # Choose outputsize based on whether the requested range is within the latest 100 days
    # Compact returns latest 100 data points, so check if start_date is recent enough
    days_from_today_to_start = (today - start_dt).days
    outputsize = "compact" if days_from_today_to_start < 100 else "full"

    params = {
        "symbol": symbol,
        "outputsize": outputsize,
        "datatype": "csv",
    }

    response = _make_api_request("TIME_SERIES_DAILY_ADJUSTED", params)

    return _filter_csv_by_date_range(response, start_date, end_date)


def _load_ohlcv_alpha_vantage(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV as a DataFrame via Alpha Vantage, filtered to ``<= curr_date``.

    Mirrors ``stockstats_utils.load_ohlcv`` (yfinance) and
    ``a_stock._load_ohlcv_astock`` (mootdx): a 5-year window ending at
    ``curr_date``, returned as a DataFrame with columns
    ``Date, Open, High, Low, Close, Volume``. ``Close`` uses the adjusted close
    so it is consistent with yfinance's ``auto_adjust=True`` and A-share
    forward-adjusted prices.

    Raises ``NoMarketDataError`` when no rows are available, and lets
    ``AlphaVantageRateLimitError`` / ``AlphaVantageNotConfiguredError`` (both
    ``VendorError`` subclasses) propagate so the routed loader can fall back.
    """
    # 5-year window matches yfinance's ``load_ohlcv`` so indicator look-back
    # (e.g. 200 SMA) has enough history.
    start_dt = pd.to_datetime(curr_date) - pd.DateOffset(years=5)
    start_date = start_dt.strftime("%Y-%m-%d")

    csv_text = get_stock(symbol, start_date, curr_date)
    if not csv_text or not csv_text.strip():
        raise NoMarketDataError(symbol, symbol, "Alpha Vantage returned no rows")

    df = pd.read_csv(StringIO(csv_text))

    # TIME_SERIES_DAILY_ADJUSTED columns: timestamp, open, high, low, close,
    # adjusted_close, volume, dividend_amount, split_coefficient.
    rename_map = {
        "timestamp": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "adjusted_close": "Close",  # adjusted, consistent with yfinance auto_adjust
        "volume": "Volume",
    }
    df = df.rename(columns=rename_map)
    keep = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep]

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])
    cutoff = pd.to_datetime(curr_date)
    df = df[df["Date"] <= cutoff].sort_values("Date").reset_index(drop=True)
    if df.empty:
        raise NoMarketDataError(
            symbol, symbol, "Alpha Vantage returned no rows on or before curr_date"
        )
    return df
