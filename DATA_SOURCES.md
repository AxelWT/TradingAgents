# TradingAgents 数据源分析报告

> 本文档梳理 `tradingagents/dataflows/` 模块用到的全部数据源、对应 API 地址、使用方式及鉴权要求。

---

## 一、整体架构

数据访问由 `tradingagents/dataflows/interface.py` 统一调度。它通过 `VENDOR_METHODS` 注册表将 6 类工具路由到不同数据源：

| 工具类别 | 工具列表 |
|---|---|
| `core_stock_apis` | `get_stock_data` |
| `technical_indicators` | `get_indicators` |
| `fundamental_data` | `get_fundamentals`、`get_balance_sheet`、`get_cashflow`、`get_income_statement` |
| `news_data` | `get_news`、`get_global_news`、`get_insider_transactions` |
| `macro_data` | `get_macro_indicators` |
| `prediction_markets` | `get_prediction_markets` |

默认厂商链配置在 `default_config.py:158-184`，按市场（`us`/`cn`/`hk`）分组、按顺序尝试，失败则降级到下一个。`macro_data` 与 `prediction_markets` 属于 `OPTIONAL_CATEGORIES`（`interface.py:106`），失败时降级为哨兵字符串而非中断运行。

---

## 二、数据源清单总览

| 数据源 | API 地址 | 是否需要 Key | 默认角色 | 是否走路由 |
|---|---|---|---|---|
| **Yahoo Finance** | `query{1,2}.finance.yahoo.com`（经 yfinance 库） | 否（免 key） | 美股/港股主源、A 股备选 | 是 |
| **a_stock** | mootdx TCP（7709）+ Sina/Tencent/Eastmoney/THS/CLS 直连 HTTP | 否（免 key） | A 股主源 | 是 |
| **china_macro** | Eastmoney 数据中心 `datacenter-web.eastmoney.com` | 否（免 key） | A 股宏观主源 | 是 |
| **Alpha Vantage** | `https://www.alphavantage.co/query` | 是 `ALPHA_VANTAGE_API_KEY` | 末位兜底 | 是 |
| **FRED** | `https://api.stlouisfed.org/fred` | 是 `FRED_API_KEY` | 美国宏观主源 | 是 |
| **Polymarket** | `https://gamma-api.polymarket.com` | 否（免 key） | 预测市场唯一源 | 是 |
| **Reddit** | `https://www.reddit.com/r/{sub}/search.rss` | 否（免 key） | 情绪数据 | **否**（直连） |
| **StockTwits** | `https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json` | 否（免 key） | 情绪数据 | **否**（直连） |

### 需要的环境变量
- `ALPHA_VANTAGE_API_KEY` — `alpha_vantage_common.py:30`
- `FRED_API_KEY` — `fred.py:86`
- 可选缓存目录：`TRADINGAGENTS_CACHE_DIR`、`TRADINGAGENTS_RESULTS_DIR`

---

## 三、各数据源详细说明

### 1. Yahoo Finance（主数据源）

**文件**：`y_finance.py`、`yfinance_news.py`

**API 地址**：yfinance 库内部访问 `https://query1.finance.yahoo.com/` 与 `https://query2.finance.yahoo.com/`（如 `v8/chart`、`v10/quoteSummary`）。代码中未硬编码 base URL。

**提供的数据**：
- **OHLCV 行情** — `get_YFin_data_online`（`y_finance.py:49-99`），经 `ticker.history()`
- **技术指标** — `get_stock_stats_indicators_window`（`y_finance.py:102-237`），通过 stockstats 计算：`close_50_sma`、`close_200_sma`、`close_10_ema`、`macd`、`macds`、`macdh`、`rsi`、`boll`、`boll_ub`、`boll_lb`、`atr`、`vwma`、`mfi`
- **基本面** — `get_fundamentals`（`y_finance.py:300-364`），经 `ticker.info`：行业、市值、PE、PB、EPS、股息率、Beta、52 周高低、营收、EBITDA、ROE、ROA、负债权益比、自由现金流等
- **资产负债表** — `get_balance_sheet`（`y_finance.py:367-399`）
- **现金流** — `get_cashflow`（`y_finance.py:402-434`）
- **利润表** — `get_income_statement`（`y_finance.py:437-469`）
- **内部人交易** — `get_insider_transactions`（`y_finance.py:472-494`）
- **个股新闻** — `get_news_yfinance`（`yfinance_news.py:75-132`），经 `yf.Ticker(canonical).get_news()`
- **全球宏观新闻** — `get_global_news_yfinance`（`yfinance_news.py:135-231`），经 `yf.Search()` 并行查询 5 个宏观主题（`default_config.py:124-130`）

