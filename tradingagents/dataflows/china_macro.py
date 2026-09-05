"""China macroeconomic indicator vendor for TradingAgents.

Direct-HTTP macro data for the A-share market context — no FRED_API_KEY needed.
Complements ``fred.py`` (US macro) so a CN analysis can ground macro commentary
in China-specific indicators (LPR, SHIBOR, CPI, PPI, PMI, M2, social financing,
RMB/USD) instead of only US series.

Data source: Eastmoney macro-data center (``datacenter-web.eastmoney.com`` and
``push2his.eastmoney.com``), the same direct-HTTP family the a_stock vendor
uses. Shares the ``_em_get`` throttle to avoid IP bans under multi-agent load.

Aliases are CN-specific (``lpr``, ``cn_cpi``, ``cn_pmi``, …) and deliberately
do not collide with FRED aliases (``cpi``, ``fed_funds_rate``, …), so a
``macro_data`` chain of ``china_macro,fred`` can serve both markets without one
masking the other.

Look-ahead (point-in-time) protection mirrors the a_stock vendor: most series
have historical daily/monthly observations, so a historical analysis date is
honoured by filtering rows to ``<= curr_date``; the few realtime-only series
(SHIBOR today) emit a snapshot warning when replayed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

import pandas as pd

from .a_stock import _em_get, _is_historical, _snapshot_notice
from .errors import NoMarketDataError

# Eastmoney datacenter base for macro reports.
_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


# ---------------------------------------------------------------------------
# Indicator catalogue
# ---------------------------------------------------------------------------
#
# Each entry maps a friendly alias → an Eastmoney report descriptor:
#   report_name  : the RPT_* identifier Eastmoney's datacenter uses
#   columns      : field codes to request
#   date_field   : the column holding the report date (used for filtering)
#   value_field  : the column holding the headline number
#   label        : human-readable name for output
#   unit         : unit suffix for display
#   sort         : sort column / direction for chronological order
#
# Aliases are prefixed (cn_*) where they'd collide with FRED aliases (cpi, ppi).
# Non-colliding ones (lpr, shibor, m2, rmb_usd) keep short names.
_INDICATORS: dict[str, dict] = {
    "lpr": {
        "report_name": "RPT_RATE_LPR",
        "columns": "REPORT_DATE,LPR1Y",
        "date_field": "REPORT_DATE",
        "value_field": "LPR1Y",
        "label": "Loan Prime Rate (1Y LPR)",
        "unit": "%",
        "sort_columns": "REPORT_DATE",
        "sort_types": "-1",
    },
    "shibor_overnight": {
        "report_name": "RPT_RATE_SHIBOR",
        "columns": "REPORT_DATE,ON",
        "date_field": "REPORT_DATE",
        "value_field": "ON",
        "label": "SHIBOR (overnight)",
        "unit": "%",
        "sort_columns": "REPORT_DATE",
        "sort_types": "-1",
    },
    "cn_cpi": {
        "report_name": "RPT_ECONOMY_CPI",
        "columns": "REPORT_DATE,CPI_YOY",
        "date_field": "REPORT_DATE",
        "value_field": "CPI_YOY",
        "label": "China CPI (YoY)",
        "unit": "%",
        "sort_columns": "REPORT_DATE",
        "sort_types": "-1",
    },
    "cn_ppi": {
        "report_name": "RPT_ECONOMY_PPI",
        "columns": "REPORT_DATE,PPI_YOY",
        "date_field": "REPORT_DATE",
        "value_field": "PPI_YOY",
        "label": "China PPI (YoY)",
        "unit": "%",
        "sort_columns": "REPORT_DATE",
        "sort_types": "-1",
    },
    "cn_pmi": {
        "report_name": "RPT_ECONOMY_PMI",
        "columns": "REPORT_DATE,MAKE_INDEX",
        "date_field": "REPORT_DATE",
        "value_field": "MAKE_INDEX",
        "label": "China Manufacturing PMI",
        "unit": "",
        "sort_columns": "REPORT_DATE",
        "sort_types": "-1",
    },
    "m2": {
        "report_name": "RPT_ECONOMY_MONEY_SUPPLY",
        "columns": "REPORT_DATE,M2_YOY",
        "date_field": "REPORT_DATE",
        "value_field": "M2_YOY",
        "label": "China M2 (YoY)",
        "unit": "%",
        "sort_columns": "REPORT_DATE",
        "sort_types": "-1",
    },
    "social_financing": {
        "report_name": "RPT_ECONOMY_FIN_SOCIAL",
        "columns": "REPORT_DATE,TOTAL_STOCK_YOY",
        "date_field": "REPORT_DATE",
        "value_field": "TOTAL_STOCK_YOY",
        "label": "Social Financing Stock (YoY)",
        "unit": "%",
        "sort_columns": "REPORT_DATE",
        "sort_types": "-1",
    },
    "rmb_usd": {
        # Central parity rate (中间价) from push2his daily kline.
        "report_name": "RPT_FX_RMBUSD",
        "columns": "REPORT_DATE,MIDDLE",
        "date_field": "REPORT_DATE",
        "value_field": "MIDDLE",
        "label": "USD/CNY central parity",
        "unit": "",
        "sort_columns": "REPORT_DATE",
        "sort_types": "-1",
    },
}


def _fetch_series(spec: dict, curr_date: str, look_back_days: int) -> pd.DataFrame:
    """Fetch a macro series from Eastmoney datacenter, filtered to the window.

    Returns a DataFrame with [date, value] columns, chronological, restricted to
    rows on or before curr_date (look-ahead protection) and within the look-back
    window. Raises NoMarketDataError when the source returns no rows.
    """
    params = {
        "reportName": spec["report_name"],
        "columns": spec["columns"],
        "filter": "",
        "pageNumber": "1",
        "pageSize": "500",
        "sortColumns": spec["sort_columns"],
        "sortTypes": spec["sort_types"],
        "source": "WEB",
        "client": "WEB",
    }
    r = _em_get(_DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    rows = d.get("result", {}).get("data") if d.get("result") else None
    if not rows:
        return pd.DataFrame(columns=["date", "value"])

    df = pd.DataFrame(rows)
    date_field = spec["date_field"]
    value_field = spec["value_field"]
    if date_field not in df.columns or value_field not in df.columns:
        return pd.DataFrame(columns=["date", "value"])

    df = df[[date_field, value_field]].copy()
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["date", "value"])

    cutoff = pd.to_datetime(curr_date)
    df = df[df["date"] <= cutoff]

    window_start = cutoff - pd.Timedelta(days=look_back_days)
    df = df[df["date"] >= window_start]

    # Eastmoney returns newest-first (sort_types=-1); reverse to chronological.
    return df.sort_values("date").reset_index(drop=True)


def get_macro_data(
    indicator: Annotated[str, "China macro indicator alias"],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format; window end"],
    look_back_days: Annotated[int | None, "Trailing window in days; None = 365"] = None,
) -> str:
    """Retrieve a China macroeconomic indicator time series (direct HTTP, keyless).

    Aliases (CN-specific, do not collide with FRED):
      lpr, shibor_overnight, cn_cpi, cn_ppi, cn_pmi, m2, social_financing, rmb_usd

    Returns the indicator name, unit, the latest in-window value, the change
    over the window, and an observation table. Historical analysis dates are
    honoured by filtering to rows on or before ``curr_date`` (point-in-time
    safety); realtime-only series emit a snapshot warning when replayed.

    Raises NoMarketDataError for an unknown alias or when the source returns no
    rows, so ``route_to_vendor`` can fall back to the next vendor (e.g. fred) or
    emit a unified sentinel.
    """
    spec = _INDICATORS.get(indicator)
    if spec is None:
        raise NoMarketDataError(
            indicator,
            indicator,
            f"unknown China macro alias '{indicator}'; choose from {sorted(_INDICATORS)}",
        )

    if look_back_days is None:
        look_back_days = 365

    try:
        df = _fetch_series(spec, curr_date, look_back_days)
    except Exception as e:
        raise NoMarketDataError(
            indicator,
            indicator,
            f"Eastmoney macro source for '{indicator}' failed: {e}",
        ) from e

    if df.empty:
        raise NoMarketDataError(
            indicator,
            indicator,
            f"no rows for '{indicator}' in the {look_back_days}-day window ending {curr_date}",
        )

    lines = [
        f"# {spec['label']}",
        "# Source: Eastmoney datacenter (direct HTTP, keyless)",
        f"# Window: last {look_back_days} days ending {curr_date}",
        f"# Unit: {spec['unit'] or '(index)'}",
        f"# Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # SHIBOR overnight is effectively realtime (today's fixing); on a historical
    # replay, the in-window historical rows are valid but the latest row may be
    # today's — flag it so the model doesn't treat today's fixing as that day's.
    if indicator == "shibor_overnight" and _is_historical(curr_date):
        lines.insert(0, _snapshot_notice(curr_date, spec["label"]))

    latest = df.iloc[-1]
    first = df.iloc[0]
    delta = latest["value"] - first["value"]
    lines.append(f"Latest ({latest['date'].strftime('%Y-%m-%d')}): {latest['value']}{spec['unit']}")
    lines.append(
        f"Window start ({first['date'].strftime('%Y-%m-%d')}): {first['value']}{spec['unit']}"
    )
    sign = "+" if delta >= 0 else ""
    lines.append(f"Change over window: {sign}{delta:.4f}{spec['unit']}")
    lines.append("")

    # Cap the table at ~40 rows for token budget (matches FRED's MAX_ROWS policy).
    table_df = df.tail(40)
    lines.append("| Date | Value |")
    lines.append("|---|---:|")
    for _, row in table_df.iterrows():
        lines.append(f"| {row['date'].strftime('%Y-%m-%d')} | {row['value']}{spec['unit']} |")

    if len(df) > 40:
        lines.append(f"\n(Showing the latest 40 of {len(df)} in-window observations.)")

    return "\n".join(lines)
