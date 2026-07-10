"""Company-name → ticker lookup.

Given a company name (Chinese or English), ask the quick/cheap LLM for up to
three candidate tickers, then validate each one against Yahoo Finance to filter
out LLM hallucinations. Auth-gated so anonymous users can't run up the bill.
"""

import asyncio
import json
import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user
from app.db.models import User
from app.ticker.schemas import (
    TickerCandidate,
    TickerLookupRequest,
    TickerLookupResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ticker", tags=["ticker"])

# Provider → quick/cheap model. Mirrors analysis/runner.py; the ticker lookup
# has no provider parameter from the frontend, so we default to DeepSeek (the
# only provider whose API key is configured in this deployment).
_PROVIDER_DEFAULTS = {
    "deepseek": "deepseek-v4-flash",
    "openai": "gpt-4.1-mini",
}

_SYSTEM_PROMPT = (
    "You are a financial-instrument symbol resolver. Given a company or asset "
    "name (Chinese or English), return up to 3 matching Yahoo Finance ticker "
    "symbols. Use canonical Yahoo suffixes: Hong Kong → .HK (e.g. 0700.HK), "
    "Shanghai → .SS (e.g. 600519.SS), Shenzhen → .SZ, Tokyo → .T, London → .L; "
    "crypto uses '-' (e.g. BTC-USD). Respond with ONLY a JSON object, no prose: "
    '{"candidates":[{"ticker":"AAPL","name":"Apple Inc.","exchange":"NasdaqGS"}]}. '
    "If unsure, return fewer candidates rather than guesses."
)


def _extract_json_object(text: str) -> dict | None:
    """Pull the first balanced {...} block out of an LLM reply.

    LLMs usually wrap JSON in ```json fences or add stray commentary; this
    keeps parsing robust without a strict schema library dependency.
    """
    # Strip ``` fences first.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    # Fallback: first {...} substring by brace matching.
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


async def _llm_candidates(company_name: str) -> list[dict]:
    """Ask the quick/cheap LLM for raw ticker candidates."""
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.llm_clients.factory import create_llm_client
    from langchain_core.messages import HumanMessage, SystemMessage

    cfg = DEFAULT_CONFIG
    # DEFAULT_CONFIG 把 "openai" 焊死成 llm_provider 默认值(default_config.py:88),
    # 用 .get(...) 拿到的永远是真值 "openai",`or` fallback 不会触发。
    # 直接读环境变量,只有用户显式设了 TRADINGAGENTS_LLM_PROVIDER 才尊重;否则
    # 退回本部署实际配置的 DeepSeek。
    provider = os.getenv("TRADINGAGENTS_LLM_PROVIDER") or "deepseek"
    model = os.getenv("TRADINGAGENTS_QUICK_THINK_LLM") or _PROVIDER_DEFAULTS.get(
        provider, "deepseek-v4-flash"
    )
    try:
        llm = create_llm_client(
            provider=provider,
            model=model,
            base_url=cfg.get("backend_url"),
        ).get_llm()
    except Exception as exc:  # noqa: BLE001 — surface as 503, not a 500 stack
        logger.warning("ticker lookup: LLM client init failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lookup service is unavailable (LLM not configured).",
        ) from exc

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f'Company/asset name: "{company_name}"'),
    ]
    try:
        # Keep the blocking langchain call off the event loop.
        response = await asyncio.to_thread(llm.invoke, messages)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ticker lookup: LLM invoke failed: %s", exc)
        return []

    content = getattr(response, "content", "")
    if not isinstance(content, str):
        content = str(content)
    parsed = _extract_json_object(content)
    if not parsed or not isinstance(parsed.get("candidates"), list):
        return []
    return [
        c
        for c in parsed["candidates"]
        if isinstance(c, dict) and isinstance(c.get("ticker"), str) and c["ticker"].strip()
    ][:3]


def _validate_candidate(raw_ticker: str) -> tuple[str, str | None, str | None]:
    """Reverse-lookup a ticker via yfinance.

    Returns (canonical_ticker, company_name_or_None, exchange_or_None).
    """
    from tradingagents.agents.utils.agent_utils import resolve_instrument_identity
    from tradingagents.dataflows.symbol_utils import normalize_symbol

    normalized = normalize_symbol(raw_ticker)
    identity = resolve_instrument_identity(normalized)
    name = identity.get("company_name")
    exchange = identity.get("exchange")
    return normalized, name, exchange


@router.post("/lookup", response_model=TickerLookupResponse)
async def lookup(
    req: TickerLookupRequest,
    current_user: User = Depends(get_current_user),
):
    raw_candidates = await _llm_candidates(req.company_name.strip())
    if not raw_candidates:
        return TickerLookupResponse(candidates=[])

    # Validate in parallel — each yfinance call is network-bound (~0.5s).
    results = await asyncio.gather(
        *[asyncio.to_thread(_validate_candidate, c["ticker"]) for c in raw_candidates],
        return_exceptions=True,
    )

    candidates: list[TickerCandidate] = []
    for raw, result in zip(raw_candidates, results):
        raw_name = str(raw.get("name") or "").strip()
        raw_exchange = raw.get("exchange")
        if isinstance(result, Exception) or result is None:
            candidates.append(
                TickerCandidate(
                    ticker=str(raw["ticker"]).strip().upper(),
                    name=raw_name or str(raw["ticker"]).strip().upper(),
                    exchange=raw_exchange if isinstance(raw_exchange, str) else None,
                    validated=False,
                )
            )
            continue
        canonical, name, exchange = result
        validated = bool(name)
        candidates.append(
            TickerCandidate(
                ticker=canonical.upper(),
                name=name or raw_name or canonical.upper(),
                exchange=exchange or (raw_exchange if isinstance(raw_exchange, str) else None),
                validated=validated,
            )
        )

    # Validated entries first; cap at 3.
    candidates.sort(key=lambda c: not c.validated)
    return TickerLookupResponse(candidates=candidates[:3])