**使用方式**：作为 `core_stock_apis`、`technical_indicators`、`fundamental_data`、`news_data` 四大类的默认主源。通过 `VENDOR_METHODS`（`interface.py:99-145`）注册，经 `@tool` 包装暴露给 LLM Agent。所有入口先经 `normalize_symbol`（`symbol_utils.py:99`）做符号归一化（如 `XAUUSD` → `GC=F`）。调用经 `yf_retry`（`stockstats_utils.py:49-73`）包装，限流时 3 次指数退避后转 `VendorRateLimitError`，路由跳到下一厂商。

**鉴权**：免 key。

---

### 2. a_stock（A 股主源）

**文件**：`a_stock.py`

**API 地址**：多源混合，全部直连 HTTP/TCP（无统一 SDK）：
- **mootdx**（TCP 7709）— OHLCV K 线、F10、股票列表（`a_stock.py:12,444`）。经 `_get_mootdx_client`（`:367`）懒初始化，多服务器探测 + BESTIP 保护。
- **Sina HTTP** — K 线兜底（`_sina_kline_fallback`，`:603`）、最新价补充（`_supplement_stale_ohlcv_with_sina`，`:691`）
- **Tencent 实时行情** — `_tencent_quote`（`:464`）
- **Eastmoney 数据中心** — `_em_get`/`_eastmoney_datacenter`（`:530,546`），基本面快照
- **同花顺（THS）** — EPS 预测（`_ths_eps_forecast`，`:578`）
- **CLS（财联社）/百度** — 新闻等

**提供的数据**：A 股全链路 — OHLCV、技术指标、基本面、三大报表、新闻、内部人交易、全球新闻。仅处理 A 股符号；非 A 股抛 `NoMarketDataError` 让路由降级。

**使用方式**：CN 市场 `core_stock_apis`/`technical_indicators` 主源，`fundamental_data`/`news_data` 唯一源（`default_config.py:173-176`）。A 股符号归一化 `_normalize_ticker`（`:95`），正则识别 6 位代码 + `sh/sz` 前缀 + `.SS/.SZ/.SH` 后缀。OHLCV 经 mootdx 取 800 根日 K（~3 年），mootdx 失败转 Sina HTTP；缓存按符号落盘 CSV。原始 DataFrame 加载器 `_load_ohlcv_astock`（`:716`）供 `load_ohlcv_routed` 使用。

**鉴权**：免 key。mootdx 未安装或全部 TDX 服务器不可达时快速失败（`_mootdx_unavailable_until`，`:429`）。

---

### 3. china_macro（A 股宏观主源）

**文件**：`china_macro.py`

**API 地址**：Eastmoney 宏观数据中心 `_DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"`（`:34`）及 `push2his.eastmoney.com`，直连 HTTP（无 SDK）。

**提供的数据**：中国宏观经济序列 — LPR、SHIBOR、CPI、PPI、PMI、M2、社融、GDP 等。

**使用方式**：CN 市场 `macro_data` 主源（`default_config.py:177`，`china_macro,fred`）。公开函数 `get_macro_data(indicator, curr_date, look_back_days)`（`:183`）。属于可选类别，失败降级为哨兵字符串。供 **News Analyst** 使用。

**鉴权**：免 key。

---

### 4. Alpha Vantage（末位兜底）

**文件**：`alpha_vantage_common.py`、`alpha_vantage_fundamentals.py`、`alpha_vantage_indicator.py`、`alpha_vantage_news.py`、`alpha_vantage_stock.py`、`alpha_vantage.py`

**API 地址**：`API_BASE_URL = "https://www.alphavantage.co/query"`（`alpha_vantage_common.py:11`）。所有请求经 `_make_api_request(function_name, params)`（`alpha_vantage_common.py:62-112`），30s 超时，附加 `source=trading_agents` 参数。

