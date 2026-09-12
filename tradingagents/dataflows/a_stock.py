"""A-stock (China mainland) data vendor for TradingAgents.

Zero third-party data dependency (no akshare/tushare). All sources are direct
HTTP APIs or mootdx TCP. Ported from the TradingAgents-astock project, with
the error contract adapted to this fork's vendor-routing layer: methods raise
``NoMarketDataError`` (from ``.errors``) when data is genuinely unavailable so
``route_to_vendor`` can fall back through the configured chain or emit a
unified ``NO_DATA_AVAILABLE`` sentinel, rather than returning free-text error
strings that would leak into the agent's data channel.

Data sources:
- mootdx (TCP 7709): OHLCV K-lines, financial snapshots, F10 text
- Tencent Finance (HTTP GBK): PE/PB/market cap/turnover
- 东方财富 push2 / datacenter-web (direct HTTP): stock info, dragon-tiger, lockup
- 新浪财经 (direct HTTP): K-line fallback, financial statements
- 同花顺 (direct HTTP): consensus EPS, hot stocks, northbound capital flow
- 财联社 (direct HTTP): global news wire
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
import math
import os
import random
import re as _re
import socket
import threading
import time
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

import pandas as pd
import requests as _requests
from dateutil.relativedelta import relativedelta

from .errors import NoMarketDataError
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: ticker format & market detection
# ---------------------------------------------------------------------------


def _get_prefix(code: str) -> str:
    """6-digit A-stock code -> market prefix for Tencent API.

    The 92 prefix must be checked before the leading-9 rule: the Beijing Stock
    Exchange started issuing 920xxx codes for new listings in October 2024, and
    a bare ``startswith("9")`` routes them to Shanghai, where the Tencent quote
    endpoint returns an empty payload.  Only 900xxx (Shanghai B shares)
    legitimately belongs to ``sh``.
    """
    if code.startswith("92"):
        return "bj"
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


def _reject_non_a_share(original: str, code: str) -> None:
    """Reject HK/US tickers at the A-share data layer instead of querying A-share
    sources with them. A-share codes are always 6 digits; HK is 4-5 digits or
    carries ``.HK``, US is letters. These sources return empty/zombie quotes
    for non-existent codes rather than erroring, so the model would silently
    write a report from the wrong market's data.

    Raises ``NoMarketDataError`` (not ``ValueError``) so ``route_to_vendor``
    treats it as "this vendor can't serve this symbol" — the router emits its
    ``NO_DATA_AVAILABLE`` sentinel or falls back to the next vendor, instead of
    surfacing a raw traceback.
    """
    if code.isdigit() and len(code) == 6:
        return
    upper = original.strip().upper()
    if upper.endswith(".HK") or (code.isdigit() and len(code) in (4, 5)):
        raise NoMarketDataError(
            original,
            code,
            f"'{original}' is a Hong Kong ticker. This data layer only supports "
            f"A-shares (6-digit codes, e.g. 600519 / 000001).",
        )
    if code and not code.isdigit():
        raise NoMarketDataError(
            original,
            code,
            f"'{original}' is not an A-share ticker. This data layer only "
            f"supports 6-digit A-share codes (e.g. 600519).",
        )
    raise NoMarketDataError(
        original,
        code,
        f"'{original}' is not a valid A-share code: A-share codes are always "
        f"6 digits (e.g. 600519); parsed '{code}'.",
    )


def _normalize_ticker(symbol: str) -> str:
    """Strip exchange prefix/suffix, return pure 6-digit code.

    Handles: '688017', 'SH688017', '688017.SH', 'sh688017'. Non-A-share codes
    (HK '00700' / '0700.HK', US 'AAPL') raise.
    """
    s = symbol.strip().upper()
    # Remove .SH / .SZ / .BJ / .SS suffix (.SS is Yahoo's Shanghai form)
    for suffix in (".SH", ".SZ", ".BJ", ".SS"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    # Remove SH / SZ / BJ prefix
    for prefix in ("SH", "SZ", "BJ"):
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    code = safe_ticker_component(s)
    _reject_non_a_share(symbol, code)
    return code


# ---------------------------------------------------------------------------
# Stock name <-> code mapping (cached)
# ---------------------------------------------------------------------------

_name_to_code: dict[str, str] | None = None
_code_to_name: dict[str, str] | None = None


def _build_name_code_map() -> tuple[dict[str, str], dict[str, str]]:
    """Build name→code and code→name maps via mootdx (both SH & SZ markets)."""
    global _name_to_code, _code_to_name
    if _name_to_code is not None:
        return _name_to_code, _code_to_name

    n2c: dict[str, str] = {}
    c2n: dict[str, str] = {}

    try:
        for market in (0, 1):  # 0=SZ, 1=SH
            stocks = _mootdx_call("stocks", market=market)
            if stocks is None or stocks.empty:
                continue
            for _, row in stocks.iterrows():
                code = str(row["code"]).strip()
                name = str(row["name"]).strip()
                if not _re.match(r"^[036]\d{5}$", code):
                    continue
                clean_name = name.replace(" ", "").replace("　", "")
                n2c[clean_name] = code
                c2n[code] = clean_name
    except Exception as e:
        raise ValueError(
            "Could not resolve stock name via mootdx (TDX service unreachable): "
            f"{e}. Retry later, or pass a 6-digit stock code directly."
        ) from e

    _name_to_code = n2c
    _code_to_name = c2n
    logger.info("Built stock name-code map: %d entries", len(n2c))
    return _name_to_code, _code_to_name


def resolve_ticker(user_input: str) -> str:
    """Resolve user input (code or Chinese name) to a 6-digit A-stock code.

    Accepts: '600379', 'SH600379', '600379.SH', '宝光股份'. Returns: '600379'.
    Raises: ValueError if not resolvable.
    """
    s = user_input.strip()
    if not s:
        raise ValueError("input cannot be empty")

    has_chinese = any("一" <= ch <= "鿿" for ch in s)

    if not has_chinese:
        try:
            return _normalize_ticker(s)
        except NoMarketDataError as e:
            # _normalize_ticker raises NoMarketDataError for wrong-market
            # symbols (so the routing layer can fall back), but resolve_ticker
            # is a user-facing API documented to raise ValueError.
            raise ValueError(str(e)) from e

    clean = s.replace(" ", "").replace("　", "")
    n2c, _ = _build_name_code_map()

    if clean in n2c:
        return n2c[clean]

    matches = {name: code for name, code in n2c.items() if clean in name}
    if len(matches) == 1:
        return next(iter(matches.values()))
    if len(matches) > 1:
        examples = ", ".join(f"{n}({c})" for n, c in list(matches.items())[:5])
        raise ValueError(f"'{s}' matched multiple stocks: {examples}; pass the full name or code")

    raise ValueError(
        f"Could not find stock '{s}'. The ticker parameter only accepts 6-digit "
        f"stock codes (e.g. '600519') or full stock names (e.g. '贵州茅台'); "
        f"industry/concept/sector names are not valid stock identifiers."
    )


# ---------------------------------------------------------------------------
# Look-ahead (point-in-time) protection
# ---------------------------------------------------------------------------

# A-share market timezone. "Today" must be computed in market-local time, not
# host time — a host east of UTC+8 (e.g. UTC+13) sees a new calendar day while
# Shanghai is still on the previous one, making a current-day analysis look like
# a historical replay: realtime fund flow gets dropped and spurious look-ahead
# warnings fire.
_MARKET_TZ = timezone(timedelta(hours=8))


def _market_today() -> date:
    """A-share market current date (Asia/Shanghai), independent of host tz."""
    return datetime.now(_MARKET_TZ).date()


def _is_historical(curr_date) -> bool:
    """Whether the analysis date is before the market's today. If so, this is a
    historical replay and realtime data must not be presented as that day's fact.
    """
    if not curr_date:
        return False
    try:
        return datetime.strptime(str(curr_date)[:10], "%Y-%m-%d").date() < _market_today()
    except ValueError:
        return False


def _snapshot_notice(curr_date: str, what: str) -> str:
    """When a realtime snapshot is used on a historical date, say so explicitly.

    Some sources only provide "current" values (Tencent realtime quotes, THS
    current consensus) with no historical point-in-time version. Since it can't
    be backfilled, it must be stated — otherwise the model treats today's value
    as the analysis date's fact, a silent look-ahead that's invisible in reports.
    """
    return (
        f"⚠️ Look-ahead warning: the following {what} is a **realtime snapshot**,"
        f" not the value as of {curr_date}. This source provides no historical "
        f"point-in-time data. When replaying a historical date, do **not** treat "
        f"these numbers as facts known on {curr_date}, nor infer that day's "
        f"judgement from them.\n"
    )


# ---------------------------------------------------------------------------
# mootdx client (singleton)
# ---------------------------------------------------------------------------

_mootdx_client = None

# Known-good TDX candidate servers (latency-sorted, 2026-06 verified). Avoids
# mootdx 0.11.x fresh-install BESTIP.HQ being an empty string → ValueError.
_TDX_SERVERS = [
    ("119.97.185.59", 7709),
    ("124.70.133.119", 7709),
    ("116.205.183.150", 7709),
    ("123.60.73.44", 7709),
    ("116.205.163.254", 7709),
    ("121.36.225.169", 7709),
    ("123.60.70.228", 7709),
    ("124.71.9.153", 7709),
    ("110.41.147.114", 7709),
    ("124.71.187.122", 7709),
]

# Canary symbol for probing: a mainboard veteran any TDX server returns daily bars for.
_TDX_CANARY_SYMBOL = "600519"

# How long to skip re-probing after all servers fail. Without this negative
# cache, every fetch re-probes the whole table (10 × TCP timeout).
_MOOTDX_RETRY_AFTER_S = 300.0
_mootdx_unavailable_until = 0.0


def _candidate_tdx_servers() -> list[tuple[str, int]]:
    """Servers to try: the curated _TDX_SERVERS first, then mootdx's full host table."""
    servers = list(_TDX_SERVERS)
    seen = set(servers)
    try:
        from mootdx.consts import HQ_HOSTS

        for entry in HQ_HOSTS:
            host = (entry[1], entry[2]) if len(entry) >= 3 else None
            if host and host not in seen:
                seen.add(host)
                servers.append(host)
    except Exception as e:
        logger.debug("Failed to read mootdx HQ_HOSTS; using curated list only: %s", e)
    return servers


