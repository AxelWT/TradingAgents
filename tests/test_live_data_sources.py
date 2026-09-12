"""直连真实数据源集成测试。

与现有 mock 化的 unit 测试不同，本模块直接调用各数据源供应商的真实接口
（不经任何 mock / patch），获取真实数据并通过日志打印出来，用于人工核验
数据通路是否畅通、返回内容是否合理。

运行方式（需联网）::

    # 直连测试默认跳过（避免在无网络/CI 环境中失败）。设置环境变量开启：
    RUN_LIVE_DATA_TESTS=1 pytest -s tests/test_live_data_sources.py

    # 仅跑免 key 的数据源
    RUN_LIVE_DATA_TESTS=1 pytest -s tests/test_live_data_sources.py -k "YFinance or Polymarket or Reddit or StockTwits or AStock or ChinaMacro"

    # 仅跑需要 key 的（需在 .env 配置真实 ALPHA_VANTAGE_API_KEY / FRED_API_KEY）
    RUN_LIVE_DATA_TESTS=1 pytest -s tests/test_live_data_sources.py -k "AlphaVantage or Fred"

``-s`` 关闭 pytest 输出捕获，使 ``[LIVE DATA]`` 日志实时打印到终端。

覆盖的数据源供应商（对应 ``DATA_SOURCES.md``）：

| 供应商 | 模块 | 是否需要 Key | 测试内容 |
|---|---|---|---|
| Yahoo Finance | y_finance / yfinance_news | 否 | OHLCV / 指标 / 基本面 / 三大报表 / 内部人交易 / 个股新闻 / 全球新闻 |
| a_stock (A 股) | a_stock | 否 | OHLCV / 指标 / 基本面 / 新闻 / 全球新闻 |
| china_macro | china_macro | 否 | LPR / CPI / PMI 等宏观序列 |
| Alpha Vantage | alpha_vantage | 是 | OHLCV / 指标 / 基本面 |
| FRED | fred | 是 | 美国宏观序列 |
| Polymarket | polymarket | 否 | 预测市场隐含概率 |
| Reddit | reddit | 否 | 情绪帖子 |
| StockTwits | stocktwits | 否 | 情绪消息流 |

所有测试标记为 ``@pytest.mark.integration``。本模块整体由 ``RUN_LIVE_DATA_TESTS``
环境变量门控：未设置时全部跳过（保持默认 ``pytest`` / CI 绿色），设置后按需再
通过 ``skipif`` 在缺少真实 API key 时跳过对应供应商。免 key 数据源在联网时可
直接拉取真实返回。
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, timedelta

import pytest

# 在模块导入（collection 阶段）即加载 .env，使真实 API key 进入 os.environ。
# conftest.py 的 autouse fixture 对 ALPHA_VANTAGE_API_KEY 等做
# `os.environ.get(x) or "placeholder"` 处理：若 .env 已注入真实 key 则保留，
# 否则降级为 placeholder（对应的 skipif 会跳过测试）。
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv 缺失时退化为纯环境变量读取
    pass

# ---------------------------------------------------------------------------
# 日志配置：把真实数据通过 logger 打印到 stderr，配合 `pytest -s` 实时查看。
# ---------------------------------------------------------------------------
logger = logging.getLogger("live_data_sources")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("\n>>> [LIVE DATA] %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# 直连门控：未设置 RUN_LIVE_DATA_TESTS 时跳过全部测试，避免无网络/CI 中失败。
# ---------------------------------------------------------------------------
_LIVE_ENABLED = os.environ.get("RUN_LIVE_DATA_TESTS", "") in ("1", "true", "yes")
pytestmark = pytest.mark.skipif(
    not _LIVE_ENABLED,
    reason="直连测试默认跳过；设置 RUN_LIVE_DATA_TESTS=1 后运行（需联网）",
)


# ---------------------------------------------------------------------------
# 日期窗口辅助
# ---------------------------------------------------------------------------
_TODAY = date.today()
_END = _TODAY.strftime("%Y-%m-%d")
_START = (_TODAY - timedelta(days=14)).strftime("%Y-%m-%d")  # 近 2 周（OHLCV / 新闻）
_START_LONG = (_TODAY - timedelta(days=150)).strftime("%Y-%m-%d")  # 指标回看窗口
# 指标测试用的 curr_date：比今天早 3 天，避开 yfinance 返回的"未结算最新 bar"
# （最新交易日 OHLC 为 NaN、只有 Volume，load_ohlcv 守卫会故意抛 NoMarketDataError）。
_IND_END = (_TODAY - timedelta(days=3)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# API key 检测（跳过条件）
# ---------------------------------------------------------------------------
def _has_real_key(env_var: str) -> bool:
    val = os.environ.get(env_var, "")
    return bool(val) and val != "placeholder"


_skip_no_av = pytest.mark.skipif(
    not _has_real_key("ALPHA_VANTAGE_API_KEY"),
    reason="ALPHA_VANTAGE_API_KEY 未设置（或为 placeholder），跳过 Alpha Vantage 直连测试",
)
_skip_no_fred = pytest.mark.skipif(
    not _has_real_key("FRED_API_KEY"),
    reason="FRED_API_KEY 未设置（或为 placeholder），跳过 FRED 直连测试",
)


def _log_and_assert_real(result: str, *, vendor: str, min_len: int = 10) -> str:
    """打印真实返回内容并断言它是有效数据（非空、非错误哨兵）。"""
    logger.info("[%s] 返回内容（%d 字符）:\n%s", vendor, len(result), result)
    assert isinstance(result, str), f"{vendor}: 返回类型应为 str，实得 {type(result)}"
    assert len(result) >= min_len, f"{vendor}: 返回内容过短（{len(result)} 字符），可能为空"
    # 排除降级哨兵（路由层 / 供应商在不可用时会返回此类字符串）
    for sentinel in ("DATA_UNAVAILABLE", "NO_DATA_AVAILABLE"):
        assert sentinel not in result, f"{vendor}: 命中降级哨兵 {sentinel}"
    return result


def _log_best_effort(result: str, *, vendor: str) -> str:
    """打印真实返回内容，但不做强断言。

    用于已知会因数据源单点不稳定 / 免费层降级而返回空或占位的场景
    （如 Sina 报表端点、AV 免费层 OVERVIEW、Eastmoney 部分宏观 report）。
    直连测试的价值在于"看到真实返回"，而非在这些外部不稳定点上 fail。
    """
    logger.info("[%s] 返回内容（%d 字符）:\n%s", vendor, len(result), result)
    assert isinstance(result, str), f"{vendor}: 返回类型应为 str，实得 {type(result)}"
    return result


# ===========================================================================
# 1. Yahoo Finance（免 key，yfinance 库）
# ===========================================================================
@pytest.mark.integration
class TestYFinanceLive:
    """直连 Yahoo Finance，覆盖行情 / 指标 / 基本面 / 报表 / 新闻全链路。"""

    def test_ohlcv_stock_data(self):
        from tradingagents.dataflows.y_finance import get_YFin_data_online

        result = get_YFin_data_online("AAPL", _START, _END)
        _log_and_assert_real(result, vendor="yfinance.get_stock_data")
        assert "Close" in result  # CSV 表头含 Close 列

    def test_technical_indicators_window(self):
        from tradingagents.dataflows.y_finance import get_stock_stats_indicators_window

        # 用 _IND_END（早 3 天）而非 _END：yfinance 最新交易日 bar 的 OHLC 常为
        # NaN（未结算），load_ohlcv 守卫会故意抛 NoMarketDataError（issue #1201）。
        result = get_stock_stats_indicators_window("AAPL", "rsi", _IND_END, 30)
        _log_and_assert_real(result, vendor="yfinance.get_indicators")

    def test_fundamentals(self):
        from tradingagents.dataflows.y_finance import get_fundamentals

        result = get_fundamentals("AAPL", _END)
        _log_and_assert_real(result, vendor="yfinance.get_fundamentals")

    def test_balance_sheet(self):
        from tradingagents.dataflows.y_finance import get_balance_sheet

        result = get_balance_sheet("AAPL", "quarterly", _END)
        _log_and_assert_real(result, vendor="yfinance.get_balance_sheet")

    def test_cashflow(self):
        from tradingagents.dataflows.y_finance import get_cashflow

        result = get_cashflow("AAPL", "quarterly", _END)
        _log_and_assert_real(result, vendor="yfinance.get_cashflow")

    def test_income_statement(self):
        from tradingagents.dataflows.y_finance import get_income_statement

        result = get_income_statement("AAPL", "quarterly", _END)
        _log_and_assert_real(result, vendor="yfinance.get_income_statement")

    def test_insider_transactions(self):
        from tradingagents.dataflows.y_finance import get_insider_transactions

        result = get_insider_transactions("AAPL")
        # 内部人交易可能为空（合法），仅打印、不强断言长度
        logger.info("[yfinance.get_insider_transactions] 返回内容:\n%s", result)
        assert isinstance(result, str)

    def test_stock_news(self):
        from tradingagents.dataflows.yfinance_news import get_news_yfinance

        result = get_news_yfinance("AAPL", _START, _END)
        _log_and_assert_real(result, vendor="yfinance.get_news")

    def test_global_news(self):
        from tradingagents.dataflows.yfinance_news import get_global_news_yfinance

        result = get_global_news_yfinance(_END, look_back_days=7, limit=5)
        _log_and_assert_real(result, vendor="yfinance.get_global_news")


# ===========================================================================
# 2. a_stock（A 股主源，mootdx TCP + Sina/Tencent/Eastmoney HTTP，免 key）
# ===========================================================================
@pytest.mark.integration
class TestAStockLive:
    """直连 A 股数据源（贵州茅台 600519），覆盖行情 / 指标 / 基本面 / 新闻。"""

    SYMBOL = "600519"

    def test_ohlcv_stock_data(self):
        from tradingagents.dataflows.a_stock import get_stock_data

        result = get_stock_data(self.SYMBOL, _START, _END)
        _log_and_assert_real(result, vendor="a_stock.get_stock_data")

    def test_technical_indicators(self):
        from tradingagents.dataflows.a_stock import get_indicators

        result = get_indicators(self.SYMBOL, "rsi", _END, 30)
        _log_and_assert_real(result, vendor="a_stock.get_indicators")

    def test_fundamentals(self):
        from tradingagents.dataflows.a_stock import get_fundamentals

        result = get_fundamentals(self.SYMBOL, _END)
        _log_and_assert_real(result, vendor="a_stock.get_fundamentals")

    def test_balance_sheet(self):
        from tradingagents.dataflows.a_stock import get_balance_sheet

        # 三大报表已从 Sina（已失效）切到 Eastmoney datacenter（RPT_DMSK_FN_BALANCE）。
        result = get_balance_sheet(self.SYMBOL, "quarterly", _END)
        _log_and_assert_real(result, vendor="a_stock.get_balance_sheet")
        assert "TOTAL_ASSETS" in result  # Eastmoney 字段

    def test_cashflow(self):
        from tradingagents.dataflows.a_stock import get_cashflow

        result = get_cashflow(self.SYMBOL, "quarterly", _END)
        _log_and_assert_real(result, vendor="a_stock.get_cashflow")
        assert "NETCASH_OPERATE" in result  # Eastmoney 字段

    def test_income_statement(self):
        from tradingagents.dataflows.a_stock import get_income_statement

        result = get_income_statement(self.SYMBOL, "quarterly", _END)
        _log_and_assert_real(result, vendor="a_stock.get_income_statement")
        assert "PARENT_NETPROFIT" in result  # Eastmoney 字段

    def test_news(self):
        from tradingagents.dataflows.a_stock import get_news

        result = get_news(self.SYMBOL, _START, _END)
        # 新闻可能因日期窗口内无报道而返回 "No news"，仅打印并断言为字符串
        logger.info("[a_stock.get_news] 返回内容:\n%s", result)
        assert isinstance(result, str)

    def test_global_news(self):
        from tradingagents.dataflows.a_stock import get_global_news

        result = get_global_news(_END, look_back_days=7, limit=5)
        _log_and_assert_real(result, vendor="a_stock.get_global_news")


# ===========================================================================
# 3. china_macro（A 股宏观主源，Eastmoney 数据中心，免 key）
# ===========================================================================
@pytest.mark.integration
class TestChinaMacroLive:
    """直连东方财富宏观数据中心，拉取中国宏观经济序列。

    Eastmoney 2024+ 改版后已修复的字段映射（均经真实数据验证）：
      lpr  → RPTA_WEB_RATE / TRADE_DATE / LPR1Y        (3%)
      cn_cpi → RPT_ECONOMY_CPI / NATIONAL_SAME          (同比)
      cn_pmi → RPT_ECONOMY_PMI / MAKE_INDEX             (49.8)
      m2  → RPT_ECONOMY_CURRENCY_SUPPLY / FREE_CASH_SAME (11.6%)
      shibor_overnight → RPT_IMP_INTRESTRATEN / IR_RATE  (1.417%)
      social_financing → RPT_ECONOMY_RMB_LOAN / RMB_LOAN_SAME（代理指标）
    rmb_usd 数据源已下线（RPT_FX_RMBUSD 不存在），保留 best-effort。
    """

    @pytest.mark.parametrize(
        "indicator",
        ["lpr", "cn_cpi", "cn_ppi", "cn_pmi", "m2", "shibor_overnight", "social_financing"],
    )
    def test_macro_indicator(self, indicator):
        """已修复映射的指标走硬断言：直连拉取并打印真实数据。"""
        from tradingagents.dataflows.china_macro import get_macro_data

        result = get_macro_data(indicator, _END, look_back_days=365)
        _log_and_assert_real(result, vendor=f"china_macro.{indicator}")

    def test_rmb_usd_best_effort(self):
        """rmb_usd 数据源已下线（Eastmoney 不再提供中间价序列），best-effort。"""
        from tradingagents.dataflows.china_macro import get_macro_data
        from tradingagents.dataflows.errors import NoMarketDataError

        try:
            result = get_macro_data("rmb_usd", _END, look_back_days=365)
        except NoMarketDataError as e:
            logger.info("[china_macro.rmb_usd] 数据源已下线: %s", e)
            pytest.skip("china_macro.rmb_usd: Eastmoney 已下线 RPT_FX_RMBUSD 报表")
        _log_best_effort(result, vendor="china_macro.rmb_usd")


# ===========================================================================
# 4. Alpha Vantage（末位兜底，需 ALPHA_VANTAGE_API_KEY）
# ===========================================================================
@_skip_no_av
@pytest.mark.integration
class TestAlphaVantageLive:
    """直连 Alpha Vantage，覆盖 OHLCV / 指标 / 基本面。"""

    def test_stock_data(self):
        from tradingagents.dataflows.alpha_vantage import get_stock
        from tradingagents.dataflows.alpha_vantage_common import AlphaVantageRateLimitError

        # AV 免费版已把 TIME_SERIES_DAILY_ADJUSTED 划为 premium 端点，会抛
        # AlphaVantageRateLimitError（"premium endpoint"）。这是 AV 政策变更，
        # 非测试 bug：捕获后 skip，并在 AV 恢复免费访问时自动转为真实断言。
        try:
            result = get_stock("IBM", _START, _END)
        except AlphaVantageRateLimitError as e:
            logger.info("[alpha_vantage.get_stock] 命中 premium/限流: %s", e)
            pytest.skip("Alpha Vantage TIME_SERIES_DAILY_ADJUSTED 已转为 premium 端点")
        _log_and_assert_real(result, vendor="alpha_vantage.get_stock")

    def test_indicator(self):
        from tradingagents.dataflows.alpha_vantage import get_indicator

        result = get_indicator("IBM", "rsi", _END, 30)
        _log_and_assert_real(result, vendor="alpha_vantage.get_indicator")

    def test_fundamentals(self):
        from tradingagents.dataflows.alpha_vantage import get_fundamentals

        # AV 免费层 OVERVIEW 对部分标的返回空 {}（免费层降级）。get_indicator
        # 通路正常说明 key 有效，这里 best-effort 记录真实返回。
        result = get_fundamentals("IBM", _END)
        _log_best_effort(result, vendor="alpha_vantage.get_fundamentals")


# ===========================================================================
# 5. FRED（美国宏观主源，需 FRED_API_KEY）
# ===========================================================================
@_skip_no_fred
@pytest.mark.integration
class TestFredLive:
    """直连 FRED API，拉取美国宏观经济序列。"""

    @pytest.mark.parametrize(
        "indicator", ["fed_funds_rate", "10y_treasury", "cpi", "unemployment_rate"]
    )
    def test_macro_indicator(self, indicator):
        from tradingagents.dataflows.fred import get_macro_data

        result = get_macro_data(indicator, _END, look_back_days=365)
        _log_and_assert_real(result, vendor=f"fred.{indicator}")


# ===========================================================================
# 6. Polymarket（预测市场，免 key）
# ===========================================================================
@pytest.mark.integration
class TestPolymarketLive:
    """直连 Polymarket Gamma API，获取前瞻事件隐含概率。"""

    def test_prediction_markets(self):
        from tradingagents.dataflows.polymarket import get_prediction_markets

        result = get_prediction_markets("Fed rate cut", limit=5)
        _log_and_assert_real(result, vendor="polymarket.get_prediction_markets")


# ===========================================================================
# 7. Reddit（情绪源，免 key，绕过路由直连）
# ===========================================================================
@pytest.mark.integration
class TestRedditLive:
    """直连 Reddit RSS 搜索，获取 ticker 相关讨论帖。"""

    def test_fetch_posts(self):
        from tradingagents.dataflows.reddit import fetch_reddit_posts

        result = fetch_reddit_posts("AAPL", limit_per_sub=3, inter_request_delay=0.5)
        # Reddit 可能因 WAF/限流返回降级占位字符串，仅打印并断言为字符串
        logger.info("[reddit.fetch_reddit_posts] 返回内容:\n%s", result)
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# 8. StockTwits（情绪源，免 key，绕过路由直连）
# ===========================================================================
@pytest.mark.integration
class TestStockTwitsLive:
    """直连 StockTwits 公开消息流，获取个股情绪。"""

    def test_fetch_messages(self):
        from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages

        result = fetch_stocktwits_messages("AAPL", limit=10)
        # StockTwits 可能因网络返回降级占位字符串，仅打印并断言为字符串
        logger.info("[stocktwits.fetch_stocktwits_messages] 返回内容:\n%s", result)
        assert isinstance(result, str)
        assert len(result) > 0


# ===========================================================================
# 9. 路由层直连（通过 interface.route_to_vendor 端到端）
# ===========================================================================
@pytest.mark.integration
class TestRoutingLive:
    """通过统一路由接口 ``route_to_vendor`` 端到端直连，验证降级链在真实环境下工作。"""

    def test_route_stock_data_us(self):
        from tradingagents.dataflows.interface import route_to_vendor

        result = route_to_vendor("get_stock_data", "AAPL", _START, _END)
        _log_and_assert_real(result, vendor="route.get_stock_data[us]")

    def test_route_fundamentals_us(self):
        from tradingagents.dataflows.interface import route_to_vendor

        result = route_to_vendor("get_fundamentals", "AAPL", _END)
        _log_and_assert_real(result, vendor="route.get_fundamentals[us]")

    def test_route_macro_us(self):
        from tradingagents.dataflows.interface import route_to_vendor

        result = route_to_vendor("get_macro_indicators", "cpi", _END, 365)
        # macro_data 属可选类别，失败降级为哨兵；若 FRED key 在位则应返回真实数据
        logger.info("[route.get_macro_indicators[us]] 返回内容:\n%s", result)
        assert isinstance(result, str)