**调用的 API 函数**：
- `TIME_SERIES_DAILY_ADJUSTED` — 日 OHLCV（`alpha_vantage_stock.py:38`）
- `SMA`/`EMA`/`MACD`/`RSI`/`BBANDS`/`ATR` — 技术指标（`alpha_vantage_indicator.py:80-132`）
- `OVERVIEW` — 公司概览（`alpha_vantage_fundamentals.py:36`）
- `BALANCE_SHEET` / `CASH_FLOW` / `INCOME_STATEMENT` — 三大报表（`alpha_vantage_fundamentals.py:41, 47, 53`）
- `NEWS_SENTIMENT` — 个股新闻与全球宏观新闻（`alpha_vantage_news.py:24, 53`）
- `INSIDER_TRANSACTIONS` — 内部人交易（`alpha_vantage_news.py:71`）

**使用方式**：所有多厂商链中的末位兜底（`core_stock_apis`、`technical_indicators`、`fundamental_data`、`news_data`）。免费层 25 次/天，"emergency only"。VWMA 指标不直接支持，返回提示信息（`alpha_vantage_indicator.py:134-136`）。限流处理（`alpha_vantage_common.py:99-110`）：响应含 `rate limit`/`call frequency` 等关键词抛 `AlphaVantageRateLimitError`；含 `api key`/`apikey` 抛 `AlphaVantageNotConfiguredError`。另提供原始 DataFrame 加载器 `_load_ohlcv_alpha_vantage`（`alpha_vantage_stock.py:43`），解析 `TIME_SERIES_DAILY_ADJUSTED` CSV 为 `Date/Open/High/Low/Close/Volume`（`adjusted_close`→`Close`，5 年窗口），供 `load_ohlcv_routed` 兜底使用。

**鉴权**：需要 `ALPHA_VANTAGE_API_KEY`（`alpha_vantage_common.py:28-35`）。缺失抛 `AlphaVantageNotConfiguredError`。

---

### 5. FRED（美国宏观主源）

**文件**：`fred.py`

**API 地址**：`FRED_API_BASE = "https://api.stlouisfed.org/fred"`（`fred.py:21`）。两个端点：
- `GET /fred/series?series_id=...` — 序列元数据（`fred.py:168`）
- `GET /fred/series/observations?series_id=...&observation_start=...&observation_end=...` — 观测值（`fred.py:180-188`）

请求附带 `api_key`、`file_type=json`，30s 超时。

**提供的数据**：宏观经济时间序列 — 政策利率、国债收益率、通胀、就业、增长、货币供给、信心、房地产。别名映射（`MACRO_SERIES`，`fred.py:37-72`）：
- `fed_funds_rate` → `FEDFUNDS`
- `10y_treasury` → `DGS10`，`2y_treasury` → `DGS2`，`10y_2y_spread` → `T10Y2Y`
- `cpi` → `CPIAUCSL`，`core_pce` → `PCEPILFE`，`inflation_expectations` → `T10YIE`
- `real_gdp` → `GDPC1`，`unemployment_rate` → `UNRATE`，`nonfarm_payrolls` → `PAYEMS`，`initial_claims` → `ICSA`
- `vix` → `VIXCLS`，`dollar_index` → `DTWEXBGS`，`consumer_sentiment` → `UMCSENT`

**使用方式**：US 市场 `macro_data` 主源（`default_config.py:164`），CN 链中作为 `china_macro` 的兜底（`china_macro,fred`，`default_config.py:177`）。公开函数 `get_macro_data(indicator, curr_date, look_back_days=None)`（`fred.py:136-237`）。默认回看 365 天（`DEFAULT_LOOKBACK_DAYS`，`fred.py:29`），输出表上限 40 行（`MAX_ROWS`，`fred.py:33`）。`_resolve_series_id`（`fred.py:95-115`）同时接受友好别名或原始 FRED 序列 ID。属于可选类别，失败降级为哨兵字符串。供 **News Analyst** 使用。

**鉴权**：需要 `FRED_API_KEY`（`fred.py:84-92`）。免费申请：https://fred.stlouisfed.org/docs/api/api_key.html 。缺失抛 `FredNotConfiguredError`。

---

### 6. Polymarket（预测市场唯一源）

**文件**：`polymarket.py`

