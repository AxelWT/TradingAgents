import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.db import database as _db_mod
from app.db.models import AnalysisTask

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None


def _get_main_loop() -> asyncio.AbstractEventLoop:
    global _main_loop
    if _main_loop is None or _main_loop.is_closed():
        try:
            _main_loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                _main_loop = asyncio.get_event_loop()
            except RuntimeError:
                _main_loop = asyncio.new_event_loop()
    return _main_loop


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, task_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active[task_id] = websocket

    def disconnect(self, task_id: str):
        self.active.pop(task_id, None)

    async def push(self, task_id: str, message: dict):
        ws = self.active.get(task_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(task_id)


manager = ConnectionManager()


class WebSocketCallbackAdapter:
    def __init__(self, task_id: str, loop: asyncio.AbstractEventLoop | None = None):
        self.task_id = task_id
        self.loop = loop or _get_main_loop()

    def _push_sync(self, message: dict):
        try:
            ws = manager.active.get(self.task_id)
            if ws:
                future = asyncio.run_coroutine_threadsafe(
                    manager.push(self.task_id, message), self.loop
                )
                future.result(timeout=5)
            else:
                logger.warning(
                    "No active WS for task %s, message type=%s skipped",
                    self.task_id,
                    message.get("type"),
                )
        except Exception as e:
            logger.warning("WS push failed for task %s: %s", self.task_id, e)

    def on_agent_start(self, agent_name: str):
        self._push_sync(
            {
                "type": "agent_status",
                "agent": agent_name,
                "status": "in_progress",
            }
        )

    def on_agent_finish(self, agent_name: str):
        self._push_sync(
            {
                "type": "agent_status",
                "agent": agent_name,
                "status": "completed",
            }
        )

    def on_tool_call(self, agent_name: str, tool_name: str, args: dict):
        self._push_sync(
            {
                "type": "tool_call",
                "agent": agent_name,
                "tool": tool_name,
                "args": args,
            }
        )

    def on_report_update(self, section: str, content: str):
        self._push_sync(
            {
                "type": "report",
                "section": section,
                "content": content,
            }
        )

    def on_stats_update(self, stats: dict):
        self._push_sync(
            {
                "type": "stats",
                **stats,
            }
        )

    def on_message(self, msg_type: str, content: str):
        self._push_sync(
            {
                "type": "message",
                "msg_type": msg_type,
                "content": content,
            }
        )

    def on_complete(
        self, signal: str, rating: str, final_report: str, agent_reports: dict, token_usage: dict
    ):
        self._push_sync(
            {
                "type": "complete",
                "signal": signal,
                "rating": rating,
                "final_report": final_report,
                "agent_reports": agent_reports,
                "token_usage": token_usage,
            }
        )

    def on_error(self, error: str):
        self._push_sync(
            {
                "type": "error",
                "message": error,
            }
        )


ANALYST_AGENT_NAMES = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}

ANALYST_REPORT_MAP = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}

ANALYST_ORDER = ["market", "social", "news", "fundamentals"]

FIXED_AGENTS = {
    "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
    "Trading Team": ["Trader"],
    "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
    "Portfolio Management": ["Portfolio Manager"],
}