def _reachable_tdx_servers(servers, timeout: float = 2.0):
    """Concurrent TCP pre-filter, returning the connectable ones (order preserved)."""
    from concurrent.futures import ThreadPoolExecutor

    if not servers:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(servers))) as pool:
        flags = list(pool.map(lambda s: _probe_tdx(s[0], s[1], timeout), servers))
    return [srv for srv, ok in zip(servers, flags, strict=True) if ok]


def _probe_tdx(ip: str, port: int, timeout: float = 2.0) -> bool:
    """TCP handshake probe. ⚠️ A cheap pre-filter only — passing doesn't mean data
    works; many servers accept TCP then RST on the TDX handshake. Real selection
    must also run `_tdx_client_works()` (a real bar fetch).
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def _tdx_client_works(client) -> bool:
    """Fetch one K-line to verify this client actually returns data."""
    try:
        df = client.bars(symbol=_TDX_CANARY_SYMBOL, category=4, offset=1)
        return df is not None and not df.empty
    except Exception:
        return False


def reset_mootdx_client() -> None:
    """Discard the cached client so the next call re-selects a server.

    A singleton pinned to a server that later died will fail-and-degrade forever
    without re-selecting. Call this when a data fetch hits a mootdx error.
    """
    global _mootdx_client, _mootdx_unavailable_until
    _mootdx_client = None
    _mootdx_unavailable_until = 0.0


@contextlib.contextmanager
def _preserve_mootdx_bestip():
    """Protect mootdx's persisted server config during probing, restoring on exit.

    `StdQuotes.__init__` does `config.set('BESTIP', {'HQ': self.server})` — every
    client built with a server overwrites the persisted config. Probing 38
    candidates overwrites the user's config and leaves a dead server behind.

    Must `setup()` before snapshoting: in a fresh process `config.get("BESTIP")`
    returns the module default empty value; the user's persisted value is only
    loaded by `BaseQuotes.__init__` calling `setup()`. Snapshoting empty would
    "restore" the real config to empty — worse than not restoring.
    """
    saved = None
    try:
        from mootdx import config as _cfg

        _cfg.setup()
        saved = _cfg.get("BESTIP")
        if isinstance(saved, dict):
            saved = dict(saved)
    except Exception as e:
        logger.debug("Failed to read mootdx BESTIP; skipping protection: %s", e)

    keep = {"flag": False}
    try:
        yield lambda: keep.__setitem__("flag", True)
    finally:
        if saved is not None and not keep["flag"]:
            try:
                from mootdx import config as _cfg2

                _cfg2.set("BESTIP", saved)
            except Exception as e:
                logger.debug("Failed to restore mootdx BESTIP: %s", e)


def _get_mootdx_client():
    """Lazy-init robust mootdx Quotes client (TCP, reusable).

    Server selection order: curated table (TCP pre-filter + real fetch verify) →
    bare factory (user's existing config). Each stage must actually fetch data
    before adoption, to avoid pinning to a "port open but protocol dead" server.
    On total failure, raises RuntimeError and fast-fails within
    `_MOOTDX_RETRY_AFTER_S` rather than re-probing every call.
    """
    global _mootdx_client, _mootdx_unavailable_until
    if _mootdx_client is not None:
        return _mootdx_client

    now = time.time()
    if now < _mootdx_unavailable_until:
        raise RuntimeError(
            f"mootdx TDX servers temporarily unavailable (fast-failing for "
            f"{_mootdx_unavailable_until - now:.0f}s). All built-in servers were "
            f"probed: those with open ports failed TDX protocol data fetch. "
            f"Check network (proxy/firewall/corporate nets often block TCP 7709),"
            f" or query by 6-digit code directly."
        )

    from mootdx.quotes import Quotes

    tcp_ok_but_dead = 0
    with _preserve_mootdx_bestip() as keep_bestip:
        reachable = _reachable_tdx_servers(_candidate_tdx_servers())

        for ip, port in reachable:
            # "TCP open but TDX protocol dead" shows two ways: factory handshake
            # rejected, or built but no data. Both must count — only the latter
            # leaves the counter at 0 (these servers all ConnectionReset in
            # factory), breaking the fast-fail.
            try:
                candidate = Quotes.factory(market="std", server=(ip, port))
            except Exception as e:
                tcp_ok_but_dead += 1
                logger.debug(
                    "mootdx %s:%s handshake failed (%s), trying next", ip, port, type(e).__name__
                )
            else:
                if _tdx_client_works(candidate):
                    logger.info("mootdx server selected: %s:%s", ip, port)
                    keep_bestip()
                    _mootdx_client = candidate
                    return _mootdx_client
                tcp_ok_but_dead += 1
                logger.debug("mootdx %s:%s connected but no data, trying next", ip, port)

    # Bare factory reads the user's restored config.
    # ⚠️ Deliberately NOT bestip=True: it speed-tests the whole host table (minutes).
    try:
        candidate = Quotes.factory(market="std")
    except Exception as e:
        logger.debug("mootdx bare factory failed — %s", e)
    else:
        if _tdx_client_works(candidate):
            logger.info("mootdx client from bare factory (user config)")
            _mootdx_client = candidate
            return _mootdx_client

    _mootdx_unavailable_until = time.time() + _MOOTDX_RETRY_AFTER_S
    if tcp_ok_but_dead:
        cause = (
            f"{tcp_ok_but_dead} servers had open ports but rejected TDX protocol "
            f"handshake/fetch. This is usually protocol-layer blocking (proxy/"
            f"firewall/corporate TCP 7709 policy); switching servers won't help."
        )
    else:
        cause = "No built-in server's TCP 7709 was reachable; check connectivity."
    raise RuntimeError(
        f"mootdx TDX servers unavailable: {cause} Fast-failing for "
        f"{_MOOTDX_RETRY_AFTER_S:.0f}s. Query by 6-digit code directly as a fallback."
    )


def _mootdx_call(method: str, **kwargs):
    """Call a mootdx method; on failure, discard the current server.

    A selected server can die anytime; without discarding, the singleton points
    at it forever and every fetch fails-and-degrades without re-selection.
    Client-fetch failures don't clear the cache (negative-cached in _get_mootdx_client).
    """
    client = _get_mootdx_client()
    try:
        return getattr(client, method)(**kwargs)
    except Exception:
        reset_mootdx_client()
        raise


# ---------------------------------------------------------------------------
# Tencent Finance API
# ---------------------------------------------------------------------------


def _tencent_quote(codes: list[str]) -> dict[str, dict]:
    """Batch real-time quotes from Tencent Finance (qt.gtimg.cn).

    Returns dict[code] -> {name, price, pe_ttm, pb, mcap_yi, ...}
    """
    prefixed = [f"{_get_prefix(c)}{c}" for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=10)
    raw = resp.read().decode("gbk")

    result = {}
    for line in raw.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]  # strip sh/sz/bj prefix
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "mcap_yi": float(vals[44]) if vals[44] else 0,
            "float_mcap_yi": float(vals[45]) if vals[45] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "limit_up": float(vals[47]) if vals[47] else 0,
            "limit_down": float(vals[48]) if vals[48] else 0,
            "pe_static": float(vals[52]) if vals[52] else 0,
        }
    return result


# ---------------------------------------------------------------------------
# Eastmoney Datacenter unified helper
# ---------------------------------------------------------------------------

_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ---------------------------------------------------------------------------
# Eastmoney anti-ban: global throttle + Keep-Alive session reuse
# ---------------------------------------------------------------------------
# Eastmoney HTTP interfaces (push2 / push2his / datacenter-web / search-api /
# np-weblist) have rate controls: >5 req/s, ≥10 concurrent/IP, ≥200/min, ≥300/5min
# → temporary IP ban. Multi-agent batch analyses hit Eastmoney heavily. All
# eastmoney.com requests go through _em_get(): serial throttle (min interval +
# jitter) + Keep-Alive session + default UA. Only Eastmoney is throttled —
# mootdx(TCP) / Tencent / Sina / THS / CLS / Baidu are not.
_EM_SESSION = _requests.Session()
_EM_SESSION.headers.update({"User-Agent": _UA})
# Min interval between Eastmoney requests (s); batch scenarios can set
# EM_MIN_INTERVAL=1.5~2 to slow down further.
_EM_MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
_em_last_call = [0.0]  # module-level last Eastmoney request timestamp
# Serializes Eastmoney requests across threads. #1290 enabled concurrent graph
# runs in one process; without this lock two threads could both pass the
# interval check and fire simultaneously, defeating the throttle and risking
# the IP ban it exists to prevent.
_EM_LOCK = threading.Lock()


def _em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """Eastmoney unified request entry: auto-throttle + session reuse + default UA.

    All eastmoney.com interfaces should go through this to avoid IP bans under
    multi-agent high-frequency fetching. Serial throttle: if the gap since the
    last Eastmoney request < _EM_MIN_INTERVAL, sleep to fill it + 0.1~0.5s
    jitter. The lock is held during the throttle check + sleep so concurrent
    threads serialize rather than all passing the interval check at once.
    """
    with _EM_LOCK:
        wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        _em_last_call[0] = time.time()
    try:
        return _EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        with _EM_LOCK:
            _em_last_call[0] = time.time()


def _eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """Eastmoney datacenter unified query — shared by dragon-tiger / lockup."""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    r = _em_get(_DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ---------------------------------------------------------------------------
# THS EPS forecast helper (direct HTTP, no akshare)
# ---------------------------------------------------------------------------


def _ths_eps_forecast(code: str) -> pd.DataFrame:
    """Fetch consensus EPS forecast from 同花顺 (direct HTTP).

    Returns DataFrame with columns roughly: 年度, 预测机构数, 最小值, 均值, 最大值.
    """
    url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
    headers = {
        "User-Agent": _UA,
        "Referer": "https://basic.10jqka.com.cn/",
    }
    r = _requests.get(url, headers=headers, timeout=15)
    r.encoding = "gbk"
    dfs = pd.read_html(r.text)
    for df in dfs:
        cols = [str(c) for c in df.columns]
        if any("每股收益" in c or "均值" in c for c in cols):
            return df
    return dfs[0] if dfs else pd.DataFrame()


# ---------------------------------------------------------------------------
# Sina K-line fallback helper (direct HTTP, no akshare)
# ---------------------------------------------------------------------------


def _sina_kline_fallback(code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """Fetch daily K-line from Sina HTTP API as mootdx fallback.

    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume.
    """
    prefix = _get_prefix(code)
    url = (
        "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    )
    params = {
        "symbol": f"{prefix}{code}",
        "scale": "240",  # daily
        "ma": "no",
        "datalen": "800",
    }
    r = _requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = _json.loads(r.text)

    if not data:
        return pd.DataFrame()

    rows = []
    for item in data:
        rows.append(
            {
                "Date": item["day"],
                "Open": float(item["open"]),
                "High": float(item["high"]),
                "Low": float(item["low"]),
                "Close": float(item["close"]),
                "Volume": int(item["volume"]),
            }
        )

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])

    if start_date:
        df = df[df["Date"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["Date"] <= pd.to_datetime(end_date)]

    return df


def _last_ohlcv_date(df: pd.DataFrame) -> pd.Timestamp | None:
    """Return the latest OHLCV Date in a normalized dataframe."""
    if df is None or df.empty or "Date" not in df.columns:
        return None
    dates = pd.to_datetime(df["Date"], errors="coerce")
    if dates.dropna().empty:
        return None
    return dates.max().normalize()


def _normalize_ohlcv_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize OHLCV Date values to daily granularity."""
    if df is None or df.empty or "Date" not in df.columns:
        return df
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    return df.dropna(subset=["Date"])


def _needs_sina_supplement(df: pd.DataFrame, target_date: str | None) -> bool:
    """True when mootdx/cache data is older than the requested cutoff date."""
    if not target_date:
        return False
    last_date = _last_ohlcv_date(df)
    if last_date is None:
        return True
    target = pd.to_datetime(target_date).normalize()
    return last_date < target


def _merge_ohlcv(primary: pd.DataFrame, supplement: pd.DataFrame) -> pd.DataFrame:
    """Merge OHLCV frames, preferring supplement rows on duplicate dates."""
    frames = [frame for frame in (primary, supplement) if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    combined = pd.concat(frames, ignore_index=True)
    combined = _normalize_ohlcv_dates(combined)
    combined = combined.drop_duplicates(subset=["Date"], keep="last")
    combined = combined.sort_values("Date").reset_index(drop=True)
    return combined


def _supplement_stale_ohlcv_with_sina(
    code: str,
    df: pd.DataFrame,
    target_date: str | None,
    start_date: str | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Use Sina daily K-line to fill dates missing from mootdx/cache data."""
    if not _needs_sina_supplement(df, target_date):
        return df, False
    try:
        sina_df = _sina_kline_fallback(code, start_date, target_date)
    except Exception as e:
        logger.warning("sina K-line supplement failed for %s: %s", code, e)
        return df, False
    if sina_df.empty:
        return df, False
    merged = _merge_ohlcv(df, sina_df)
    return merged, _last_ohlcv_date(merged) != _last_ohlcv_date(df)


# ---------------------------------------------------------------------------
# OHLCV loading with cache (mootdx -> CSV)
# ---------------------------------------------------------------------------


def _load_ohlcv_astock(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV via mootdx, cache to CSV, filter by curr_date.

    Mirrors stockstats_utils.load_ohlcv but uses mootdx instead of yfinance.
    Returns DataFrame with columns: Date, Open, High, Low, Close, Volume.

    Raises NoMarketDataError when no data can be obtained, so the routed loader
    can fall back to another vendor.
    """
    from .config import get_config

    code = _normalize_ticker(symbol)
    config = get_config()
    cache_dir = config.get("data_cache_dir", os.path.expanduser("~/.tradingagents/cache"))
    os.makedirs(cache_dir, exist_ok=True)

    cache_file = os.path.join(cache_dir, f"{code}-astock-daily.csv")

    if os.path.exists(cache_file):
        mtime = datetime.fromtimestamp(os.path.getmtime(cache_file), tz=_MARKET_TZ)
        if mtime.date() == _market_today():
            data = pd.read_csv(cache_file, on_bad_lines="skip", encoding="utf-8")
            data = _normalize_ohlcv_dates(data)
            data, supplemented = _supplement_stale_ohlcv_with_sina(
                code, data, curr_date, start_date=None
            )
            if supplemented:
                data.to_csv(cache_file, index=False, encoding="utf-8")
            cutoff = pd.to_datetime(curr_date)
            return data[data["Date"] <= cutoff]

    # Fetch from mootdx — 800 daily bars (~3 years of trading days)
    try:
        df = _mootdx_call("bars", symbol=code, category=4, offset=800)

        if df is None or df.empty:
            raise ValueError(f"No OHLCV data from mootdx for {code}")

        # mootdx returns an index named 'datetime' AND a column named 'datetime'
        # (plus year/month/day/hour/minute/volume). Drop duplicates before reset.
        df = df.drop(
            columns=["datetime", "year", "month", "day", "hour", "minute"], errors="ignore"
        )
        df = df.reset_index()  # moves index 'datetime' → column 'datetime'
        rename_map = {
            "datetime": "Date",
            "open": "Open",
            "close": "Close",
            "high": "High",
            "low": "Low",
            "volume": "Volume",
        }
        df = df.rename(columns=rename_map)
        df = df[["Date", "Open", "High", "Low", "Close", "Volume"]]
        df = _normalize_ohlcv_dates(df)
    except Exception as e:
        logger.warning("mootdx OHLCV failed for %s: %s, trying sina HTTP fallback", code, e)
        try:
            df = _sina_kline_fallback(code)
            if df.empty:
                raise NoMarketDataError(symbol, code, "no OHLCV from mootdx or sina")
        except NoMarketDataError:
            raise
        except Exception:
            raise NoMarketDataError(symbol, code, "no OHLCV from mootdx or sina") from None

    df, _ = _supplement_stale_ohlcv_with_sina(code, df, curr_date, start_date=None)

    df.to_csv(cache_file, index=False, encoding="utf-8")

    cutoff = pd.to_datetime(curr_date)
    return df[df["Date"] <= cutoff]


# ===========================================================================
# Vendor Methods (signatures match interface.py VENDOR_METHODS)
# ===========================================================================


# ---- 1. get_stock_data ----


def get_stock_data(
    symbol: Annotated[str, "A-stock code (e.g. 688017, SH688017)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV stock price data via mootdx (Sina HTTP fallback)."""
    code = _normalize_ticker(symbol)

    data_source = "mootdx (TCP)"
    try:
        df = _mootdx_call("bars", symbol=code, category=4, offset=800)

        if df is None or df.empty:
            raise ValueError(f"No data from mootdx for {code}")

        df = df.drop(
            columns=["datetime", "year", "month", "day", "hour", "minute"],
            errors="ignore",
        )
        df = df.reset_index()
        df = df.rename(
            columns={
                "datetime": "Date",
                "open": "Open",
                "close": "Close",
                "high": "High",
                "low": "Low",
                "volume": "Volume",
                "amount": "Amount",
            }
        )
        df = _normalize_ohlcv_dates(df)

    except Exception as e:
        logger.warning("mootdx K-line failed for %s: %s, trying sina HTTP fallback", code, e)
        try:
            df = _sina_kline_fallback(code, start_date, end_date)
            if df.empty:
                raise NoMarketDataError(symbol, code, "no OHLCV from mootdx or sina")
            data_source = "sina HTTP (fallback)"
        except NoMarketDataError:
            raise
        except Exception:
            raise NoMarketDataError(symbol, code, "no OHLCV from mootdx or sina") from None

    df, supplemented = _supplement_stale_ohlcv_with_sina(code, df, end_date, start_date)
    if supplemented:
        data_source = f"{data_source} + sina HTTP supplement"

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]

    if df.empty:
        raise NoMarketDataError(symbol, code, f"no OHLCV rows between {start_date} and {end_date}")

    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].round(2)

    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    csv_out = df[["Date", "Open", "High", "Low", "Close", "Volume"]].to_csv(index=False)

    header = f"# Stock data for {code} (A-stock) from {start_date} to {end_date}\n"
    header += f"# Total records: {len(df)}\n"
    header += f"# Data source: {data_source}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_out


# ---- 2. get_indicators ----

# Supported technical indicators with descriptions
_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: Medium-term trend indicator.",
    "close_200_sma": "200 SMA: Long-term trend benchmark.",
    "close_10_ema": "10 EMA: Responsive short-term average.",
    "macd": "MACD: Momentum via EMA differences.",
    "macds": "MACD Signal: EMA smoothing of MACD line.",
    "macdh": "MACD Histogram: Gap between MACD and signal.",
    "rsi": "RSI: Momentum overbought/oversold indicator (70/30 thresholds).",
    "boll": "Bollinger Middle: 20 SMA basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: 2 std devs above middle.",
    "boll_lb": "Bollinger Lower Band: 2 std devs below middle.",
    "atr": "ATR: Average True Range volatility measure.",
    "vwma": "VWMA: Volume-weighted moving average.",
    "mfi": "MFI: Money Flow Index (volume + price momentum).",
}


def get_indicators(
    symbol: Annotated[str, "A-stock code"],
    indicator: Annotated[str, "technical indicator (e.g. rsi, macd, close_50_sma)"],
    curr_date: Annotated[str, "Current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Get technical indicators using stockstats on mootdx OHLCV data."""
    from stockstats import wrap

    code = _normalize_ticker(symbol)

    if indicator not in _INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator {indicator} not supported. "
            f"Choose from: {list(_INDICATOR_DESCRIPTIONS.keys())}"
        )

    try:
        data = _load_ohlcv_astock(code, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats calculation

        ind_dict = {}
        for _, row in df.iterrows():
            d = row["Date"]
            v = row[indicator]
            ind_dict[d] = "N/A" if pd.isna(v) else str(round(float(v), 4))

        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        before = curr_dt - relativedelta(days=look_back_days)

        lines = []
        dt = curr_dt
        while dt >= before:
            ds = dt.strftime("%Y-%m-%d")
            val = ind_dict.get(ds, "N/A: Not a trading day (weekend or holiday)")
            lines.append(f"{ds}: {val}")
            dt -= relativedelta(days=1)

        result = (
            f"## {indicator} values for {code} "
            f"from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
            + "\n".join(lines)
            + "\n\n"
            + _INDICATOR_DESCRIPTIONS.get(indicator, "")
        )
        return result

    except NoMarketDataError:
        raise
    except Exception as e:
        logger.warning("indicator calc failed for %s: %s", code, e)
        raise NoMarketDataError(symbol, code, f"indicator {indicator} calc failed: {e}") from e


# ---- 3. get_fundamentals ----


def get_fundamentals(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Get company fundamentals from Tencent + mootdx + Eastmoney + 同花顺."""
    code = _normalize_ticker(ticker)

    try:
        lines = []
        # Tencent realtime quotes only have "current" PE/PB/market cap, no
        # historical point-in-time value. State it explicitly on historical dates.
        if _is_historical(curr_date):
            lines.append(_snapshot_notice(curr_date, "valuation & quote data"))

        # --- Tencent: real-time valuation ---
        try:
            tq = _tencent_quote([code])
            if code in tq:
                q = tq[code]
                lines.extend(
                    [
                        f"Name: {q['name']}",
                        f"Price: {q['price']}",
                        f"PE (TTM): {q['pe_ttm']}",
                        f"PE (Static): {q['pe_static']}",
                        f"PB: {q['pb']}",
                        f"Market Cap (100M CNY): {q['mcap_yi']}",
                        f"Float Market Cap (100M CNY): {q['float_mcap_yi']}",
                        f"Turnover Rate: {q['turnover_pct']}%",
                        f"Change: {q['change_pct']}%",
                        f"Limit Up: {q['limit_up']}",
                        f"Limit Down: {q['limit_down']}",
                    ]
                )
        except Exception as e:
            logger.warning("Tencent quote failed for %s: %s", code, e)

        # --- mootdx: financial snapshot (quarterly) ---
        try:
            fin = _mootdx_call("finance", symbol=code)
            if fin is not None and not (isinstance(fin, pd.DataFrame) and fin.empty):
                row = fin.iloc[0] if isinstance(fin, pd.DataFrame) else fin
                field_map = {
                    "eps": "EPS (Quarterly)",
                    "bvps": "Book Value Per Share",
                    "roe": "ROE (%)",
                    "profit": "Net Profit",
                    "income": "Revenue",
                    "liutongguben": "Float Shares",
                    "zongguben": "Total Shares",
                }
                idx = row.index if hasattr(row, "index") else []
                for field, label in field_map.items():
                    if field in idx:
                        val = row[field]
                        if val is not None and str(val) != "nan":
                            lines.append(f"{label}: {val}")
        except Exception as e:
            logger.warning("mootdx finance failed for %s: %s", code, e)

        # --- Eastmoney push2: basic stock info (direct HTTP) ---
        try:
            market_code = 1 if code.startswith("6") else 0
            _info_url = "https://push2.eastmoney.com/api/qt/stock/get"
            _info_params = {
                "fltt": "2",
                "invt": "2",
                "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
                "secid": f"{market_code}.{code}",
            }
            r = _em_get(_info_url, params=_info_params, timeout=10)
            d = r.json().get("data", {})
            if d:
                if d.get("f127"):
                    lines.append(f"行业: {d['f127']}")
                if d.get("f84"):
                    lines.append(f"总股本: {d['f84']}")
                if d.get("f85"):
                    lines.append(f"流通股本: {d['f85']}")
                if d.get("f116"):
                    lines.append(f"总市值: {d['f116']}")
                if d.get("f117"):
                    lines.append(f"流通市值: {d['f117']}")
                if d.get("f189"):
                    lines.append(f"上市日期: {d['f189']}")
        except Exception as e:
            logger.warning("eastmoney push2 stock info failed for %s: %s", code, e)

        # --- 同花顺 direct HTTP: consensus EPS forecast ---
        try:
            forecast_df = _ths_eps_forecast(code)
            if forecast_df is not None and not forecast_df.empty:
                lines.append("\n--- Consensus EPS Forecast (同花顺) ---")
                eps_by_year = {}
                for _, row in forecast_df.iterrows():
                    year = str(row.iloc[0]) if len(row) > 0 else ""
                    mean_eps_val = row.iloc[3] if len(row) > 3 else 0
                    count_val = row.iloc[1] if len(row) > 1 else 0
                    min_eps_val = row.iloc[2] if len(row) > 2 else "N/A"
                    max_eps_val = row.iloc[4] if len(row) > 4 else "N/A"
                    try:
                        mean_eps = float(mean_eps_val)
                    except (ValueError, TypeError):
                        mean_eps = 0
                    try:
                        count = int(count_val)
                    except (ValueError, TypeError):
                        count = 0
                    lines.append(
                        f"FY{year}: EPS={mean_eps} "
                        f"(range {min_eps_val}~{max_eps_val}, {count} analysts)"
                    )
                    if count < 3:
                        lines.append("  Warning: low coverage (<3 analysts)")
                    eps_by_year[year] = mean_eps

                # Forward PE / PEG / PE digestion
                try:
                    tq = _tencent_quote([code])
                    if code in tq:
                        price = tq[code]["price"]
                        years_sorted = sorted(eps_by_year.keys())
                        if years_sorted and eps_by_year.get(years_sorted[0], 0) > 0:
                            eps_cur = eps_by_year[years_sorted[0]]
                            fwd_pe = price / eps_cur
                            lines.append(
                                f"\nForward PE (FY{years_sorted[0]}): "
                                f"{fwd_pe:.1f}x (price={price}, EPS={eps_cur})"
                            )
                            if len(years_sorted) >= 2 and eps_by_year.get(years_sorted[1], 0) > 0:
                                eps_next = eps_by_year[years_sorted[1]]
                                cagr = eps_next / eps_cur - 1
                                if cagr > 0:
                                    peg = fwd_pe / (cagr * 100)
                                    lines.append(f"PEG: {peg:.2f} (EPS CAGR={cagr * 100:.0f}%)")
                                    if fwd_pe > 30:
                                        digest = math.log(fwd_pe / 30) / math.log(1 + cagr)
                                        lines.append(f"PE Digestion to 30x: {digest:.1f} years")
                                    else:
                                        lines.append("PE already below 30x target")
                                else:
                                    lines.append(
                                        f"EPS declining ({cagr * 100:.0f}%), PEG not applicable"
                                    )
                except Exception as e:
                    logger.warning("Forward PE calc failed for %s: %s", code, e)
        except Exception as e:
            logger.warning("Consensus EPS forecast failed for %s: %s", code, e)

        if not lines:
            raise NoMarketDataError(ticker, code, "all fundamentals sources returned nothing")

        header = f"# Company Fundamentals for {code} (A-stock)\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        return header + "\n".join(lines)

    except NoMarketDataError:
        raise
    except Exception as e:
        logger.warning("fundamentals failed for %s: %s", code, e)
        raise NoMarketDataError(ticker, code, f"fundamentals retrieval failed: {e}") from e


# ---- 4. get_balance_sheet ----


def _sina_stock_code(code: str) -> str:
    """Pure 6-digit code → sina format (sh688017 / sz000001 / bj832000)."""
    return f"{_get_prefix(code)}{code}"


def _secucode(code: str) -> str:
    """6-digit A-stock code → Eastmoney SECUCODE (600519.SH / 000001.SZ / 832000.BJ)."""
    prefix = _get_prefix(code)
    return f"{code}.{prefix.upper()}"


# Eastmoney datacenter report descriptors for the three financial statements.
# RPT_DMSK_FN_BALANCE / RPT_DMSK_FN_INCOME are the "new" (2024+) simplified
# reports; RPT_F10_FINANCE_GCASHFLOW is the full cashflow report.
# Verified 2026-09 against live Eastmoney datacenter for 600519.
_EM_FINANCIAL_REPORTS = {
    "资产负债表": {
        "report_name": "RPT_DMSK_FN_BALANCE",
        # Key fields (full report has 57; select the headline items for CSV output)
        "columns": (
            "REPORT_DATE,NOTICE_DATE,TOTAL_ASSETS,FIXED_ASSET,MONETARYFUNDS,"
            "MONETARYFUNDS_RATIO,ACCOUNTS_RECE,ACCOUNTS_RECE_RATIO,INVENTORY,"
            "INVENTORY_RATIO,TOTAL_LIABILITIES,ACCOUNTS_PAYABLE,ACCOUNTS_PAYABLE_RATIO,"
            "TOTAL_EQUITY,TOTAL_EQUITY_RATIO,TOTAL_ASSETS_RATIO,TOTAL_LIAB_RATIO,"
            "CURRENT_RATIO,DEBT_ASSET_RATIO"
        ),
    },
    "利润表": {
        "report_name": "RPT_DMSK_FN_INCOME",
        "columns": (
            "REPORT_DATE,NOTICE_DATE,PARENT_NETPROFIT,TOTAL_OPERATE_INCOME,"
            "TOTAL_OPERATE_COST,TOE_RATIO,OPERATE_COST,OPERATE_EXPENSE,"
            "OPERATE_EXPENSE_RATIO,SALE_EXPENSE,MANAGE_EXPENSE,FINANCE_EXPENSE,"
            "OPERATE_PROFIT,TOTAL_PROFIT,INCOME_TAX,DEDUCT_PARENT_NETPROFIT,"
            "OPERATE_PROFIT_RATIO,PARENT_NETPROFIT_RATIO"
        ),
    },
    "现金流量表": {
        "report_name": "RPT_F10_FINANCE_GCASHFLOW",
        "columns": (
            "REPORT_DATE,NOTICE_DATE,NETCASH_OPERATE,NETCASH_INVEST,NETCASH_FINANCE,"
            "CCE_ADD,BEGIN_CCE,END_CCE,NETPROFIT,SALES_SERVICES,TOTAL_OPERATE_INFLOW,"
            "TOTAL_OPERATE_OUTFLOW,TOTAL_INVEST_INFLOW,TOTAL_INVEST_OUTFLOW,"
            "TOTAL_FINANCE_INFLOW,TOTAL_FINANCE_OUTFLOW"
        ),
    },
}


def _get_financial_report_em(
    code: str,
    report_type: str,
    freq: str,
    curr_date: str = None,
) -> pd.DataFrame:
    """Fetch financial report via Eastmoney datacenter (direct HTTP).

    Replaces the legacy Sina ``getFinanceReport2022`` endpoint which stopped
    returning report rows in 2024+. Uses Eastmoney's RPT_DMSK_FN_* / RPT_F10_*
    reports via ``_em_get`` (throttled, shares the a_stock session).

    report_type: '资产负债表' | '利润表' | '现金流量表'
    """
    spec = _EM_FINANCIAL_REPORTS.get(report_type)
    if spec is None:
        return pd.DataFrame()

    secucode = _secucode(code)
    params = {
        "reportName": spec["report_name"],
        "columns": spec["columns"],
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": "1",
        "pageSize": "20",
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    r = _em_get(_DATACENTER_URL, params=params, timeout=15)
    d = r.json()

    rows = d.get("result", {}).get("data") if d.get("result") else None
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    if "REPORT_DATE" in df.columns:
        df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"], errors="coerce")
        if curr_date:
            cutoff = pd.to_datetime(curr_date)
            df = df[df["REPORT_DATE"] <= cutoff]
        if freq.lower() == "annual":
            months = df["REPORT_DATE"].dt.month
            df = df[months == 12]

    return df.head(8)


def get_balance_sheet(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get balance sheet via Eastmoney datacenter (direct HTTP)."""
    code = _normalize_ticker(ticker)

    df = _get_financial_report_em(code, "资产负债表", freq, curr_date)

    if df.empty:
        raise NoMarketDataError(ticker, code, "no balance sheet rows from eastmoney")

    csv_string = df.to_csv(index=False)

    header = f"# Balance Sheet for {code} (A-stock, {freq})\n"
    header += "# Data source: eastmoney datacenter (direct HTTP)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string


# ---- 5. get_cashflow ----


def get_cashflow(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get cash flow statement via Eastmoney datacenter (direct HTTP)."""
    code = _normalize_ticker(ticker)

    df = _get_financial_report_em(code, "现金流量表", freq, curr_date)

    if df.empty:
        raise NoMarketDataError(ticker, code, "no cash flow rows from eastmoney")

    csv_string = df.to_csv(index=False)

    header = f"# Cash Flow for {code} (A-stock, {freq})\n"
    header += "# Data source: eastmoney datacenter (direct HTTP)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string


# ---- 6. get_income_statement ----


def get_income_statement(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get income statement via Eastmoney datacenter (direct HTTP)."""
    code = _normalize_ticker(ticker)

    df = _get_financial_report_em(code, "利润表", freq, curr_date)

    if df.empty:
        raise NoMarketDataError(ticker, code, "no income statement rows from eastmoney")

    csv_string = df.to_csv(index=False)

    header = f"# Income Statement for {code} (A-stock, {freq})\n"
    header += "# Data source: eastmoney datacenter (direct HTTP)\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    return header + csv_string


# ---- 7. get_news ----


def _fetch_news_eastmoney(code: str, page_size: int = 20) -> list[dict]:
    """Direct East Money search API for individual stock news."""
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    inner_param = {
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    params = {
        "cb": "callback",
        "param": _json.dumps(inner_param, ensure_ascii=False),
        "_": "1",
    }
    headers = {
        "Referer": "https://so.eastmoney.com/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
    }

    resp = _em_get(url, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    text = resp.text
    text = text[text.index("(") + 1 : text.rindex(")")]
    data = _json.loads(text)

    articles: list[dict] = []
    for item in data.get("result", {}).get("cmsArticleWebOld", []):
        articles.append(
            {
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "time": item.get("date", ""),
                "source": item.get("mediaName", "东方财富"),
                "url": item.get("url", ""),
            }
        )
    return articles


def _fetch_news_sina(code: str, page_size: int = 20) -> list[dict]:
    """Sina Finance stock news API (backup source)."""
    prefix = _get_prefix(code)
    url = (
        f"https://vip.stock.finance.sina.com.cn/corp/view/"
        f"vCB_AllNewsStock.php?symbol={prefix}{code}&Page=1"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
        ),
        "Referer": "https://finance.sina.com.cn/",
    }

    resp = _requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    resp.encoding = "gb2312"
    html = resp.text

    articles: list[dict] = []
    rows = _re.findall(
        r"(\d{4}-\d{2}-\d{2})\s*(?:&nbsp;)*(\d{2}:\d{2})\s*(?:&nbsp;)*"
        r"<a[^>]+href='([^']+)'[^>]*>([^<]+)</a>",
        html,
    )
    for date_str, time_str, link, title in rows[:page_size]:
        articles.append(
            {
                "title": title.strip(),
                "content": "",
                "time": f"{date_str} {time_str}",
                "source": "新浪财经",
                "url": link,
            }
        )
    return articles


def get_news(
    ticker: Annotated[str, "A-stock code"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get stock-specific news via East Money direct API (Sina as fallback).

    Raises NoMarketDataError when both sources fail to respond (network/source
    failure). Returns a "no news in range" string when sources respond but no
    articles match the date window (legitimate sparseness).
    """
    code = _normalize_ticker(ticker)

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    articles: list[dict] = []
    source_label = ""
    source_errors = 0

    try:
        articles = _fetch_news_eastmoney(code)
        source_label = "东方财富"
    except Exception as e:
        logger.warning("East Money news fetch failed for %s: %s", code, e)
        source_errors += 1

    if not articles:
        try:
            articles = _fetch_news_sina(code)
            source_label = "新浪财经"
        except Exception as e:
            logger.warning("Sina news fetch failed for %s: %s", code, e)
            source_errors += 1

    if not articles and source_errors >= 2:
        raise NoMarketDataError(ticker, code, "eastmoney and sina news sources both failed")

    if not articles:
        return f"No news found for A-stock '{code}'"

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
        source = art.get("source", source_label)
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
        return f"No news found for A-stock '{code}' between {start_date} and {end_date}"

    return f"## {code} (A-stock) News, from {start_date} to {end_date}:\n\n" + news_str


# ---- 8. get_global_news ----


def get_global_news(
    curr_date: Annotated[str, "Current date yyyy-mm-dd"],
    look_back_days: Annotated[int | None, "Days to look back; None = config default"] = None,
    limit: Annotated[int | None, "Max articles; None = config default"] = None,
) -> str:
    """Get China/global financial news via direct HTTP (CLS + Eastmoney).

    None for look_back_days/limit falls back to the configured
    ``global_news_lookback_days`` / ``global_news_article_limit``.
    """
    from .config import get_config

    config = get_config()
    if look_back_days is None:
        look_back_days = config.get("global_news_lookback_days", 7)
    if limit is None:
        limit = config.get("global_news_article_limit", 10)

    start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    all_news: list[dict] = []
    source_errors = 0

    # Source 1: CLS wire (财联社快讯) — direct HTTP
    try:
        cls_url = "https://www.cls.cn/nodeapi/telegraphList"
        cls_params = {"rn": str(limit), "page": "1"}
        cls_headers = {"User-Agent": _UA, "Referer": "https://www.cls.cn/"}
        r_cls = _requests.get(cls_url, params=cls_params, headers=cls_headers, timeout=10)
        d_cls = r_cls.json()
        for item in d_cls.get("data", {}).get("roll_data", []):
            title = item.get("title", "") or item.get("brief", "")
            content = item.get("content", "") or item.get("brief", "")
            ctime = item.get("ctime", "")
            pub_time = ""
            if ctime:
                try:
                    pub_time = datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d %H:%M")
                except (ValueError, TypeError, OSError):
                    pub_time = str(ctime)
            all_news.append(
                {
                    "title": title,
                    "content": content,
                    "time": pub_time,
                    "source": "CLS Wire",
                }
            )
    except Exception as e:
        logger.warning("CLS news fetch failed: %s", e)
        source_errors += 1

    # Source 2: Eastmoney global (东财7x24资讯) — direct HTTP
    try:
        em_url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        em_params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(limit),
            "req_trace": str(uuid.uuid4()),
        }
        em_headers = {"User-Agent": _UA, "Referer": "https://kuaixun.eastmoney.com/"}
        r_em = _em_get(em_url, params=em_params, headers=em_headers, timeout=10)
        d_em = r_em.json()
        for item in d_em.get("data", {}).get("fastNewsList", []):
            title = item.get("title", "")
            summary = item.get("summary", "")[:200]
            pub_time = item.get("showTime", "")
            all_news.append(
                {
                    "title": title,
                    "content": summary,
                    "time": pub_time,
                    "source": "Eastmoney Global",
                }
            )
    except Exception as e:
        logger.warning("Eastmoney global news fetch failed: %s", e)
        source_errors += 1

    if not all_news and source_errors >= 2:
        raise NoMarketDataError(curr_date, curr_date, "CLS and Eastmoney global news both failed")

    if not all_news:
        return f"No global news found for {curr_date}"

    seen: set[str] = set()
    unique: list[dict] = []
    for n in all_news:
        if n["title"] not in seen:
            seen.add(n["title"])
            unique.append(n)

    news_str = ""
    for n in unique[:limit]:
        news_str += f"### {n['title']} (source: {n['source']})\n"
        if n.get("content"):
            snippet = n["content"][:300] + "..." if len(n["content"]) > 300 else n["content"]
            news_str += f"{snippet}\n"
        news_str += "\n"

    return f"## China & Global Market News, from {start_date} to {curr_date}:\n\n" + news_str


# ---- 9. get_insider_transactions ----


def get_insider_transactions(
    ticker: Annotated[str, "A-stock code"],
) -> str:
    """Get shareholder/insider activity via mootdx F10.

    A-stock insider transaction data differs from US markets. Uses mootdx F10
    shareholder research as the closest equivalent.
    """
    code = _normalize_ticker(ticker)

    try:
        text = _mootdx_call("F10", symbol=code, name="股东研究")
    except Exception as e:
        logger.warning("mootdx F10 failed for %s: %s", code, e)
        raise NoMarketDataError(
            ticker, code, f"mootdx F10 shareholder research unavailable: {e}"
        ) from e

    if not text or not text.strip():
        raise NoMarketDataError(ticker, code, "mootdx F10 returned empty shareholder research")

    header = f"# Shareholder Research for {code} (A-stock)\n"
    header += "# Note: A-stock equivalent of insider transactions\n"
    header += "# Data source: mootdx F10\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    import re

    sec4_hits = list(re.finditer(r"\r?\n【4\.股东变化】\r?\n", text))
    if sec4_hits:
        sec4_pos = sec4_hits[-1].start()
        before_sec4 = text[:sec4_pos]
        sec4_text = text[sec4_pos:]
        cut_at = 2000
        if len(sec4_text) > cut_at:
            sec4_text = (
                sec4_text[:cut_at] + f"\n\n(... older shareholder history omitted, "
                f"{len(text) - sec4_pos - cut_at} chars truncated ...)"
            )
        text = before_sec4 + sec4_text

    return header + text