**API 地址**：`GAMMA_BASE = "https://gamma-api.polymarket.com"`（`polymarket.py:20`）。端点 `GET /public-search?q=<topic>&limit_per_type=20`（`polymarket.py:86`），30s 超时。

**提供的数据**：前瞻性事件的市场隐含概率（Fed 决议/衰退/选举/地缘/加密）。`outcomePrices` 即各结果（如 "Yes"）的隐含概率。`_is_forward_looking`（`polymarket.py:47-65`）仅保留仍开放且未来结算的市场。

**使用方式**：`prediction_markets` 类别唯一厂商（`default_config.py:148`）。公开函数 `get_prediction_markets(topic, limit=None)`（`polymarket.py:68-139`）返回 markdown 报告，含每个市场的隐含概率、交易量、结算日期、1 周变动。默认 6 个市场（`DEFAULT_LIMIT`，`polymarket.py:26`）。属于可选类别，失败降级为哨兵。供 **News Analyst** 作为新闻和宏观数据的补充。

**鉴权**：免 key，免注册。

---

### 7. Reddit（情绪源，绕过路由直连）

**文件**：`reddit.py`

**API 地址**：
- `_RSS = "https://www.reddit.com/r/{sub}/search.rss?{qs}"`（`reddit.py:36`）— 默认路径
- `_API = "https://www.reddit.com/r/{sub}/search.json?{qs}"`（`reddit.py:35`）— 因 WAF 拦截 403 默认不用（issue #862）
- User-Agent：`"tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"`
- 查询参数：`q=<ticker>&restrict_sr=on&sort=new&t=week&limit=<n>`

**提供的数据**：财经子版最近 7 天提及该 ticker 的帖子。默认子版：`wallstreetbets`、`stocks`、`investing`（`reddit.py:47`）。RSS 路径无评分/评论数（标签 `source="rss"`，格式化器省略指标而非打印假 0）。

**使用方式**：**不在 `VENDOR_METHODS` 中，不经 `route_to_vendor`**。由 sentiment analyst 直接调用：
- `tradingagents/agents/analysts/sentiment_analyst.py:43` — `from tradingagents.dataflows.reddit import fetch_reddit_posts`
- `sentiment_analyst.py:75` — `ex.submit(fetch_reddit_posts, ticker)`（与 StockTwits、新闻在 3-worker 线程池并行，`sentiment_analyst.py:72-78`）

公开函数 `fetch_reddit_posts(ticker, subreddits=DEFAULT_SUBREDDITS, limit_per_sub=5, timeout=10.0, inter_request_delay=1.0)`（`reddit.py:189-245`）。优雅降级，始终返回字符串、永不抛异常。遇 429 按 `Retry-After` 退避一次（上限 30s，`reddit.py:82-88, 111-118`）。

**鉴权**：免 key。

---

### 8. StockTwits（情绪源，绕过路由直连）

**文件**：`stocktwits.py`

**API 地址**：`_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"`（`stocktwits.py:24`）。默认超时 10s。

**提供的数据**：个股最近消息流。每条消息含用户标注情绪（`Bullish`/`Bearish`/null）、正文、时间戳、发布者。函数统计多空/未标注数量与百分比，列出每条消息（正文截断 280 字符）。

**使用方式**：**同 Reddit，不在 `VENDOR_METHODS`，不经路由**。由 sentiment analyst 直接调用：
- `sentiment_analyst.py:44` — `from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages`
- `sentiment_analyst.py:74` — `ex.submit(fetch_stocktwits_messages, ticker, 30)`（并行）

公开函数 `fetch_stocktwits_messages(ticker, limit=30, timeout=10.0)`（`stocktwits.py:28-83`）。始终返回字符串、永不抛异常，失败返回 `<stocktwits unavailable: ...>`。

**鉴权**：免 key，免 OAuth。

---

## 四、市场感知路由（`market_vendors` × 供应商 × 降级链）

供应商链配置在 `default_config.py:158-184` 的 `market_vendors`，按市场（`us`/`cn`/`hk`）分组。`classify_market`（`symbol_utils.py:208`）依据符号语法判定市场：6 位代码→`cn`、`XXXX.HK`→`hk`、其余→`us`。`get_vendor`（`interface.py:196`）按优先级解析链：`tool_vendors[method]`（最高，市场无关）→ `market_vendors[market][category]` → `"default"` 哨兵（展开为该 method 在 `VENDOR_METHODS` 中全部厂商）。

