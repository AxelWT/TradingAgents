import contextvars
from copy import deepcopy

import tradingagents.default_config as default_config

# Use default config but allow it to be overridden
_config: dict | None = None

# Per-run analysis market (cn/hk/us). Set by the graph at run start from the
# analyzed ticker so non-symbol data methods (get_macro_indicators,
# get_global_news, get_prediction_markets) can route to market-appropriate
# vendors. A ContextVar (not a key in ``_config``) so concurrent runs in the
# same process with different tickers don't clobber each other (#1290).
# ``None`` means "no run in progress" — callers fall back to "us".
analysis_market_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "analysis_market", default=None
)


def initialize_config():
    """Initialize the configuration with default values."""
    global _config
    if _config is None:
        _config = deepcopy(default_config.DEFAULT_CONFIG)


def _deep_merge(existing: dict, incoming: dict) -> dict:
    """Recursively merge ``incoming`` into ``existing`` in place.

    For each key: if both existing and incoming values are dicts, recurse;
    otherwise replace.
    """
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            _deep_merge(existing[key], value)
        else:
            existing[key] = value
    return existing


def set_config(config: dict):
    """Update the configuration with custom values.

    Dict-valued keys are recursively (deep) merged so a partial update like
    ``{"market_vendors": {"us": {"core_stock_apis": "alpha_vantage"}}}``
    preserves sibling categories within ``us`` and other markets entirely;
    scalar keys are replaced outright.
    """
    global _config
    initialize_config()
    incoming = deepcopy(config)
    _deep_merge(_config, incoming)


def get_config() -> dict:
    """Get the current configuration."""
    if _config is None:
        initialize_config()
    return deepcopy(_config)


# Initialize with default config
initialize_config()
