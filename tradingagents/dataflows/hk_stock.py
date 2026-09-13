"""Hong Kong stock data vendor for TradingAgents.

Lightweight module providing HK-stock news via Eastmoney's search API, which
fully covers HK-listed companies (e.g. 00700 / Tencent). OHLCV / indicators /
fundamentals / financial statements are served by yfinance (already configured
in ``market_vendors.hk``), so this module only implements the news category
where yfinance is unreliable (curl timeouts / Yahoo Finance regional blocks).

Data sources (all direct HTTP, keyless):
  - Eastmoney search API (``search-api-web.eastmoney.com``): individual stock
    news, searched by HK code (e.g. "00700") or company name.
  - CLS wire (财联社) + Eastmoney 7x24 (东财快讯): global market news, reused
    from a_stock (naturally covers HK market as part of global coverage).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from .a_stock import _fetch_news_eastmoney
from .errors import NoMarketDataError

logger = logging.getLogger(__name__)


def _normalize_hk_ticker(symbol: str) -> str:
    """Strip ``.HK`` suffix, return the bare HK code (4-5 digits).

    Handles: '0700.HK', '00700.HK', '0700'. Unlike A-share codes, HK codes can
    be 4 or 5 digits and may have leading zeros that must be preserved.
    """
    s = symbol.strip().upper()
    for suffix in (".HK",):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


def get_news(
    ticker: Annotated[str, "HK stock code (e.g. 0700.HK or 00700)"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get HK stock-specific news via Eastmoney search API.

    Searches Eastmoney's article index by the HK code (e.g. "00700") which
    returns Chinese-language financial news about the company. Falls back to
    raising ``NoMarketDataError`` when the source fails, so ``route_to_vendor``
    can try the next vendor (yfinance).

    Raises NoMarketDataError when the source fails to respond. Returns a
    "no news in range" string when the source responds but no articles match
    the date window (legitimate sparseness).
    """
    code = _normalize_hk_ticker(ticker)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    try:
        articles = _fetch_news_eastmoney(code)
    except Exception as e:
        logger.warning("Eastmoney news fetch failed for HK %s: %s", code, e)
        raise NoMarketDataError(
            ticker, code, f"eastmoney news source failed for HK '{code}': {e}"
        ) from e

    if not articles:
        return f"No news found for HK stock '{code}'"

    news_str = ""
    count = 0
    for art in articles:
        pub_time = art.get("time", "")
        try:
            pub_dt = datetime.strptime(pub_time[:10], "%Y-%m-%d")
            if pub_dt < start_dt or pub_dt > end_dt:
                continue
        except (ValueError, IndexError):
            pass

        title = art["title"]
        content = art.get("content", "")
        source = art.get("source", "东方财富")
        link = art.get("url", "")

        news_str += f"### {title} (source: {source})\n"
        if content:
            snippet = content[:300] + "..." if len(content) > 300 else content
            news_str += f"{snippet}\n"
        if link and link != "nan":
            news_str += f"Link: {link}\n"
        news_str += "\n"
        count += 1

    if count == 0:
        return f"No news found for HK stock '{code}' between {start_date} and {end_date}"

    return f"## {code} (HK) News, from {start_date} to {end_date}:\n\n" + news_str


def get_global_news(
    curr_date: Annotated[str, "Current date yyyy-mm-dd"],
    look_back_days: Annotated[int | None, "Days to look back; None = config default"] = None,
    limit: Annotated[int | None, "Max articles; None = config default"] = None,
) -> str:
    """Get global/HK market news via CLS + Eastmoney 7x24 (direct HTTP).

    Delegates to ``a_stock.get_global_news`` — the CLS wire and Eastmoney 7x24
    fast-news feeds are general Chinese financial news that naturally cover the
    HK market (HK-listed companies, Hang Seng Index, southbound capital flow,
    etc.). No HK-specific source is needed for global news.
    """
    from .a_stock import get_global_news as _astock_global_news

    return _astock_global_news(curr_date, look_back_days, limit)