### 4.1 `route_to_vendor` 路径（分析师主流程）

| 类别 / 方法 | US 市场 | CN 市场 | HK 市场 |
|---|---|---|---|
| **core_stock_apis** `get_stock_data` | yfinance → alpha_vantage | a_stock → yfinance | yfinance（单源） |
| **technical_indicators** `get_indicators` | yfinance → alpha_vantage | a_stock → yfinance | *default* → alpha_vantage, yfinance, a_stock |
| **fundamental_data** `get_fundamentals`/`get_balance_sheet`/`get_cashflow`/`get_income_statement` | yfinance → alpha_vantage | a_stock（单源） | *default* → yfinance, alpha_vantage, a_stock |
| **news_data** `get_news`/`get_global_news`/`get_insider_transactions` | yfinance → alpha_vantage | a_stock（单源） | *default* → yfinance, alpha_vantage, a_stock |
| **macro_data** `get_macro_indicators` | fred（单源） | china_macro → fred | *default* → fred, china_macro |
| **prediction_markets** `get_prediction_markets` | polymarket（单源） | polymarket（单源） | *default* → polymarket |

> `get_insider_transactions` 已实现但当前无 analyst 调用。`macro_data`/`prediction_markets` 属 `OPTIONAL_CATEGORIES`（`interface.py:106`），失败降级为哨兵字符串而非中断运行。HK 默认仅配 `core_stock_apis`/`fundamental_data`，其余类别落到 `"default"` 哨兵。

### 4.2 `load_ohlcv_routed` 路径（验证快照 + 部分指标底层）

`get_verified_market_snapshot`（`market_data_validator.py:72`）与 `StockstatsUtils.get_stock_stats`（`stockstats_utils.py:374`）不调字符串接口，而是经 `load_ohlcv_routed` 取**原始 DataFrame**。该函数同样读 `core_stock_apis` 配置（与 `get_stock_data` 同源），按 vendor 分派到 raw loader：

| Vendor | Raw loader | 说明 |
|---|---|---|
| yfinance | `load_ohlcv`（`stockstats_utils.py:193`） | 5 年窗口，`auto_adjust` |
| a_stock | `_load_ohlcv_astock`（`a_stock.py:716`） | mootdx TCP + Sina HTTP，800 bars |
| alpha_vantage | `_load_ohlcv_alpha_vantage`（`alpha_vantage_stock.py:43`） | 5 年窗口，`adjusted_close`→`Close` |

各市场的快照/指标 raw 路径降级链：

| 方法 | US | CN | HK |
|---|---|---|---|
| **`get_verified_market_snapshot`** | `load_ohlcv` → `_load_ohlcv_alpha_vantage` | `_load_ohlcv_astock` → `load_ohlcv` | `load_ohlcv` |
| **`StockstatsUtils.get_stock_stats`** | 同上 | 同上 | 同上 |

### 4.3 降级（fallback）触发条件

下列异常会让 `route_to_vendor` / `load_ohlcv_routed` 跳到链中下一厂商（`interface.py:258-283`，`stockstats_utils.py:346-365`）：
- `NoMarketDataError` — 空数据 / 数据陈旧
- `VendorRateLimitError` — 限流（如 yfinance 429、AV 速率限制）
- `VendorNotConfiguredError` — 缺 API key / 配置

路由行为：配置的厂商串即有序链，**不会静默降级到用户未选的厂商**（issue #988/#289）。`route_to_vendor` 全部失败返回 `NO_DATA_AVAILABLE: ...` 哨兵（`interface.py:289-309`）；`load_ohlcv_routed` 全部失败优先抛 `NoMarketDataError`，否则抛首个真实错误。

### 4.4 同源说明

`get_verified_market_snapshot` 与 `get_stock_data` 现已**同源**：读同一份 `market_vendors`/`tool_vendors` 配置、用同一批 raw loader、支持同样的 fallback 链。用户修改 `market_vendors.cn.core_stock_apis` 或设 `tool_vendors["get_stock_data"]` 对两条路径同时生效。验证快照由代码确定性计算（最新 OHLCV 行 + 固定指标集 + 近期收盘），供 market analyst 作为精确数值声明的 ground truth（防 LLM 编造价格，issue #830）。