def run_analysis_task(
    task_id: str, config: dict, user_id: str, loop: asyncio.AbstractEventLoop | None = None
):
    db: Session = _db_mod.SessionLocal()
    try:
        task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()
        if task is None:
            return

        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        db.commit()

        logger.info("Waiting for WebSocket connection for task %s", task_id)
        for _ in range(30):
            if manager.active.get(task_id):
                logger.info("WebSocket connected for task %s, starting analysis", task_id)
                break
            time.sleep(1)
        else:
            logger.warning(
                "Timed out waiting for WebSocket for task %s, proceeding without live updates",
                task_id,
            )

        adapter = WebSocketCallbackAdapter(task_id, loop=loop)

        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.graph.analyst_execution import (
            AnalystWallTimeTracker,
            build_analyst_execution_plan,
            get_initial_analyst_node,
            sync_analyst_tracker_from_chunk,
        )
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        run_config = DEFAULT_CONFIG.copy()
        run_config["max_debate_rounds"] = config.get("research_depth", 2)
        run_config["max_risk_discuss_rounds"] = config.get("research_depth", 2)

        _PROVIDER_DEFAULTS = {
            "deepseek": {
                "deep_think_llm": "deepseek-v4-pro",
                "quick_think_llm": "deepseek-v4-flash",
            },
            "openai": {"deep_think_llm": "gpt-4.1", "quick_think_llm": "gpt-4.1-mini"},
        }
        provider = config.get("llm_provider", "openai").lower()
        run_config["llm_provider"] = provider
        _pd = _PROVIDER_DEFAULTS.get(provider, {})
        run_config["deep_think_llm"] = config.get("deep_think_llm") or _pd.get(
            "deep_think_llm", DEFAULT_CONFIG.get("deep_think_llm")
        )
        run_config["quick_think_llm"] = config.get("quick_think_llm") or _pd.get(
            "quick_think_llm", DEFAULT_CONFIG.get("quick_think_llm")
        )
        run_config["output_language"] = config.get("output_language", "English")
        if config.get("backend_url"):
            run_config["backend_url"] = config["backend_url"]
        if config.get("google_thinking_level"):
            run_config["google_thinking_level"] = config["google_thinking_level"]
        if config.get("openai_reasoning_effort"):
            run_config["openai_reasoning_effort"] = config["openai_reasoning_effort"]
        if config.get("anthropic_effort"):
            run_config["anthropic_effort"] = config["anthropic_effort"]

        selected_analysts = [a for a in ANALYST_ORDER if a in config.get("analysts", ANALYST_ORDER)]

        graph = TradingAgentsGraph(
            selected_analysts,
            config=run_config,
            debug=True,
            callbacks=[],
        )

        instrument_context = graph.resolve_instrument_context(
            config["ticker"], config.get("asset_type", "stock")
        )
        init_agent_state = graph.propagator.create_initial_state(
            config["ticker"],
            config["trade_date"],
            asset_type=config.get("asset_type", "stock"),
            instrument_context=instrument_context,
        )
        args = graph.propagator.get_graph_args()

        all_agent_names = []
        for a in selected_analysts:
            all_agent_names.append(ANALYST_AGENT_NAMES[a])
        for team_agents in FIXED_AGENTS.values():
            all_agent_names.extend(team_agents)
        for name in all_agent_names:
            adapter.on_agent_start.__wrapped__(name) if hasattr(
                adapter.on_agent_start, "__wrapped__"
            ) else None

        first_analyst = ANALYST_AGENT_NAMES.get(selected_analysts[0], "Market Analyst")
        adapter.on_agent_start(first_analyst)

        report_sections = {}
        agent_status = {name: "pending" for name in all_agent_names}
        agent_status[first_analyst] = "in_progress"

        trace = []
        start_time = time.time()

        for chunk in graph.graph.stream(init_agent_state, **args):
            for message in chunk.get("messages", []):
                content = _extract_content(getattr(message, "content", None))
                if content and content.strip():
                    if isinstance(message, HumanMessage):
                        if content.strip() != "Continue":
                            adapter.on_message("User", content)
                    elif isinstance(message, AIMessage):
                        adapter.on_message("Agent", content[:500])
                    elif isinstance(message, ToolMessage):
                        adapter.on_message("Data", content[:300])

                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tc in message.tool_calls:
                        tool_name = tc["name"] if isinstance(tc, dict) else tc.name
                        tool_args = tc["args"] if isinstance(tc, dict) else tc.args
                        adapter.on_tool_call("Agent", tool_name, tool_args)

            found_active = False
            for analyst_key in selected_analysts:
                agent_name = ANALYST_AGENT_NAMES[analyst_key]
                report_key = ANALYST_REPORT_MAP[analyst_key]
                if chunk.get(report_key):
                    report_sections[report_key] = chunk[report_key]
                    adapter.on_report_update(report_key, chunk[report_key])
                    agent_status[agent_name] = "completed"
                    adapter.on_agent_finish(agent_name)
                elif not found_active and agent_status.get(agent_name) != "completed":
                    if agent_status.get(agent_name) != "in_progress":
                        adapter.on_agent_start(agent_name)
                    agent_status[agent_name] = "in_progress"
                    found_active = True

            if chunk.get("investment_debate_state"):
                debate = chunk["investment_debate_state"]
                for name in ["Bull Researcher", "Bear Researcher", "Research Manager"]:
                    if agent_status.get(name) == "pending":
                        adapter.on_agent_start(name)
                        agent_status[name] = "in_progress"
                if debate.get("judge_decision", "").strip():
                    for name in ["Bull Researcher", "Bear Researcher", "Research Manager"]:
                        agent_status[name] = "completed"
                        adapter.on_agent_finish(name)
                    report_sections["investment_plan"] = debate["judge_decision"]
                    adapter.on_report_update("investment_plan", debate["judge_decision"])
                    adapter.on_agent_start("Trader")
                    agent_status["Trader"] = "in_progress"
                elif debate.get("bull_history", "").strip():
                    adapter.on_report_update(
                        "investment_plan", f"### Bull\n{debate['bull_history']}"
                    )
                elif debate.get("bear_history", "").strip():
                    adapter.on_report_update(
                        "investment_plan", f"### Bear\n{debate['bear_history']}"
                    )

            if chunk.get("trader_investment_plan"):
                report_sections["trader_investment_plan"] = chunk["trader_investment_plan"]
                adapter.on_report_update("trader_investment_plan", chunk["trader_investment_plan"])
                if agent_status.get("Trader") != "completed":
                    agent_status["Trader"] = "completed"
                    adapter.on_agent_finish("Trader")
                    for name in ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"]:
                        adapter.on_agent_start(name)
                        agent_status[name] = "in_progress"

            if chunk.get("risk_debate_state"):
                risk = chunk["risk_debate_state"]
                if risk.get("aggressive_history", "").strip():
                    adapter.on_report_update(
                        "final_trade_decision", f"### Aggressive\n{risk['aggressive_history']}"
                    )
                if risk.get("conservative_history", "").strip():
                    adapter.on_report_update(
                        "final_trade_decision", f"### Conservative\n{risk['conservative_history']}"
                    )
                if risk.get("neutral_history", "").strip():
                    adapter.on_report_update(
                        "final_trade_decision", f"### Neutral\n{risk['neutral_history']}"
                    )
                judge = risk.get("judge_decision", "").strip()
                if judge and agent_status.get("Portfolio Manager") != "completed":
                    adapter.on_agent_start("Portfolio Manager")
                    agent_status["Portfolio Manager"] = "in_progress"
                    adapter.on_report_update("final_trade_decision", f"### PM Decision\n{judge}")
                    for name in [
                        "Aggressive Analyst",
                        "Neutral Analyst",
                        "Conservative Analyst",
                        "Portfolio Manager",
                    ]:
                        agent_status[name] = "completed"
                        adapter.on_agent_finish(name)

            elapsed = time.time() - start_time
            adapter.on_stats_update(
                {
                    "elapsed_seconds": int(elapsed),
                    "reports_done": len([v for v in report_sections.values() if v]),
                    "reports_total": 7,
                }
            )

            trace.append(chunk)

        final_state = {}
        for c in trace:
            final_state.update(c)

        signal = ""
        rating = ""
        try:
            signal_result = graph.process_signal(final_state.get("final_trade_decision", ""))
            signal = signal_result if isinstance(signal_result, str) else str(signal_result)
        except Exception:
            signal = "N/A"

        final_report = final_state.get("final_trade_decision", "")
        agent_reports = {k: v for k, v in report_sections.items() if v}

        task.status = "completed"
        task.signal = signal
        task.rating = rating
        task.final_report = final_report
        task.agent_reports = agent_reports
        task.token_usage = {
            "elapsed_seconds": int(time.time() - start_time),
        }
        task.completed_at = datetime.now(timezone.utc)
        db.commit()

        adapter.on_complete(signal, rating, final_report, agent_reports, task.token_usage)

    except Exception as e:
        task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()
        if task:
            task.status = "failed"
            task.error_message = str(e)
            task.completed_at = datetime.now(timezone.utc)
            db.commit()
        adapter.on_error(str(e))
    finally:
        db.close()


def _extract_content(content) -> str | None:
    if content is None or content == "":
        return None
    if isinstance(content, str):
        return content.strip() if content.strip() else None
    if isinstance(content, dict):
        text = content.get("text", "")
        return text.strip() if text else None
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        result = " ".join(p.strip() for p in parts if p and p.strip())
        return result if result else None
    return str(content).strip() if content else None