---

## 五、支撑模块（非数据源）

### `stockstats_utils.py` — OHLCV 加载与指标计算共享层
- `yf_retry(func, max_retries=3, base_delay=2.0)`（`:30-54`）— 包装 yfinance 调用，限流退避
- `load_ohlcv(symbol, curr_date)`（`:193-275`）— yfinance OHLCV 加载器，5 年每符号磁盘缓存，防前视 bias
- `load_ohlcv_routed(symbol, curr_date)`（`:319-371`）— 配置驱动的 DataFrame 加载器，读 `market_vendors`（与 `get_stock_data` 同源）并按 vendor 分派到 raw loader（`_load_ohlcv_for_vendor`，`:292`），支持 fallback 链。供 `market_data_validator.py` 与 `StockstatsUtils` 使用
- `_assert_ohlcv_not_stale(...)`（`:139-173`）— 拒绝超过 10 天的 stale 数据（issue #1021）
- `StockstatsUtils.get_stock_stats`（`:374-395`）— 经 `stockstats.wrap` 的单日指标查询，底层经 `load_ohlcv_routed`

### `symbol_utils.py` — 符号归一化
`normalize_symbol(raw)`（`:99-133`）将券商/TradingView/MT5 风格符号映射到 Yahoo Finance 规范：
- 显式别名表（`:53-70`）：`XAUUSD→GC=F`、`XAGUSD→SI=F`、`WTICOUSD→CL=F`、`SPX500→^GSPC`、`NAS100→^NDX`、`UK100→^FTSE`、`HK50→^HSI`
- 加密规则（`:83-96`）：已知加密币种对 USD/USDT/USDC → `BASE-USD`
- 外汇规则（`:126`）：6 字母符号拆分为两 ISO-4217 代码 → `PAIR=X`

### `market_data_validator.py` — 确定性快照
`build_verified_market_snapshot(symbol, curr_date, look_back_days=30, indicators=None)`（`:74-176`）调用 `load_ohlcv_routed` 生成"已验证市场快照"喂给 market analyst，防止 LLM 编造价格（issue #830）。固定指标集 `DEFAULT_SNAPSHOT_INDICATORS`（`:22-34`）：10 EMA、50/200 SMA、RSI、布林带、MACD、ATR。经 `agents/utils/market_data_validation_tools.py:5,23` 暴露为 `get_verified_market_snapshot` 工具。

### `errors.py` — 厂商错误分类
驱动 `route_to_vendor` 降级逻辑（`:21-55`）：
- `VendorError` — 基类
- `NoMarketDataError(symbol, canonical, detail)` — 无可用行（空或 stale）
- `VendorRateLimitError` — 瞬时限流 → 路由跳下一厂商
- `VendorNotConfiguredError`（同时是 `ValueError`）— 缺 key/配置

---

## 六、数据流全景图

```
   ┌──────────────────────────────────────────────────────────────┐
   │ classify_market(symbol)  →  us / cn / hk   (symbol_utils.py)  │
   └──────────────┬───────────────────────────────────────────────┘
                  │ 市场决定 market_vendors[market][category] 链
                  ▼
   ┌─────────────────────────────────────────┐   ┌──────────────────────────────┐
   │ route_to_vendor()  (interface.py)       │   │ load_ohlcv_routed()          │
   │ 分析师主流程（字符串接口）              │   │ (stockstats_utils.py)         │
   │ get_stock_data / get_indicators /       │   │ get_verified_market_snapshot │
   │ get_fundamentals / get_news / ...       │   │ + StockstatsUtils 指标底层   │
   └──────────────┬──────────────────────────┘   └──────────────┬───────────────┘
                  │ 按 core_stock_apis 链同源分派                │
                  ▼                                              ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  US:  yfinance → alpha_vantage        CN:  a_stock → yfinance            │
   │  HK:  yfinance                         宏观 US: fred  CN: china_macro→fred│
   └──────────────────────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────┐
   │ sentiment_analyst.py (ThreadPool 直连)  │
   └──────────────┬──────────────────────────┘
                  ▼
        Reddit  +  StockTwits  +  Yahoo News
        (不走路由，不在 VENDOR_METHODS)
```
